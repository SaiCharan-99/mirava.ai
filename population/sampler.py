"""Seeded attribute sampler with quota allocation, so marginals match the configured priors (P-01)."""

from __future__ import annotations

from typing import Any

import numpy as np

from engine.rng import quota, stream
from population.config import market

ASSUMED_FIELDS = ["age", "occupation", "income_band", "commute_mode", "household", "lifestyle", "phone"]


def _assign(rng: np.random.Generator, idx: list[int], shares: dict[str, float]) -> dict[int, str]:
    """Give each index a label so the label counts follow `shares` exactly (shuffled)."""
    counts = quota(len(idx), shares)
    labels = [k for k in sorted(counts) for _ in range(counts[k])]
    order = rng.permutation(len(idx))
    return {idx[int(o)]: labels[i] for i, o in enumerate(order)}


def expected_marginals(n: int) -> dict[str, dict[str, float]]:
    """Config-implied marginal shares for age band, gender, occupation, income band and commute mode."""
    m = market()
    bands = {f"{b['lo']}-{b['hi']}": b["share"] for b in m["age_bands"]}
    occ: dict[str, float] = {}
    for band, share in bands.items():
        for o, s in m["occupation_by_band"][band].items():
            occ[o] = occ.get(o, 0.0) + share * s
    inc: dict[str, float] = {}
    com: dict[str, float] = {}
    for o, s in occ.items():
        spec = m["occupations"][o]
        for k, v in spec["income"].items():
            inc[k] = inc.get(k, 0.0) + s * v
        for k, v in spec["commute"].items():
            com[k] = com.get(k, 0.0) + s * v
    return {"age_band": bands, "gender": dict(m["gender"]), "occupation": occ, "income_band": inc, "commute_mode": com}


def sample_people(n: int, seed: int) -> list[dict[str, Any]]:
    """Sample `n` attribute rows (age, gender, occupation, income, commute, offmap, interests, lifestyle)."""
    m = market()
    rng = stream(seed, "sampler")
    bands = {f"{b['lo']}-{b['hi']}": b["share"] for b in m["age_bands"]}
    band_of = _assign(rng, list(range(n)), bands)
    people: list[dict[str, Any]] = []
    for i in range(n):
        lo, hi = (int(x) for x in band_of[i].split("-"))
        people.append({"i": i, "band": band_of[i], "age": int(rng.integers(lo, hi + 1))})
    gender = _assign(rng, list(range(n)), m["gender"])
    for p in people:
        p["gender"] = gender[p["i"]]
    for band in bands:
        idx = [p["i"] for p in people if p["band"] == band]
        if idx:
            for i, o in _assign(rng, idx, m["occupation_by_band"][band]).items():
                people[i]["occupation"] = o
    for occ, spec in m["occupations"].items():
        idx = [p["i"] for p in people if p["occupation"] == occ]
        if not idx:
            continue
        for i, v in _assign(rng, idx, spec["income"]).items():
            people[i]["income_band"] = v
        for i, v in _assign(rng, idx, spec["commute"]).items():
            people[i]["commute_mode"] = v
        off = _assign(rng, idx, {"yes": spec["offmap"], "no": 1 - spec["offmap"]})
        for i, v in off.items():
            people[i]["offmap"] = v == "yes"
    for p in people:
        spec = m["occupations"][p["occupation"]]
        p["label"] = spec["label"]
        p["education"] = m["education"].get(p["occupation"], m["education"]["default"])
        if p["offmap"] and p["commute_mode"] == "walk":
            p["commute_mode"] = "metro"
        p["lifestyle"] = _lifestyle(rng, p)
        pool = list(spec["interests"]) + _LIFESTYLE_INTERESTS[p["lifestyle"]]
        k = min(len(pool), 3)
        p["interests"] = sorted({str(x) for x in rng.choice(pool, size=k + 1, replace=False)})[:k]
    return people


_LIFESTYLE_INTERESTS: dict[str, list[str]] = {
    "young_professional": ["tech", "travel", "coffee", "startups"], "family_first": ["family", "cooking", "movies"],
    "traditional": ["devotional", "news", "family"], "student_life": ["gaming", "music", "anime"],
    "fitness_focused": ["fitness", "running", "cycling"], "creative": ["photography", "design", "art"],
    "frugal": ["deals", "cooking", "news"], "social_butterfly": ["food", "music", "fashion"],
}


def _lifestyle(rng: np.random.Generator, p: dict[str, Any]) -> str:
    """Lifestyle cluster conditioned on age and occupation."""
    if p["occupation"] in ("school_student", "college_student"):
        return "student_life" if rng.random() < 0.8 else "social_butterfly"
    if p["age"] >= 60:
        return "traditional" if rng.random() < 0.6 else ("family_first" if rng.random() < 0.6 else "frugal")
    if p["occupation"] in ("product_designer", "ux_designer", "content_creator"):
        return "creative" if rng.random() < 0.6 else "young_professional"
    if p["income_band"] in ("<25k",):
        return "frugal" if rng.random() < 0.5 else ("family_first" if rng.random() < 0.5 else "traditional")
    w = {"young_professional": 0.3 if p["age"] < 40 else 0.1, "family_first": 0.25 if p["age"] >= 30 else 0.05,
         "fitness_focused": 0.12, "social_butterfly": 0.12, "frugal": 0.1, "traditional": 0.06, "creative": 0.05}
    keys = sorted(w)
    pr = np.array([w[k] for k in keys])
    return keys[int(rng.choice(len(keys), p=pr / pr.sum()))]
