"""Memory schemas: episodic entries and beliefs (INTERFACES §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Stage = Literal["unaware", "aware", "curious", "researching", "inquiring", "deciding", "purchased", "postponed",
                "rejected"]


class MemoryEntry(BaseModel):
    """One first-person episodic memory owned by a single agent."""

    mid: str
    agent_id: int
    t: int
    kind: Literal["seed", "ad_thought", "conversation", "inquiry", "post", "review", "purchase", "life_event",
                  "reflection", "observation"]
    text: str
    importance: int
    source: dict
    entities: list[str]
    event_refs: list[str]
    embedding: list[float] | None = None


class Belief(BaseModel):
    """An agent's belief about one subject (product, brand or category)."""

    agent_id: int
    subject: str
    awareness: Literal["unaware", "heard", "aware", "familiar"]
    attitude: float
    confidence: float
    reasons_for: list[str]
    reasons_against: list[str]
    open_questions: list[str]
    first_heard: dict | None
    sources_seen: dict[str, int]
    stage: Stage
    updated_t: int
