"""Likely-buyer segments (I-05): L = need × interest × affordability × stage_weight, aggregated — never per person."""

from __future__ import annotations

from typing import Any

from commerce.consideration import stage_weight
from commerce.need import cfg

INCOME_MID = {"<25k": 18000, "25-50k": 37000, "50k-1L": 75000, "1-2L": 150000, ">2L": 260000}
GROUPS = {"age_band", "income_band", "lifestyle", "phone_tier", "occupation", "gender"}


def age_band(age: int) -> str:
    """Age band label."""
    for lo, hi in ((15, 17), (18, 24), (25, 34), (35, 44), (45, 59)):
        if lo <= age <= hi:
            return f"{lo}–{hi}"
    return "60+" if age >= 60 else "<15"


def need_proxy(age_years: float, condition: str) -> float:
    """Phone need from the snapshot fields available in BigQuery (age + condition)."""
    c = cfg()["need"]
    span = max(0.1, c["age_full_years"] - c["age_start_years"])
    v = c["age_weight"] * min(1.0, max(0.0, (age_years - c["age_start_years"]) / span))
    v += float(c["condition"].get(condition or "ok", 0.0)) + 0.1
    return round(min(1.0, v), 3)


def afford_proxy(income_band: str, price_inr: int) -> float:
    """Affordability 0..1 from the income band (≈ 6 months of 25% of income covers the price → 1)."""
    inc = INCOME_MID.get(income_band, 37000)
    return round(min(1.0, (inc * 0.25 * 6) / max(1, price_inr)), 3)


def segments(runner: Any, product_id: str, group_by: list[str], price_inr: int | None = None) -> list[dict[str, Any]]:
    """Aggregated rows: group keys, n agents, aware, avg L, share with L ≥ 0.2, top stage."""
    gb = [g for g in group_by if g in GROUPS][:3] or ["age_band", "income_band"]
    rows, _ = runner.run(
        "SELECT a.agent_id, a.age, a.income_band, a.lifestyle, a.phone_tier, a.occupation, a.gender, "
        "a.phone_age_years, a.phone_condition, b.attitude, b.stage FROM agents_latest a "
        "LEFT JOIN beliefs_latest b ON b.agent_id = a.agent_id AND b.product_id = @p "
        "WHERE a.special_role = 'none' OR a.special_role IS NULL", {"p": product_id})
    price = int(price_inr or 20000)
    agg: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        r["age_band"] = age_band(int(r["age"] or 0))
        key = tuple(str(r.get(g)) for g in gb)
        st = r.get("stage") or "unaware"
        need = need_proxy(float(r.get("phone_age_years") or 0), str(r.get("phone_condition") or "ok"))
        interest = 0.0 if st == "unaware" else (float(r.get("attitude") or 0) + 1) / 2
        score = need * interest * afford_proxy(str(r.get("income_band")), price) * stage_weight(st)
        a = agg.setdefault(key, {**{g: k for g, k in zip(gb, key, strict=True)}, "n": 0, "aware": 0,
                                 "sum_l": 0.0, "likely": 0, "stages": {}})
        a["n"] += 1
        a["aware"] += st != "unaware"
        a["sum_l"] += score
        a["likely"] += score >= 0.2
        a["stages"][st] = a["stages"].get(st, 0) + 1
    out = []
    for a in agg.values():
        n = a["n"]
        out.append({**{g: a[g] for g in gb}, "n": n, "aware": a["aware"], "avg_score": round(a["sum_l"] / n, 3),
                    "likely_share": round(a["likely"] / n, 3),
                    "top_stage": max(sorted(a["stages"]), key=lambda s: a["stages"][s])})
    return sorted(out, key=lambda r: (-r["avg_score"], -r["n"]))
