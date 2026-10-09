"""Deterministic conditional questionnaire for the teleMER demo call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from llm_engine import AnswerAnalysis


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    spoken_text: str
    answer_type: str
    allowed_values: tuple[str, ...] = ()
    route_by_answer: dict[str, str] = field(default_factory=dict)
    default_next: Optional[str] = None


@dataclass(frozen=True)
class Transition:
    next_question_id: Optional[str]
    status: str
    message: str


QUESTIONS: dict[str, Question] = {
    "consent": Question(
        id="consent",
        text="May teleMER ask you a few questions about your insurance request?",
        spoken_text="क्या टेलीमेर आपसे आपके बीमा अनुरोध के बारे में कुछ सवाल पूछ सकता है? कृपया हाँ या नहीं में जवाब दें।",
        answer_type="boolean",
        allowed_values=("yes", "no"),
        route_by_answer={"yes": "customer_name", "no": "do_not_call"},
    ),
    "customer_name": Question(
        id="customer_name",
        text="What is your full name?",
        spoken_text="आपका पूरा नाम क्या है?",
        answer_type="name",
        default_next="policy_type",
    ),
    "policy_type": Question(
        id="policy_type",
        text="What type of insurance are you asking about: auto, home, or health?",
        spoken_text="आप किस प्रकार के बीमा के बारे में पूछ रहे हैं: वाहन, घर या स्वास्थ्य?",
        answer_type="choice",
        allowed_values=("auto", "home", "health"),
        route_by_answer={
            "auto": "vehicle_count",
            "home": "property_type",
            "health": "dependents",
        },
    ),
    "vehicle_count": Question(
        id="vehicle_count",
        text="How many vehicles should we include in this request?",
        spoken_text="इस अनुरोध में कितने वाहन शामिल करने हैं?",
        answer_type="number",
        default_next="prior_claim",
    ),
    "property_type": Question(
        id="property_type",
        text="Is the property a house, apartment, or commercial space?",
        spoken_text="यह संपत्ति घर, अपार्टमेंट या व्यावसायिक स्थान है?",
        answer_type="choice",
        allowed_values=("house", "apartment", "commercial"),
        default_next="prior_claim",
    ),
    "dependents": Question(
        id="dependents",
        text="How many people should be included on the health insurance request?",
        spoken_text="स्वास्थ्य बीमा अनुरोध में कितने लोगों को शामिल करना है?",
        answer_type="number",
        default_next="prior_claim",
    ),
    "prior_claim": Question(
        id="prior_claim",
        text="Have you made an insurance claim in the last five years?",
        spoken_text="क्या आपने पिछले पाँच वर्षों में कोई बीमा दावा किया है? कृपया हाँ या नहीं में जवाब दें।",
        answer_type="boolean",
        allowed_values=("yes", "no"),
        route_by_answer={"yes": "claim_details", "no": "preferred_contact"},
    ),
    "claim_details": Question(
        id="claim_details",
        text="Briefly, what was the claim about?",
        spoken_text="संक्षेप में बताइए कि दावा किस बारे में था।",
        answer_type="text",
        default_next="preferred_contact",
    ),
    "preferred_contact": Question(
        id="preferred_contact",
        text="What is the best time for a licensed insurance representative to contact you?",
        spoken_text="लाइसेंस प्राप्त बीमा प्रतिनिधि आपसे संपर्क करने के लिए किस समय फोन करें?",
        answer_type="time",
        default_next="complete",
    ),
    "do_not_call": Question(
        id="do_not_call",
        text="Understood. We will not continue this call.",
        spoken_text="समझ गया। हम यह कॉल आगे जारी नहीं रखेंगे।",
        answer_type="none",
        default_next="do_not_call",
    ),
}


class Questionnaire:
    """Apply deterministic transitions to validated LLM answer analysis."""

    def __init__(self, questions: Optional[dict[str, Question]] = None) -> None:
        self.questions = questions or QUESTIONS

    def get(self, question_id: str) -> Question:
        try:
            return self.questions[question_id]
        except KeyError as error:
            raise ValueError(f"Unknown question id: {question_id}") from error

    def transition(
        self,
        question_id: str,
        analysis: AnswerAnalysis,
    ) -> Transition:
        question = self.get(question_id)

        if analysis.next_action == "transfer":
            return Transition(None, "transferred", "A human representative is required.")
        if not analysis.is_valid or analysis.needs_clarification:
            return Transition(question_id, "clarify", "The answer needs clarification.")
        if analysis.next_action == "complete":
            return Transition(None, "complete", "The questionnaire is complete.")

        normalized = (analysis.normalized_answer or "").strip().lower()
        next_question_id = question.route_by_answer.get(normalized)
        if next_question_id is None:
            next_question_id = question.default_next

        if next_question_id == "complete":
            return Transition(None, "complete", "The questionnaire is complete.")
        if next_question_id is None:
            return Transition(None, "complete", "The questionnaire is complete.")

        self.get(next_question_id)
        return Transition(next_question_id, "active", "The next question is selected by the questionnaire rules.")
