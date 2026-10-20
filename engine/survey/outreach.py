"""How a survey reaches people, who decides to come, and when they leave (phase 5). Pure rules; deterministic.

Nobody is telepathically invited: a panel message is read at someone's next phone session, a forum post at their next
community visit, word of mouth when a friend brings it up, a flyer when they walk into a store. Each person then decides
from interest, what they get out of it, how far it is, what else is in their plan and who told them — and whoever says
yes works out when to leave so they arrive on time (or not, if they are the careless type).
"""

from __future__ import annotations

import math
from typing import Any

from engine.rng import stream
from insights.likely_buyers import age_band
from population.config import load
from shared.schemas.survey import Incentive

DAY = 1440
TRUST = {"panel": 0.5, "community": 0.4, "word_of_mouth": 0.7, "store_flyer": 0.3}
MIN_LEAD = 5                    # an explicit start can be this many minutes away
CLOSE_BEFORE = 2                # sign-ups close this long before the start
GLANCE_P = 0.3                  # share of awake people who glance at a phone notification within minutes
LATE_OK = 8                     # arriving up to this many minutes after the start is still fine (the room waits)
REACH_EXTRA = {"community": 0.25, "word_of_mouth": 0.15, "store_flyer": 0.08}   # rough share of the pool each adds (estimate)
TECH = {"tech", "gadgets", "photography", "gaming", "startups"}
SHOP = {"shopping", "fashion", "food", "cooking", "coffee"}


def next_session_start(feed_sessions: list[Any], t: int, app: str | None = None, min_gap: int = MIN_LEAD) -> int:
    """Absolute minute of the person's next phone session (of `app` if given) at least `min_gap` minutes from `t`;
    tomorrow 08:00 if they have none."""
    day0 = (t // DAY) * DAY
    starts = sorted(int(s[0]) for s in feed_sessions if app is None or str(s[2]) == app)
    for d in (0, 1):
        for m in starts:
            if day0 + d * DAY + m >= t + min_gap:
                return day0 + d * DAY + m
    return day0 + DAY + 8 * 60


def sample_panel(pool: list[int], n: int, ages: dict[int, int], seed: int, survey_id: str, exclude: set[int]) -> list[int]:
    """`n` people from the pool, stratified by age band (each band gets its share of the pool)."""
    avail = [a for a in pool if a not in exclude]
    if n >= len(avail):
        return sorted(avail)
    bands: dict[str, list[int]] = {}
    for a in avail:
        bands.setdefault(age_band(ages[a]), []).append(a)
    rng = stream(seed, "panel", survey_id, len(exclude))
    out: list[int] = []
    for b in sorted(bands):
        ids = bands[b]
        k = max(1, round(n * len(ids) / len(avail)))
        out += [ids[int(i)] for i in rng.permutation(len(ids))[:k]]
    return sorted(out[:n])


def incentive_value(inc: Incentive, monthly_income: int, interests: list[str], extraversion: float,
                    interested_in_product: bool = False) -> float:
    """How much the cash and goodies matter to THIS person, 0..1 (₹500 means more on ₹20k a month than on ₹2L)."""
    ref = max(300.0, monthly_income / 30 * 1.5)
    have = {i.lower() for i in interests}
    v = min(1.0, inc.cash_inr / ref) * 0.6
    for g in inc.goodies:
        base = min(1.0, max(g.value_inr, 150) / ref) * 0.4
        fit = {"accessory": 1.0 if TECH & have else 0.5, "food": 0.8, "voucher": 1.0 if SHOP & have else 0.6,
               "product_trial": 0.9 if interested_in_product or TECH & have else 0.5,
               "merch": 0.4 + 0.6 * extraversion}.get(g.kind, 0.5)
        v += base * fit
    return min(1.0, v)


def attend_propensity(*, interest: float, free: float, extraversion: float, openness: float, incentive: float,
                      channel: str, closeness: float, dist_m: float, fatigue: bool, job_high: bool) -> float:
    """Chance a person who has just heard about the session says yes."""
    trust = TRUST.get(channel, 0.4) * (0.5 + 0.5 * closeness if channel == "word_of_mouth" else 1.0)
    p = (0.12 + 0.28 * interest + 0.15 * free + 0.08 * extraversion + 0.06 * openness + 0.30 * incentive
         + 0.15 * trust - 0.12 * min(1.0, dist_m / 2500) - (0.25 if fatigue else 0.0) - (0.08 if job_high else 0.0))
    return max(0.02, min(0.95, p))


def eta_minutes(dist_m: float, commute_mode: str) -> int:
    """Minutes to get there (road distance ≈ 1.3 × straight line), by how this person travels."""
    c = load("world")
    speeds = c["speeds_m_per_min"]
    road = dist_m * 1.3
    mode = "walk" if road <= float(c["walk_max_m"]) else commute_mode
    if mode == "metro":
        mode = "auto" if road > 1800 else "walk"
    return max(1, math.ceil(road / float(speeds.get(mode, speeds["walk"]))))


def leave_buffer(conscientiousness: float, rng: Any) -> int:
    """Minutes of slack before the start: careful people leave early (+5…10), careless ones cut it fine or run late."""
    if conscientiousness >= 0.6:
        return 5 + int(rng.integers(0, 6))
    if conscientiousness >= 0.35:
        return int(rng.integers(0, 6))
    return -int(rng.integers(0, 11))


def no_show_probability(base: float, conscientiousness: float, recent_trouble: bool, dist_m: float) -> float:
    """Chance of simply not turning up after saying yes."""
    return min(0.6, base + 0.10 * (1 - conscientiousness) + (0.15 if recent_trouble else 0.0) + 0.04 * min(1.0, dist_m / 3000))


def reach_share(channels: list[str], max_participants: int, eligible: int) -> float:
    """Rough share of the eligible pool that ever hears about it (for the estimate)."""
    miss = 1.0
    if "panel" in channels:
        miss *= 1 - min(1.0, 3 * max_participants / max(1, eligible))
    for c in ("community", "word_of_mouth", "store_flyer"):
        if c in channels:
            miss *= 1 - REACH_EXTRA[c]
    return 1 - miss
