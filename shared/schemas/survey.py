"""Survey Room schemas (phase-5 addendum B2) — additive; no existing contract changes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

QType = Literal["single", "multi", "scale", "open"]
Mode = Literal["focus_group", "survey"]
Status = Literal["draft", "recruiting", "gathering", "in_session", "balloting", "completed", "cancelled"]
Influence = Literal["persuaded", "conformed", "reinforced", "unchanged", "reacted_against"]
Why = Literal["relevance", "credibility", "emotion", "novelty", "agreement", "disagreement", "primacy", "recency"]
MAX_PARTICIPANTS = 100


class Scale(BaseModel):
    """Scale anchors."""

    min: int = 1
    max: int = 5
    low_label: str = ""
    high_label: str = ""


class Question(BaseModel):
    """One survey question."""

    question_id: str
    text: str = Field(min_length=3, max_length=300)
    type: QType
    options: list[str] | None = None
    max_select: int | None = None
    scale: Scale | None = None
    discuss: bool = True

    @model_validator(mode="after")
    def _shape(self) -> Question:
        if self.type in ("single", "multi") and not (self.options and 2 <= len(self.options) <= 8):
            raise ValueError("single/multi questions need 2–8 options")
        if self.type == "scale":
            self.scale = self.scale or Scale()
            if (self.scale.min, self.scale.max) not in ((1, 5), (1, 10)):
                raise ValueError("scale must be 1–5 or 1–10")
        if self.type == "multi":
            self.max_select = max(1, min(self.max_select or len(self.options or []), len(self.options or [])))
        return self

    def valid(self, answer: object) -> bool:
        """Is `answer` allowed for this question?"""
        if self.type == "single":
            return isinstance(answer, str) and answer in (self.options or [])
        if self.type == "multi":
            return isinstance(answer, list) and 1 <= len(answer) <= (self.max_select or 1) and \
                all(a in (self.options or []) for a in answer) and len(set(answer)) == len(answer)
        if self.type == "scale":
            s = self.scale or Scale()
            return isinstance(answer, int) and not isinstance(answer, bool) and s.min <= answer <= s.max
        return isinstance(answer, str) and 0 < len(answer.split()) <= 60


class InterestFilter(BaseModel):
    """Recruit only agents at or beyond a stage for a product."""

    product_id: str | None = None
    min_stage: str | None = None


class Survey(BaseModel):
    """A survey or focus group definition + status."""

    survey_id: str
    title: str
    mode: Mode
    product_id: str | None = None
    topic: str = ""
    questions: list[Question] = Field(min_length=1, max_length=10)
    cohort_filter: str | None = None
    interest_filter: InterestFilter | None = None
    max_participants: int = Field(ge=1, le=MAX_PARTICIPANTS)
    table_size: int = Field(8, ge=6, le=10)
    incentive_inr: int = 500
    start_at_t: int | None = None
    wave: int = 1
    panel_id: str | None = None
    parent_survey_id: str | None = None
    status: Status = "draft"
    estimate_usd: float = 0.0
    actual_usd: float = 0.0


class Participant(BaseModel):
    """One invited agent."""

    agent_id: int
    table_id: str | None = None
    seat: int | None = None
    rsvp: Literal["accepted", "declined", "no_show", "attended", "waitlist"] = "declined"
    rsvp_reason: str = ""          # PRIVATE
    arrived_t: int | None = None


class Table(BaseModel):
    """A round table with its moderator session."""

    table_id: str
    survey_id: str
    session_id: str
    seats: list[int]
    moderator_id: str


class PreStance(BaseModel):
    """PRIVATE initial answer (the 'before' measure)."""

    agent_id: int
    question_id: str
    answer: str | int | list[str]
    confidence: float = Field(ge=0, le=1)
    gut_reason: str


class SurveyMessage(BaseModel):
    """A public message at a table."""

    message_id: str
    survey_id: str
    table_id: str
    question_id: str
    seq: int
    speaker: int | Literal["moderator"]
    text: str
    addressed_to: int | None = None
    reply_to: str | None = None
    t: int = 0


class HeardItem(BaseModel):
    """PRIVATE: what one listener retained of one message."""

    message_id: str
    salience: float = Field(ge=0, le=1)
    why: list[Why]


class SurveyAnswer(BaseModel):
    """The private ballot answer."""

    agent_id: int
    question_id: str
    answer: str | int | list[str]
    confidence: float = Field(ge=0, le=1)
    reason: str
    changed_from_prestance: bool = False
    influence_type: Influence = "unchanged"
    influenced_by: list[str] = Field(default_factory=list)
    public_private_gap: bool = False
    effort: Literal["careful", "satisficed"] = "careful"


class QuestionResult(BaseModel):
    """Per-question result."""

    question_id: str
    distribution: dict[str, int]
    shift: dict[str, dict[str, int]]        # prestance → final counts
    by_segment: dict[str, dict[str, int]]
    quotes: list[dict]
    moderator_summary: str = ""


class SurveyResult(BaseModel):
    """All question results."""

    survey_id: str
    questions: list[QuestionResult]
    n_attended: int
    changed_share: float
    participation_effect: str = ""
    notes: list[str] = Field(default_factory=list)
