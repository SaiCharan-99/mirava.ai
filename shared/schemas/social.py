"""Conversation schemas; SharePlan is the ONLY per-agent input to a shared dialogue prompt (INTERFACES §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SharePlan(BaseModel):
    """What one agent decided to say (private prep output)."""

    session_id: str
    agent_id: int
    opening: str
    points_to_share: list[str]
    questions_to_ask: list[str]
    tone: str
    withheld_count: int


class Message(BaseModel):
    """One spoken message."""

    session_id: str
    seq: int
    speaker: int
    listener: int
    text: str
    t: int


class Conversation(BaseModel):
    """Conversation summary record."""

    session_id: str
    participants: list[int]
    place_id: str | None
    kind: Literal["social", "stranger", "store", "interview"]
    t_start: int
    t_end: int
    topics: list[str]
    product_mentions: list[str]
    n_messages: int
    rendered: bool
    model: str | None


class Inquiry(BaseModel):
    """A store inquiry outcome."""

    session_id: str
    agent_id: int
    store_id: str
    product_id: str | None
    questions: list[str]
    topics: list[str]
    answered: list[bool]
    satisfaction: float
    outcome: Literal["left", "think_about_it", "buy", "referred_online"]
