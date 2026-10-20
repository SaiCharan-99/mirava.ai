"""Planned meetups (phase 2d): friends who agree to meet get a café or park block in both plans.

Pure rules over the people's own plans, personalities and favourite places. Deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from engine.planner import OFFMAP, free_slot
from engine.rng import stream

FREE_ACTS = ("home", "shop", "cafe", "eat", "park", "gym", "roam")


@dataclass
class Meetup:
    """Two people, one place, one hour."""

    a: int
    b: int
    start: int          # minute of day
    minutes: int
    act: str            # cafe | park
    place_id: str


def is_free(plan: list[dict[str, Any]], s: int, e: int) -> bool:
    """Every block that overlaps [s, e) is free time on the map."""
    return all(b["act"] in FREE_ACTS and b.get("place") != OFFMAP for b in plan if b["s"] < e and b["e"] > s)


def plan_meetups(pairs: list[tuple[int, int, float]], *, day: int, weekend: bool, seed: int, cfg: dict[str, Any],
                 extraversion: Callable[[int], float], satisfaction: Callable[[int], float],
                 plan_of: Callable[[int], list[dict[str, Any]]],
                 haunts: Callable[[int, str], list[str]]) -> list[Meetup]:
    """Which friend pairs meet today, when and where (at most `max_per_day`)."""
    lo, hi = cfg["weekend_window" if weekend else "weekday_window"]
    base = float(cfg["base_p_weekend" if weekend else "base_p_weekday"])
    minutes = int(cfg["minutes"])
    order = stream(seed, "meetup_order", day).permutation(len(pairs))
    out: list[Meetup] = []
    busy: set[int] = set()
    for i in order.tolist():
        a, b, closeness = pairs[int(i)]
        if len(out) >= int(cfg["max_per_day"]):
            break
        if a in busy or b in busy:
            continue
        rng = stream(seed, "meetup", day, a, b)
        lonely = 1.5 - (satisfaction(a) + satisfaction(b)) / 2
        p = base * (0.5 + closeness) * (extraversion(a) + extraversion(b)) * lonely
        if float(rng.random()) >= p:
            continue
        pa, pb = plan_of(a), plan_of(b)
        sa = free_slot(pa, lo, hi, minutes)
        if sa is None:
            continue
        sb = free_slot(pb, sa, hi, minutes)
        if sb is None:
            continue
        start = sb - sb % 5
        if start + minutes > 1440 or not (is_free(pa, start, start + minutes) and is_free(pb, start, start + minutes)):
            continue
        act = "park" if (weekend and float(rng.random()) < 0.4) else "cafe"
        both = [x for x in haunts(a, act) if x in set(haunts(b, act))]
        places = both or haunts(a, act) or haunts(b, act)
        if not places:
            continue
        out.append(Meetup(a, b, start, minutes, act, places[int(rng.integers(len(places)))]))
        busy.update((a, b))
    return out
