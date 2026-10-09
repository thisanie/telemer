"""Streamlit voice-only simulator for the teleMER questionnaire."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from logging_config import configure_logging
from llm_engine import LLMEngine
from questionnaire import QUESTIONS, Questionnaire
from stt_engine import STTEngine
from tts_engine import TTSEngine


logger = configure_logging("streamlit")
ARTIFACT_DIR = Path("artifacts/streamlit_call")


st.set_page_config(page_title="teleMER Voice Call Simulator", page_icon="☎️")
st.title("teleMER Voice Call Simulator")
st.caption("Synthetic local call flow: listen, respond, transcribe, analyze, and continue.")


@st.cache_resource(show_spinner="Loading text-to-speech model...")
def get_tts_engine() -> TTSEngine:
    logger.info("Initializing text-to-speech engine")
    return TTSEngine()


@st.cache_resource(show_spinner="Loading speech-to-text model...")
def get_stt_engine() -> STTEngine:
    logger.info("Initializing speech-to-text engine")
    return STTEngine(language="hindi")


@st.cache_resource(show_spinner="Connecting to Gemini...")
def get_llm_engine() -> LLMEngine:
    logger.info("Initializing Gemini engine")
    return LLMEngine()


def get_call_state() -> dict:
    if "call_state" not in st.session_state:
        st.session_state.call_state = {
            "status": "ready",
            "current_question_id": "consent",
            "answers": {},
            "history": [],
        }
    return st.session_state.call_state


def reset_call() -> None:
    st.session_state.call_state = {
        "status": "active",
        "current_question_id": "consent",
        "answers": {},
        "history": [],
    }


def render_question_audio(question_id: str, spoken_text: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = ARTIFACT_DIR / f"question_{question_id}.wav"
    if not audio_path.exists():
        logger.info("Generating question audio question_id=%s", question_id)
        get_tts_engine().synthesize(spoken_text, audio_path)
    return audio_path


def process_response(
    questionnaire: Questionnaire,
    state: dict,
    question_id: str,
    uploaded_audio,
) -> None:
    logger.info("Processing response question_id=%s", question_id)
    response_path = ARTIFACT_DIR / f"response_{len(state['history']) + 1}.wav"
    response_path.write_bytes(uploaded_audio.getvalue())

    logger.info("Transcribing response question_id=%s", question_id)
    transcript = get_stt_engine().transcribe(response_path)
    question = questionnaire.get(question_id)
    logger.info("Analyzing response question_id=%s", question_id)
    analysis = get_llm_engine().analyze_answer(
        question_id=question.id,
        question_text=question.text,
        answer_text=transcript,
        answer_type=question.answer_type,
        allowed_values=list(question.allowed_values),
        conversation_context={
            key: value for key, value in state["answers"].items()
        },
    )
    transition = questionnaire.transition(question_id, analysis)
    logger.info(
        "Response processed question_id=%s status=%s",
        question_id,
        transition.status,
    )

    state["history"].append(
        {
            "question_id": question_id,
            "question": question.text,
            "transcript": transcript,
            "analysis": analysis.model_dump(),
            "transition": transition.message,
        }
    )
    if analysis.normalized_answer:
        state["answers"][question_id] = analysis.normalized_answer

    state["status"] = transition.status
    if transition.next_question_id:
        state["current_question_id"] = transition.next_question_id


def main() -> None:
    state = get_call_state()
    questionnaire = Questionnaire()

    with st.sidebar:
        st.subheader("Simulation controls")
        st.write("Gemini API key: " + ("configured" if os.getenv("GOOGLE_API_KEY") else "missing"))
        if st.button("Start new call", type="primary"):
            logger.info("Starting new Streamlit call")
            reset_call()
            st.rerun()
        st.divider()
        st.write(f"State: **{state['status']}**")
        st.write(f"Answers collected: **{len(state['answers'])}**")

    if state["status"] == "ready":
        st.info("Start a call to begin the voice-only simulation.")
        return

    if state["status"] in {"complete", "transferred", "clarify"} and state["current_question_id"] not in QUESTIONS:
        st.success("Call finished.")
    elif state["status"] in {"complete", "transferred"}:
        st.success("Call finished.")
    else:
        question = questionnaire.get(state["current_question_id"])
        st.subheader("Current question")
        st.write(question.text)
        st.audio(render_question_audio(question.id, question.spoken_text), format="audio/wav")

        uploaded_audio = st.audio_input("Record your answer")
        if uploaded_audio is not None:
            st.audio(uploaded_audio, format=uploaded_audio.type)
            if st.button("Analyze response", type="primary"):
                try:
                    with st.spinner("Transcribing and analyzing response..."):
                        process_response(
                            questionnaire,
                            state,
                            question.id,
                            uploaded_audio,
                        )
                    st.rerun()
                except Exception as error:
                    logger.exception(
                        "Could not process response question_id=%s",
                        question.id,
                    )
                    st.error(f"Could not process this response: {error}")

    if state["history"]:
        st.divider()
        st.subheader("Call transcript")
        for turn in state["history"]:
            with st.expander(turn["question_id"]):
                st.write("**Question:**", turn["question"])
                st.write("**Transcript:**", turn["transcript"])
                st.json(turn["analysis"])
                st.caption(turn["transition"])


if __name__ == "__main__":
    logger.info("Streamlit backend process starting")
    main()
