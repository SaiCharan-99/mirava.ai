"""Money profile, phone possession, media diet and life-event hazards (P-04, P-05, P-06)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from engine.rng import choice, stream
from population.config import band_key, load, market
from shared.schemas.agent import MediaDiet, MoneyProfile, Phone

MIN_PER_YEAR = 1440 * 365
AGE_GROUPS = ["5-17", "18-34", "35-59", "60-88"]


def money_profile(p: dict[str, Any], seed: int) -> MoneyProfile:
    """Monthly income (weekly pay for gig work), fixed costs, savings, credit and EMI eligibility."""
    rng = stream(seed, "money", p["i"])
    lo, hi = market()["income_ranges"][p["income_band"]]
    income = int(round(rng.uniform(lo, hi) / 500) * 500)
    if p["occupation"] in ("school_student",):
        income = int(round(rng.uniform(300, 2500) / 100) * 100)          # pocket money
    weekly = market()["occupations"][p["occupation"]].get("pay") == "weekly"
    fixed = int(round(income * rng.uniform(0.35, 0.7) / 100) * 100)
    savings = int(round(income * rng.gamma(2.0, 1.4 if p["age"] > 30 else 0.7) / 500) * 500)
    has_card = p["income_band"] in ("50k-1L", "1-2L", ">2L") and 21 <= p["age"] <= 70 and rng.random() < 0.8
    limit = int(round(income * rng.uniform(1.5, 3.0) / 5000) * 5000) if has_card else 0
    emi = 21 <= p["age"] <= 62 and income >= 25000 and p["occupation"] not in ("college_student", "job_seeker")
    return MoneyProfile(monthly_income_inr=income, pay_cycle="weekly" if weekly else "monthly",
                        payday=int(rng.integers(0, 7)) if weekly else (1 if rng.random() < 0.7 else 7),
                        fixed_costs_inr=fixed, savings_inr=savings, credit_card_limit_inr=limit, emi_eligible=emi)


def phone(p: dict[str, Any], seed: int) -> Phone:
    """A phone: brand by simulated share within the price band, tier, purchase time, condition and battery."""
    cfg = load("phones_market")
    rng = stream(seed, "phone", p["i"])
    band = p["income_band"]
    if p["age"] < 13:
        band = "<25k"
    tier = choice(rng, cfg["price_band_by_income"][band])
    brand = choice(rng, cfg["brand_share_by_band"][tier])
    a = cfg["age_years"]
    age_y = float(np.clip(rng.lognormal(a["mu"], a["sigma"]), a["min"], a["max"]))
    bought_t = -int(age_y * MIN_PER_YEAR)
    batt = float(np.clip(1.0 - 0.085 * age_y + rng.normal(0, 0.05), 0.35, 1.0))
    r = rng.random()
    if age_y > 3.5 and r < 0.35:
        cond = "battery_weak" if batt < 0.72 else "slow"
    elif r < 0.08 + 0.03 * age_y:
        cond = "cracked"
    elif batt < 0.62:
        cond = "battery_weak"
    else:
        cond = "ok"
    sat = float(np.clip(0.85 - 0.07 * age_y - (0.15 if cond != "ok" else 0) + rng.normal(0, 0.08), 0.05, 1.0))
    price_lo, price_hi = cfg["tier_price_inr"][tier]
    price = int(round(rng.uniform(price_lo, price_hi) / 500) * 500)
    label = f"{brand} {tier} (simulated)"
    hist = [{"t": bought_t, "event": "bought", "price_inr": price, "where": "simulated"}]
    if cond != "ok":
        hist.append({"t": bought_t + int(age_y * 0.7 * MIN_PER_YEAR), "event": cond})
    return Phone(brand=brand, tier=tier, model_label=label, bought_t=bought_t, condition=cond,  # type: ignore[arg-type]
                 battery_health=round(batt, 2), satisfaction=round(sat, 2), history=hist)


def phone_age_years(ph: dict[str, Any], t: int) -> float:
    """Phone age at sim time `t` in years."""
    return (t - int(ph["bought_t"])) / MIN_PER_YEAR


def media_diet(p: dict[str, Any], reviewers: list[dict[str, Any]], seed: int) -> MediaDiet:
    """Feed sessions, community/newspaper/news-app habits and reviewer follows."""
    cfg = load("media")
    rng = stream(seed, "media", p["i"])
    g = band_key(p["age"], AGE_GROUPS)
    lo, hi = cfg["sessions_per_day"][g]
    n = int(rng.integers(lo, hi + 1))
    sessions = []
    for k in range(n):
        w = cfg["windows"][k % len(cfg["windows"])]
        start = int(rng.integers(w[0], w[1]))
        mins = int(rng.integers(*cfg["session_minutes"]))
        sessions.append((start, mins, choice(rng, cfg["app_weights_by_age"][g])))
    sessions.sort()
    follows = []
    for r in reviewers:
        if r["i"] == p["i"]:
            continue
        overlap = bool(set(p["interests"]) & set(r["interests"]))
        pr = cfg["follow_prob_interest_match"] if overlap else cfg["follow_prob_base"]
        if p["age"] >= 13 and rng.random() < pr:
            follows.append(r["i"])
    return MediaDiet(feed_sessions=sessions, community=bool(rng.random() < cfg["community_prob"][g]),
                     newspaper=bool(rng.random() < cfg["newspaper_prob"][g]),
                     news_app=bool(rng.random() < cfg["news_app_prob"][g]), follows=follows)


def daily_hazards(ph: dict[str, Any], lifestyle: str, t: int) -> dict[str, float]:
    """Per-day probability of lost / broken / slow for one phone (rises with age)."""
    cfg = load("phones_market")
    age = max(0.0, phone_age_years(ph, t))
    mult = cfg["lifestyle_hazard_multiplier"].get(lifestyle, 1.0)
    return {k: v["base"] * (1 + age * v["age_slope"]) * mult for k, v in cfg["hazards"].items()}


def affordability(money: dict[str, Any], price_inr: int) -> dict[str, Any]:
    """Can this agent pay `price_inr` by cash (savings), card or EMI? (P-05)."""
    disposable = max(0, money["monthly_income_inr"] - money["fixed_costs_inr"])
    emi_12 = math.ceil(price_inr / 12)
    return {"cash": money["savings_inr"] >= price_inr, "card": money["credit_card_limit_inr"] >= price_inr,
            "emi": bool(money["emi_eligible"]) and emi_12 <= 0.4 * disposable,
            "share_of_income": round(price_inr / max(1, money["monthly_income_inr"]), 2)}
