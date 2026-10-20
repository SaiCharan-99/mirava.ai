"""Do I stop for this person on the street? (phase 2b) Rules only — no model call.

Walking to work you give a nod; strolling with time to spare you stop and talk. The more you like them, the more is
on your mind to tell them, the lonelier you are and the longer since you last met, the more likely you stop; being
in a hurry cancels most of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Stop = Literal["ignore", "nod", "quick", "long"]
HURRY_ACTS = {"work", "school", "college", "store_shift"}
MODE_RECOGNISE = {"walk": 1.0, "auto": 0.15, "bus": 0.15, "two_wheeler": 0.2, "car": 0.05}
QUICK_MIN, LONG_MIN = (2, 5), (10, 20)


def urgency(block_act: str | None, activity: str, mode: str) -> float:
    """0 (all the time in the world) … 1 (late for something). Heading to work or school means a hurry."""
    if mode in ("car", "two_wheeler", "auto", "bus"):
        return 0.9
    if block_act in HURRY_ACTS:
        return 0.85
    if block_act == "roam" or activity == "roam":
        return 0.55
    return 0.2


@dataclass
class StopCtx:
    """Everything the stop decision may use (all rule features)."""

    closeness: float
    hurry: float               # the larger of the two people's urgency
    agenda: float              # strongest thing either wants to tell the other (0..1)
    social_need: float         # 0 (just had company) … 1 (lonely): from the two people's social need
    mood: float                # average mood 0..1
    days_since_met: float
    jitter: float = 0.0        # seeded, ±0.08


def stop_score(c: StopCtx) -> float:
    """Raw willingness to stop (higher = more willing)."""
    return (0.40 * c.closeness + 0.25 * c.agenda + 0.15 * c.social_need + 0.10 * c.mood
            + 0.10 * min(1.0, c.days_since_met / 7.0) - 0.70 * c.hurry + c.jitter)


def decide_stop(c: StopCtx) -> Stop:
    """ignore | nod | quick (2–5 min) | long (10–20 min)."""
    s = stop_score(c)
    if c.hurry >= 0.8:
        return "nod" if (s > -0.2 and c.closeness >= 0.35) else "ignore"
    if s > 0.55 and c.hurry < 0.4:
        return "long"
    if s > 0.32:
        return "quick"
    if s > 0.10:
        return "nod"
    return "ignore"
