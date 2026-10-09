"""Persistent WebSocket backend for the teleMER realtime browser simulator."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from llm_engine import AnswerAnalysis, LLMEngine
from logging_config import configure_logging
from questionnaire import Questionnaire


logger = configure_logging("realtime")
app = FastAPI(title="teleMER realtime call server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def empty_state() -> dict[str, Any]:
    return {
        "session_id": str(uuid.uuid4()),
        "status": "active",
        "current_question_id": "consent",
        "answers": {},
        "history": [],
    }


def local_analysis(question_id: str, text: str) -> AnswerAnalysis:
    """Keep the demo usable without an API key; Gemini replaces this in configured runs."""
    normalized_text = re.sub(r"[^\w\s]", "", text.strip().lower())
    answer_tokens = set(normalized_text.split())
    yes_values = {
        "yes", "y", "yeah", "yep", "sure", "okay", "ok", "agree", "agreed",
        "correct", "absolutely", "हाँ", "हां", "जी", "haan", "ha",
    }
    no_values = {
        "no", "n", "nah", "nope", "never", "नहीं", "नही", "न", "nahin", "nahi",
    }
    if question_id in {"consent", "prior_claim"}:
        if normalized_text in yes_values or answer_tokens & yes_values:
            value = "yes"
        elif normalized_text in no_values or answer_tokens & no_values:
            value = "no"
        else:
            return AnswerAnalysis(
                is_valid=False,
                confidence=0.0,
                needs_clarification=True,
                next_action="clarify",
                reason_code="ambiguous_boolean",
            )
    elif question_id == "policy_type":
        aliases = {"vehicle": "auto", "car": "auto", "घर": "home", "स्वास्थ्य": "health"}
        value = aliases.get(normalized_text, normalized_text)
        if value not in {"auto", "home", "health"}:
            return AnswerAnalysis(
                is_valid=False,
                confidence=0.0,
                needs_clarification=True,
                next_action="clarify",
                reason_code="invalid_choice",
            )
    else:
        value = text.strip()
    return AnswerAnalysis(
        is_valid=bool(value),
        normalized_answer=value or None,
        confidence=0.75,
        needs_clarification=not bool(value),
        next_action="ask_next" if value else "clarify",
        reason_code="valid" if value else "empty",
    )


async def analyze_answer(
    state: dict[str, Any],
    questionnaire: Questionnaire,
    text: str,
) -> AnswerAnalysis:
    question = questionnaire.get(state["current_question_id"])
    fast_analysis = local_analysis(question.id, text)
    if fast_analysis.is_valid and question.answer_type in {"boolean", "choice", "number"}:
        logger.info(
            "Answer analyzed locally session_id=%s question_id=%s valid=%s",
            state["session_id"],
            question.id,
            fast_analysis.is_valid,
        )
        return fast_analysis

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.info(
            "Gemini unavailable; using local analysis session_id=%s question_id=%s",
            state["session_id"],
            question.id,
        )
        return fast_analysis
    engine = LLMEngine(api_key=api_key)
    try:
        analysis = await asyncio.wait_for(
            asyncio.to_thread(
                engine.analyze_answer,
                question_id=question.id,
                question_text=question.text,
                answer_text=text,
                answer_type=question.answer_type,
                allowed_values=list(question.allowed_values),
                conversation_context=state["answers"],
            ),
            timeout=8,
        )
        logger.info(
            "Answer analyzed with Gemini session_id=%s question_id=%s valid=%s",
            state["session_id"],
            question.id,
            analysis.is_valid,
        )
        return analysis
    except (asyncio.TimeoutError, RuntimeError):
        logger.exception(
            "Gemini analysis failed; using local analysis session_id=%s question_id=%s",
            state["session_id"],
            question.id,
        )
        return fast_analysis


async def send_question(socket: WebSocket, questionnaire: Questionnaire, state: dict[str, Any]) -> None:
    question = questionnaire.get(state["current_question_id"])
    logger.info(
        "Sending question session_id=%s question_id=%s",
        state["session_id"],
        question.id,
    )
    await socket.send_json(
        {
            "type": "question",
            "question": {
                "id": question.id,
                "text": question.text,
                "spokenText": question.spoken_text,
                "answerType": question.answer_type,
                "allowedValues": list(question.allowed_values),
            },
        }
    )


async def process_transcript(
    socket: WebSocket,
    questionnaire: Questionnaire,
    state: dict[str, Any],
    text: str,
) -> None:
    if not text or state["status"] not in {"active", "clarify"}:
        return

    question_id = state["current_question_id"]
    analysis = await analyze_answer(state, questionnaire, text)
    transition = questionnaire.transition(question_id, analysis)
    logger.info(
        "Answer processed session_id=%s question_id=%s status=%s",
        state["session_id"],
        question_id,
        transition.status,
    )
    state["history"].append(
        {
            "questionId": question_id,
            "transcript": text,
            "analysis": analysis.model_dump(),
            "transition": transition.status,
        }
    )
    if analysis.normalized_answer:
        state["answers"][question_id] = analysis.normalized_answer
    state["status"] = transition.status
    await socket.send_json(
        {
            "type": "answer.processed",
            "questionId": question_id,
            "transcript": text,
            "analysis": analysis.model_dump(),
            "transition": transition.status,
        }
    )
    if transition.next_question_id:
        state["current_question_id"] = transition.next_question_id
        await send_question(socket, questionnaire, state)
    else:
        logger.info(
            "Call ended session_id=%s status=%s",
            state["session_id"],
            state["status"],
        )
        await socket.send_json({"type": "call.ended", "status": state["status"]})


@app.get("/health")
async def health() -> dict[str, str]:
    logger.debug("Health check")
    return {"status": "ok"}


@app.websocket("/ws/call")
async def call_socket(socket: WebSocket) -> None:
    await socket.accept()
    questionnaire = Questionnaire()
    state = empty_state()
    logger.info("Call session connected session_id=%s", state["session_id"])
    await socket.send_json({"type": "session.ready", "sessionId": state["session_id"]})
    await send_question(socket, questionnaire, state)

    try:
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(
                    code=message.get("code", 1000),
                    reason=message.get("reason", ""),
                )
            text_message = message.get("text")
            if text_message is None:
                continue
            payload = json.loads(text_message)
            message_type = payload.get("type")
            logger.info(
                "WebSocket message received session_id=%s message_type=%s",
                state["session_id"],
                message_type,
            )
            if message_type == "ping":
                await socket.send_json({"type": "pong"})
                continue
            if message_type == "reset":
                state = empty_state()
                logger.info("Call session reset session_id=%s", state["session_id"])
                await socket.send_json({"type": "session.ready", "sessionId": state["session_id"]})
                await send_question(socket, questionnaire, state)
                continue
            if message_type != "transcript.final":
                continue

            await process_transcript(
                socket,
                questionnaire,
                state,
                str(payload.get("text", "")).strip(),
            )
    except WebSocketDisconnect:
        logger.info("Call session disconnected session_id=%s", state["session_id"])
        return
    except Exception:
        logger.exception("Call session failed session_id=%s", state["session_id"])
        raise


logger.info("Realtime backend process initialized")
