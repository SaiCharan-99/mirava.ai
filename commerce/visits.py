"""Who goes to a phone store today, and why (phase 4). Most people never think about it; a few do, at random times.

Daily 07:00 roll per person: a small base chance, rising with how much they need a phone, open considerations, payday,
weekend, a store on their route, a sale period, and above all a deadline (a gift errand).
"""

from __future__ import annotations

from typing import Any


def visit_probability(*, need: float, curious: bool, payday: bool, weekend: bool, near_store: bool, festival: bool,
                      errand_days_left: float | None, cfg: dict[str, Any]) -> float:
    """Chance (0..cap) this person goes to a store today."""
    v = cfg["visits"]
    p = float(v["base"]) + float(v["need_sq"]) * need * need
    p += float(v["curious"]) * curious + float(v["payday"]) * payday + float(v["weekend"]) * weekend
    p += float(v["near_store"]) * near_store + float(v["festival"]) * festival
    if errand_days_left is not None:
        lo, hi = v["errand_urgency"]
        urgency = hi if errand_days_left <= 1 else lo + (hi - lo) * max(0.0, 1 - (errand_days_left - 1) / 9)
        p = max(p, urgency)
    return min(float(v["cap"]), p)


def visit_kind(has_errand: bool) -> str:
    """errand when there is one (a gift, a replacement); otherwise plain browsing."""
    return "errand" if has_errand else "browse"
