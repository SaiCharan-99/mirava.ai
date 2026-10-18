"""Phone need 0..1 (S-01): age, condition, battery, lost/broken, satisfaction, job dependence; life events spike it."""

from __future__ import annotations

from typing import Any

from population.config import load
from population.possessions import phone_age_years

HIGH_DEP = ("delivery", "driver", "sales", "agent", "gig", "business", "shop", "owner", "freelanc", "consultant",
            "broker", "rider", "manager")
LOW_DEP = ("student", "retired", "homemaker", "job seeker", "looking for work")


def cfg() -> dict[str, Any]:
    """`config/consideration.yaml`."""
    return load("consideration")


def job_dependence(occupation: str) -> str:
    """high | medium | low reliance on the phone for work (keyword rules, assumption)."""
    o = occupation.lower()
    if any(k in o for k in LOW_DEP):
        return "low"
    if any(k in o for k in HIGH_DEP):
        return "high"
    return "medium"


def phone_need(phone: dict[str, Any], t: int, occupation: str, last_life_event_t: int | None = None) -> float:
    """Need for a new phone at sim time t, in [0, 1]."""
    c = cfg()["need"]
    if phone.get("condition") == "lost":
        return 1.0
    age = phone_age_years(phone, t) if "bought_t" in phone else 0.0
    span = max(0.1, c["age_full_years"] - c["age_start_years"])
    v = c["age_weight"] * min(1.0, max(0.0, (age - c["age_start_years"]) / span))
    v += float(c["condition"].get(phone.get("condition", "ok"), 0.0))
    v += c["battery_weight"] * (1.0 - float(phone.get("battery_health", 1.0)))
    v += c["satisfaction_weight"] * (1.0 - float(phone.get("satisfaction", 0.7)))
    v += float(c["job_dependence"][job_dependence(occupation)])
    if last_life_event_t is not None and 0 <= t - last_life_event_t <= c["life_event_days"] * 1440:
        v += c["life_event_spike"]
    return round(min(1.0, max(0.0, v)), 3)


def affordability(price_inr: int, money: dict[str, Any]) -> tuple[float, str | None]:
    """(0..1 score, best method) for a price given a money profile; method None if unaffordable."""
    p = cfg()["purchase"]
    savings = int(money.get("savings_inr", 0))
    limit = int(money.get("credit_card_limit_inr", 0))
    if price_inr <= savings * p["cash_share_of_savings"]:
        return 1.0, "cash"
    if price_inr <= limit * p["card_share_of_limit"]:
        return 0.8, "card"
    if money.get("emi_eligible") and price_inr >= p["emi_min_price_inr"] and \
            price_inr / 6 <= 0.25 * int(money.get("monthly_income_inr", 0)):
        return 0.65, "emi"
    income = max(1, int(money.get("monthly_income_inr", 1)))
    return round(max(0.0, min(0.4, 0.4 * income * 2 / max(1, price_inr))), 3), None
