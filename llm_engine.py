"""Google Gemini decision engine for teleMER conversation analysis."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


DEFAULT_MODEL = "gemini-3.5-flash-lite"


class ExtractedField(BaseModel):
    """One normalized field extracted from a customer answer."""

    key: str
    value: str


class AnswerAnalysis(BaseModel):
    """Validated result used by the conversation orchestrator."""

    is_valid: bool = Field(description="Whether the answer satisfies the question")
    normalized_answer: Optional[str] = Field(
        default=None,
        description="Answer normalized to the requested answer type",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool
    next_action: Literal["ask_next", "clarify", "transfer", "complete"]
    next_question_id: Optional[str] = None
    reason_code: str = Field(
        description="Short machine-readable reason such as valid, ambiguous, or invalid"
    )
    extracted_data: list[ExtractedField] = Field(default_factory=list)


class LLMEngine:
    """Analyze customer answers with a Google Gemini model.

    Set GOOGLE_API_KEY in the environment before creating this engine. The key
    is intentionally never accepted from or printed by the CLI arguments.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
    ) -> None:
        resolved_api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not resolved_api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Configure it in the environment before use."
            )

        self.model = model
        self.client = genai.Client(api_key=resolved_api_key)

    def analyze_answer(
        self,
        question_id: str,
        question_text: str,
        answer_text: str,
        answer_type: str,
        allowed_values: Optional[list[str]] = None,
        conversation_context: Optional[dict[str, str]] = None,
    ) -> AnswerAnalysis:
        """Extract and validate one answer without exposing unrelated state."""
        if not question_text.strip():
            raise ValueError("question_text must not be empty")
        if not answer_text.strip():
            raise ValueError("answer_text must not be empty")

        allowed_values_text = json.dumps(allowed_values or [], ensure_ascii=False)
        context_text = json.dumps(
            conversation_context or {},
            ensure_ascii=False,
        )
        prompt = f"""
You are a structured data extraction component for an insurance phone questionnaire.
Analyze only the customer's answer to the current question. Do not make a coverage,
pricing, eligibility, or claims decision. Do not invent missing information.

Current question id: {question_id}
Current question: {question_text}
Expected answer type: {answer_type}
Allowed values, if any: {allowed_values_text}
Relevant previously collected values: {context_text}
Customer answer: {answer_text}

Rules:
- Normalize dates, booleans, numbers, and choices when unambiguous.
- Set needs_clarification=true when the answer is incomplete, ambiguous, or conflicts
  with the expected type.
- Use next_action=clarify for an answer that needs a retry.
- Use next_action=transfer when the customer requests a human, expresses distress, or
  asks for something outside the questionnaire.
- Use next_action=ask_next only when the answer is valid and the application can route
  to another question.
- Use next_action=complete only when the current answer completes the questionnaire.
- next_question_id is only a suggestion for the deterministic questionnaire engine;
  leave it null when it cannot be safely inferred.
- Return only the requested JSON structure.
""".strip()

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnswerAnalysis,
                temperature=0.0,
            ),
        )
        response_text = response.text
        if not response_text:
            raise RuntimeError("Gemini returned an empty response")

        try:
            return AnswerAnalysis.model_validate_json(response_text)
        except ValueError as error:
            raise RuntimeError("Gemini returned invalid structured output") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze one questionnaire answer")
    parser.add_argument("question", help="Current questionnaire question")
    parser.add_argument("answer", help="Customer's answer")
    parser.add_argument("--question-id", default="current_question")
    parser.add_argument("--answer-type", default="text")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    engine = LLMEngine(model=args.model)
    analysis = engine.analyze_answer(
        question_id=args.question_id,
        question_text=args.question,
        answer_text=args.answer,
        answer_type=args.answer_type,
    )
    print(analysis.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
