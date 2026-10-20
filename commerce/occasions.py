"""Occasions that send someone to a store (phase 4): birthdays, a family member's lost or cracked phone, a new term,
sale periods. An `Errand` is a purchase for someone (maybe yourself) with a budget and what they want.

Pure rules over the agents' own households, phones and money. Deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from commerce.need import affordability
from engine.rng import stream
from population.config import load

DAY = 1440


def cfg() -> dict[str, Any]:
    """`config/occasions.yaml`."""
    return load("occasions")


@dataclass
class Errand:
    """Buy a phone for `beneficiary` (may equal `buyer`)."""

    errand_id: str
    buyer: int
    beneficiary: int
    reason: str                         # gift | replacement | new_start
    budget_inr: int
    due_t: int
    created_t: int
    requirements: list[str] = field(default_factory=list)   # attribute names the beneficiary wants
    briefed: bool = False               # the beneficiary actually said what they want
    status: str = "open"                # open | planned | done | expired
    tries: int = 0


class Errands:
    """All errands (checkpointed)."""

    def __init__(self) -> None:
        self.items: dict[str, Errand] = {}

    def add(self, e: Errand) -> bool:
        """Add unless the same occasion already exists."""
        if e.errand_id in self.items:
            return False
        self.items[e.errand_id] = e
        return True

    def open_for(self, buyer: int) -> list[Errand]:
        """The buyer's errands still to do, soonest due first."""
        return sorted((e for e in self.items.values() if e.buyer == buyer and e.status in ("open", "planned")),
                      key=lambda e: (e.due_t, e.errand_id))

    def note_requirements(self, buyer: int, beneficiary: int, attrs: list[str]) -> Errand | None:
        """The beneficiary said aloud what they want: attach it to the buyer's open errand for them."""
        for e in self.open_for(buyer):
            if e.beneficiary == beneficiary and attrs:
                e.requirements = list(dict.fromkeys([*attrs, *(r for r in e.requirements if e.briefed)]))[:4]
                e.briefed = True
                return e
        return None

    def expire(self, t: int, grace_days: int = 3) -> int:
        """Drop errands long past their due date."""
        n = 0
        for e in self.items.values():
            if e.status in ("open", "planned") and t > e.due_t + grace_days * DAY:
                e.status = "expired"
                n += 1
        return n

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        return {k: asdict(v) for k, v in self.items.items()}

    def load(self, d: dict[str, Any]) -> None:
        """Restore."""
        self.items = {k: Errand(**v) for k, v in (d or {}).items()}


def birthday_doy(seed: int, aid: int) -> int:
    """Day of the (sim) year of this person's birthday, 0-based; fixed for ever."""
    return int(stream(seed, "bday", aid).integers(0, int(cfg()["year_days"])))


def days_until_birthday(seed: int, aid: int, day: int) -> int:
    """Whole days from sim `day` (1-based) to the next birthday (0 = today)."""
    n = int(cfg()["year_days"])
    return (birthday_doy(seed, aid) - (day - 1)) % n


def festival_active(day: int) -> bool:
    """Is a sale period on?"""
    f = cfg()["festival"]
    return ((day - 1 - int(f["offset"])) % int(f["every_days"])) < int(f["length_days"])


def budget_for(money: dict[str, Any], closeness: float) -> int:
    """What the buyer is willing to spend on the person (limited by what they can actually pay)."""
    b = cfg()["budget"]
    want = float(money.get("monthly_income_inr", 0)) * float(b["income_months"]) * (0.7 + 0.6 * closeness)
    can = max(float(money.get("credit_card_limit_inr", 0)) * 0.6, float(money.get("savings_inr", 0)) * 0.5,
              float(money.get("monthly_income_inr", 0)) * 2)
    return int(round(max(float(b["floor_inr"]), min(want, can, float(b["cap_inr"]))) / 1000) * 1000)


def default_requirements(age: int) -> list[str]:
    """Reasonable guesses when nobody has said what they want."""
    d = cfg()["default_requirements"]
    return list(d["child"] if age < 18 else d["young"] if age < 26 else d["senior"] if age >= 60 else d["adult"])


def plan_errands(*, day: int, t: int, seed: int, members: dict[str, list[tuple[int, str]]],
                 ages: Callable[[int], int], closeness: Callable[[int, int], float],
                 money: Callable[[int], dict[str, Any]], phone_condition: Callable[[int], str],
                 life_recent: Callable[[int], bool], need: Callable[[int], float], is_student: Callable[[int], bool],
                 existing: Errands) -> list[Errand]:
    """New errands for today from birthdays, broken phones and a new term (one per occasion, never repeated)."""
    c = cfg()
    out: list[Errand] = []
    doy = (day - 1) % int(c["year_days"])
    lo, hi = c["gift"]["window_days"]
    for _hid, mem in sorted(members.items()):
        ids = [m for m, _ in mem]
        adults = [m for m in ids if ages(m) >= 21]
        if not adults:
            continue
        for b in ids:
            reason, due_in, eid = "", 0, ""
            buyers: list[int] = []
            d = days_until_birthday(seed, b, day)
            if lo <= d <= hi and len(ids) > 1:
                buyers = [x for x in adults if x != b]
                year = (day - 1) // int(c["year_days"])
                if buyers:
                    reason, due_in = "gift", d
                    eid = f"gift-{b}-{year}"
            if not reason and phone_condition(b) in ("lost", "cracked") and life_recent(b) \
                    and (ages(b) < c["replacement"]["young_below"] or ages(b) > c["replacement"]["old_above"]):
                buyers = [x for x in adults if x != b]
                if buyers:
                    reason, due_in, eid = "replacement", 2, f"repl-{b}-{day // 7}"
            if not reason and is_student(b) and any(a <= doy <= z for a, z in c["new_start"]["windows"]) \
                    and c["new_start"]["age_range"][0] <= ages(b) <= c["new_start"]["age_range"][1] and len(ids) > 1:
                buyers = [x for x in adults if x != b]
                if buyers:
                    reason, due_in, eid = "new_start", 6, f"term-{b}-{(day - 1) // int(c['year_days'])}-{doy // 100}"
            if not reason or eid in existing.items:
                continue
            rng = stream(seed, "errand", eid)
            buyer = max(buyers, key=lambda x: (closeness(x, b) + 0.3 * float(rng.random()), -x))
            cl = closeness(buyer, b)
            p = 1.0
            if reason == "gift":
                g = c["gift"]
                wants = g["age_range"][0] <= ages(b) <= g["age_range"][1] or need(b) >= float(g["need_threshold"])
                p = float(g["p_base"]) * (0.5 + cl) * (float(g["p_if_wants_phone"]) if wants else float(g["p_otherwise"]))
            elif reason == "new_start":
                p = float(c["new_start"]["p"])
            if float(rng.random()) >= p:
                existing.add(Errand(eid, buyer, b, "skipped", 0, t, t, status="expired"))   # decided not to: remembered
                continue
            out.append(Errand(eid, buyer, b, reason, budget_for(money(buyer), cl), t + due_in * DAY, t,
                              default_requirements(ages(b))))
    return out


def requirement_phrase(attrs: list[str]) -> str:
    """Plain words for a list of wanted attributes."""
    lab = cfg()["requirement_labels"]
    return ", ".join(lab.get(a, a) for a in attrs) or "something reliable"


def best_for(requirements: list[str], budget: int, options: list[dict[str, Any]], money: dict[str, Any]
             ) -> dict[str, Any] | None:
    """Pick the option that matches what is wanted and fits the budget (and what the buyer can pay for).

    `options`: {id, label, price_inr, specs{attr:value}}. Score = wanted attributes' strength, a little value for money,
    a penalty for stretching the budget. None if nothing is affordable and within reach."""
    best, best_s = None, -1.0
    for o in options:
        price = int(o["price_inr"])
        aff, method = affordability(price, money)
        if method is None or price > budget * 1.15:
            continue
        specs = o.get("specs", {})
        want = [specs.get(a, 0.5) for a in requirements if a in specs]
        s = (sum(want) / len(want) if want else 0.5) + 0.15 * specs.get("price_value", 0.5) \
            - 0.3 * max(0.0, price / max(budget, 1) - 0.85)
        if s > best_s:
            best, best_s = {**o, "method": method}, s
    return best
