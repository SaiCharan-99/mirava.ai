"""The Event envelope — events are the source of truth (INTERFACES §2.1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

PRIVATE_KINDS = frozenset({"thought", "memory_write", "share_plan", "debrief", "store_thought", "salesperson_thought",
                           "review_private", "community_thought", "reflection"})


class Event(BaseModel):
    """Immutable world event."""

    event_id: str
    t: int
    day: int
    t_real: datetime
    kind: str
    agent_id: int | None
    other_id: int | None = None
    product_id: str | None = None
    site_id: str | None = None
    session_id: str | None = None
    rendered: bool = True
    private: bool = False
    payload: dict


def make_event_id(kind: str, t: int, agent_id: int | None, seq: int) -> str:
    """Deterministic, idempotent event id `{kind}:{t}:{agent_id}:{seq}`."""
    agent = "" if agent_id is None else str(agent_id)
    return f"{kind}:{t}:{agent}:{seq}"
