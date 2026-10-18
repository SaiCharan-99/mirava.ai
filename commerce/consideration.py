"""Consideration state machine per agent × product (S-02): rules in config/consideration.yaml; every move has a cause."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from commerce.need import cfg

STAGES = ("unaware", "aware", "curious", "researching", "inquiring", "deciding", "purchased", "postponed", "rejected")
TERMINAL = {"purchased", "rejected"}


@dataclass
class Pair:
    """Consideration state of one agent for one product (rule features only, no text)."""

    stage: str = "unaware"
    since_t: int = 0
    attitude: float = 0.0
    aware: bool = False
    social: float = 0.0          # friends' expressed attitude heard in chats (−1..1)
    review: float = 0.0          # review rating seen, 0..1
    fit: float = 0.0             # features ↔ interests, 0..1
    open_questions: list[str] = field(default_factory=list)
    cause: str | None = None     # latest cause event id
    inquired: int = 0
    visit_planned_day: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        return asdict(self)


def interest(p: Pair) -> float:
    """Interest 0..1 from attitude, awareness, social proof, reviews and fit (S-02, architecture §12.2)."""
    w = cfg()["interest"]
    v = (w["attitude_weight"] * (p.attitude + 1) / 2 + w["awareness_weight"] * (1.0 if p.aware else 0.0)
         + w["social_weight"] * max(0.0, p.social) + w["review_weight"] * p.review + w["fit_weight"] * p.fit)
    return round(min(1.0, max(0.0, v)), 3)


def next_stage(p: Pair, need: float, opportunity: set[str], t: int) -> tuple[str, str] | None:
    """(new stage, reason) if a rule fires, else None. Opportunities: feed, store_route, weekend, payday, online,
    friend, payday_due, life_event."""
    s = cfg()["stages"]
    i = interest(p)
    if p.stage in TERMINAL or p.stage in ("inquiring", "deciding"):
        if p.stage in ("inquiring", "deciding") and p.attitude <= s["reject_attitude"]:
            return "rejected", "strong negative belief"
        return None
    if p.stage != "unaware" and p.attitude <= s["reject_attitude"]:
        return "rejected", "strong negative belief"
    if p.stage == "unaware":
        return ("aware", "heard of it") if p.aware else None
    if p.stage == "aware":
        return ("curious", f"interest {i:.2f} above curiosity threshold") if i >= s["curious_interest"] else None
    if p.stage == "curious":
        if "friend" in opportunity and need >= s["inquire_need"] and opportunity & {"store_route", "online", "weekend"}:
            return "inquiring", "friend recommends + store opportunity"
        if (p.open_questions or i >= s["research_interest"]) and "feed" in opportunity:
            return "researching", "open questions + feed/community session"
        return None
    if p.stage == "researching":
        if (t - p.since_t) < s["research_min_days"] * 1440:
            return None
        if need >= s["inquire_need"] and i >= s["inquire_interest"] and \
                opportunity & {"store_route", "weekend", "payday", "online"}:
            return "inquiring", f"need {need:.2f} + interest {i:.2f} + opportunity"
        return None
    if p.stage == "postponed":
        if opportunity & {"payday_due", "life_event"} or t - p.since_t >= s["postpone_days"] * 1440:
            return "deciding", "payday / phone trouble / time passed"
    return None


def stage_weight(stage: str) -> float:
    """Stage weight for the likely-buyer score."""
    return float(cfg()["stage_weight"].get(stage, 0.0))
