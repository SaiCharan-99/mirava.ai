"""Survey recruitment (addendum B3): eligibility, RSVP, stratified selection, tables, scheduling; cost estimate (B11)."""

from __future__ import annotations

import math
from typing import Any

import duckdb

from commerce.consideration import STAGES
from engine.rng import stream
from insights.likely_buyers import age_band
from population.config import load
from population.possessions import phone_age_years
from shared.models import cost_usd
from shared.schemas.survey import MAX_PARTICIPANTS, Survey

AGENT_COLS = ("agent_id", "name", "age", "gender", "occupation", "income_band", "special_role", "lifestyle",
              "phone_brand", "phone_tier", "phone_condition", "phone_age_years")


def cfg() -> dict[str, Any]:
    """`config/survey.yaml`."""
    return load("survey")


def agent_rows(profiles: list[Any], phones: list[dict[str, Any]], t: int) -> list[dict[str, Any]]:
    """agents_latest-shaped rows from live world state (same column names as the view)."""
    out = []
    for p in profiles:
        ph = phones[p.agent_id]
        out.append({"agent_id": p.agent_id, "name": p.name, "age": p.age, "gender": p.gender, "occupation": p.occupation,
                    "income_band": p.income_band, "special_role": p.special_role, "lifestyle": p.persona.lifestyle,
                    "phone_brand": ph.get("brand"), "phone_tier": ph.get("tier"), "phone_condition": ph.get("condition"),
                    "phone_age_years": round(phone_age_years(ph, t), 3) if "bought_t" in ph else 0.0})
    return out


def eligible(rows: list[dict[str, Any]], cohort_filter: str | None, stages: dict[int, dict[str, str]],
             interest: dict[str, Any] | None) -> list[int]:
    """cohort_filter (agents_latest expression, as the `cohort` tool) ∩ interest_filter; regular residents only."""
    import sqlglot
    from sqlglot import exp

    from insights.sqlguard import SQLRejected

    where = "TRUE"
    if cohort_filter and cohort_filter.strip():
        try:
            node = sqlglot.parse_one(cohort_filter, read="bigquery", into=exp.Condition)
        except sqlglot.errors.ParseError as e:
            raise SQLRejected(f"bad cohort filter: {e}") from e
        for c in node.find_all(exp.Column):
            if c.name not in AGENT_COLS:
                raise SQLRejected(f"unknown column `{c.name}`")
        if any(isinstance(n, exp.Select | exp.Subquery) for n in node.walk()):
            raise SQLRejected("subqueries are not allowed")
        where = node.sql(dialect="duckdb")
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE a (agent_id BIGINT, name VARCHAR, age BIGINT, gender VARCHAR, occupation VARCHAR, "
                "income_band VARCHAR, special_role VARCHAR, lifestyle VARCHAR, phone_brand VARCHAR, phone_tier VARCHAR, "
                "phone_condition VARCHAR, phone_age_years DOUBLE)")
    con.executemany("INSERT INTO a VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [[r[c] for c in AGENT_COLS] for r in rows])
    ids = [int(r[0]) for r in con.execute(f"SELECT agent_id FROM a WHERE special_role = 'none' AND ({where}) "
                                          "ORDER BY agent_id").fetchall()]
    if interest and interest.get("product_id"):
        pid = interest["product_id"]
        lo = STAGES.index(interest.get("min_stage") or "aware")
        ok = {s for s in STAGES[lo:] if s not in ("rejected",)}
        ids = [i for i in ids if stages.get(i, {}).get(pid) in ok]
    return ids


def rsvp_propensity(prof: Any, *, interest: float, free: float, dist_m: float, incentive: int, fatigue: bool,
                    job_dep: str) -> float:
    """Rule propensity to accept (used offline and as the model's hint)."""
    b5 = prof.persona.big5
    p = (0.18 + 0.30 * interest + 0.18 * free + 0.10 * float(b5.get("E", 0.5)) + 0.08 * float(b5.get("O", 0.5))
         + 0.12 * min(1.0, incentive / 1000) - 0.12 * min(1.0, dist_m / 2500) - (0.25 if fatigue else 0.0)
         - (0.08 if job_dep == "high" else 0.0))
    return max(0.02, min(0.95, p))


def select(accepted: list[int], pool: list[int], max_n: int, profiles: list[Any], seed: int, survey_id: str
           ) -> tuple[list[int], list[int]]:
    """Accept up to max_n in RSVP order with age-band quotas matching the eligible pool; rest → waitlist."""
    max_n = min(max_n, MAX_PARTICIPANTS)
    bands: dict[str, int] = {}
    for a in pool:
        bands[age_band(profiles[a].age)] = bands.get(age_band(profiles[a].age), 0) + 1
    quota = {b: max(1, math.ceil(max_n * n / max(1, len(pool)))) for b, n in bands.items()}
    chosen: list[int] = []
    wait: list[int] = []
    used = dict.fromkeys(quota, 0)
    for a in accepted:
        b = age_band(profiles[a].age)
        if len(chosen) < max_n and used.get(b, 0) < quota.get(b, 1):
            chosen.append(a)
            used[b] = used.get(b, 0) + 1
        else:
            wait.append(a)
    for a in list(wait):                       # fill leftover seats from the waitlist in order
        if len(chosen) >= max_n:
            break
        chosen.append(a)
        wait.remove(a)
    return chosen, wait


def seat(chosen: list[int], table_size: int, profiles: list[Any], stance: dict[int, float], seed: int,
         survey_id: str) -> list[list[int]]:
    """Stratified seating: sort by (age band, income, stance) and deal round-robin so each table mixes."""
    n_tables = max(1, math.ceil(len(chosen) / table_size))
    rng = stream(seed, "seat", survey_id)
    order = sorted(chosen, key=lambda a: (age_band(profiles[a].age), profiles[a].income_band, stance.get(a, 0.0),
                                          float(rng.random())))
    tables: list[list[int]] = [[] for _ in range(n_tables)]
    for i, a in enumerate(order):
        tables[i % n_tables].append(a)
    return [t for t in tables if t]


def estimate(s: Survey, expected: int) -> dict[str, Any]:
    """Cost estimate = calls × tokens × prices (shared.models), before launch."""
    tok = cfg()["tokens"]
    n = max(1, expected)
    q = len(s.questions)
    calls: dict[str, int] = {"rsvp": 0}                  # who comes is decided by rules (reasons are templated): no model calls
    focus = s.mode == "focus_group" and n >= 2
    tables = max(1, math.ceil(n / s.table_size))
    disc_q = sum(1 for x in s.questions if x.discuss) if focus else 0
    # calibrated on recorded runs: ~6 speaker turns considered and ~4 spoken lines per discussed question per table
    calls.update({"prestance": n * q if focus else 0, "think": 6 * disc_q * tables, "speak": 4 * disc_q * tables,
                  "moderator": 3 * q * tables if focus else 0, "ballot": n * q,
                  "summary": tables + 1})
    total = 0.0
    for k, c in calls.items():
        tin, tout = tok[k]
        tier = "flash" if k == "summary" else "lite"
        per = cost_usd(tier, tin * (32 if k == "rsvp" else 1), tout * (32 if k == "rsvp" else 1))
        total += c * per
    return {"calls": calls, "usd": round(total, 4), "tables": tables, "per_participant_question":
            round(total / max(1, n * q), 5)}
