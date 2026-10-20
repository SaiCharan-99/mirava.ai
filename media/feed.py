"""Feed ranking (phase 3): what a person's feed shows is scored from what THEY engage with, how much they need a phone,
how paid reach is targeted, and what friends sent them — not randomly shuffled.

Rules only; deterministic given the seeded noise passed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.schemas.product import StimulusRecord

PHONE_INTERESTS = {"phones", "tech", "gadgets", "photography", "gaming", "smartphones"}
DEFAULT_AFFINITY = 0.1
GAIN = {"full": 0.12, "partial": 0.04, "scroll": -0.03}      # what each way of treating an item teaches the feed
DAILY_DECAY = 0.97
SHARE_LIFE = 48 * 60                                          # a friend's share stays in the feed pool this long


@dataclass
class Candidate:
    """One item that could appear in a feed."""

    pid: str
    cid: str
    channel: str                 # reel | review
    stim: StimulusRecord
    interest: float
    source: str                  # paid | review | share | baseline
    topic: str = "phones"
    closeness: float = 0.0       # of the friend who shared it


class FeedAffinity:
    """Per person, per topic: how much the feed has learned they like it (0..1)."""

    def __init__(self) -> None:
        self.v: dict[int, dict[str, float]] = {}

    def get(self, aid: int, topic: str, interests: list[str]) -> float:
        """Learned affinity, or a start value from the person's interests."""
        got = self.v.get(aid, {}).get(topic)
        if got is not None:
            return got
        if topic == "phones":
            return 0.4 if PHONE_INTERESTS & {i.lower() for i in interests} else DEFAULT_AFFINITY
        return 0.3 if topic in {i.lower() for i in interests} else DEFAULT_AFFINITY

    def learn(self, aid: int, topic: str, outcome: str, interests: list[str]) -> None:
        """Watching more of something makes the feed show more of it."""
        cur = self.get(aid, topic, interests)
        key = "scroll" if outcome == "scroll" else ("full" if outcome == "full" else "partial")
        self.v.setdefault(aid, {})[topic] = max(0.0, min(1.0, cur + GAIN[key]))

    def decay(self) -> None:
        """Daily drift back toward the default."""
        for per in self.v.values():
            for k in per:
                per[k] = DEFAULT_AFFINITY + (per[k] - DEFAULT_AFFINITY) * DAILY_DECAY

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        return {str(a): {k: round(v, 3) for k, v in per.items()} for a, per in self.v.items()}

    def load(self, d: dict[str, Any]) -> None:
        """Restore."""
        self.v = {int(a): {k: float(v) for k, v in per.items()} for a, per in (d or {}).items()}


def score(c: Candidate, *, affinity: float, need: float, in_audience: bool, curious: bool, n_seen: int,
          noise: float = 0.0) -> float:
    """Higher = nearer the top of this person's feed."""
    s = affinity
    if c.topic == "phones":
        s += 0.6 * need + (0.2 if curious else 0.0)
    if c.source == "paid":
        s += 0.8 if in_audience else 0.1
    elif c.source == "share":
        s += 0.25 + 0.5 * c.closeness
    elif c.source == "review":
        s += 0.3
    return s - 0.1 * min(n_seen, 5) + noise


def rank(cands: list[Candidate], scores: list[float], n: int) -> list[Candidate]:
    """Top `n` by score (ties broken by product/creative id so the order is stable)."""
    order = sorted(range(len(cands)), key=lambda i: (-scores[i], cands[i].pid, cands[i].cid))
    return [cands[i] for i in order[:n]]
