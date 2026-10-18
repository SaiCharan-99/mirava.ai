"""Auto planner (L-06): traffic → score → greedy max-coverage site selection + the other channels. Deterministic."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from media.screen import wrap
from media.traffic import Traffic
from shared import models
from shared.llm import FakeGemini, LLMClient
from shared.schemas.product import Plan, PlannedSite, Product
from shared.schemas.world import Site, Store

log = logging.getLogger("media.planner")
PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "site_reason.md"
K_BY_INTENSITY = {"low": 4, "medium": 8, "high": 12}
REVIEWERS_BY_INTENSITY = {"low": 2, "medium": 4, "high": 6}
DIVERSITY_M = 150.0
DIVERSITY_FACTOR = 0.5
KIND_GLANCE = {"billboard": 1.0, "unipole": 1.1, "facade_screen": 1.2, "bus_shelter": 0.8, "metro_panel": 0.85}
_COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def compass(deg: float) -> str:
    """Bearing → 8-point compass word."""
    return _COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def glance_prior(s: Site) -> float:
    """Relative glance chance from size, lighting and format (labelled assumption)."""
    area = s.width_m * s.height_m
    return KIND_GLANCE.get(s.kind, 1.0) * (0.6 + 0.4 * min(1.0, area / 20)) * (1.1 if s.lit else 1.0)


def _creative_for(p: Product, s: Site) -> str:
    kinds = {c.kind: c.creative_id for c in p.creatives}
    pref = ["bus_shelter", "hoarding"] if s.kind in ("bus_shelter", "metro_panel") else ["hoarding", "bus_shelter"]
    return next((kinds[k] for k in pref if k in kinds), p.creatives[0].creative_id if p.creatives else "")


def select_sites(p: Product, traffic: Traffic, sites: list[Site], audience: set[int], held: set[str]) -> list[dict]:
    """Greedy max-coverage of distinct target agents, one face per site, 150 m diversity penalty."""
    k = K_BY_INTENSITY.get(str(p.strategy.get("intensity", "medium")), 8)
    cands: list[dict[str, Any]] = []
    for s in sorted(sites, key=lambda s: s.site_id):
        if s.site_id in held:
            continue
        rate_day = max(1.0, s.rate_card_inr_week / 7)
        for f in s.facings:
            per = traffic.agents.get((s.site_id, float(f)), {})
            tgt = {a: c for a, c in per.items() if not audience or a in audience}
            if not tgt:
                continue
            cands.append({"site": s, "facing": float(f), "tgt": tgt, "tgt_ots": sum(tgt.values()),
                          "w": glance_prior(s) / math.sqrt(rate_day / 1000)})
    chosen: list[dict[str, Any]] = []
    covered: set[int] = set()
    while len(chosen) < k and cands:
        best: dict[str, Any] | None = None
        best_score = 0.0
        for c in cands:
            new = sum(1 for a in c["tgt"] if a not in covered)
            score = (new + 0.25 * c["tgt_ots"]) * c["w"]
            if any(math.hypot(c["site"].x - o["site"].x, c["site"].y - o["site"].y) < DIVERSITY_M for o in chosen):
                score *= DIVERSITY_FACTOR
            if score > best_score + 1e-9:
                best, best_score = c, score
        if best is None:
            break
        chosen.append(best)
        covered |= set(best["tgt"])
        cands = [c for c in cands if c["site"].site_id != best["site"].site_id]
    return chosen


def template_reason(c: dict, traffic: Traffic) -> str:
    """Rule reason (used offline and when the model is unavailable)."""
    s: Site = c["site"]
    hist = traffic.by_hour.get((s.site_id, c["facing"]))
    peak = int(hist.argmax()) if hist is not None and hist.sum() > 0 else 18
    return (f"{s.kind.replace('_', ' ').capitalize()} facing {compass(c['facing'])} at {s.area_label}: catches "
            f"~{round(c['tgt_ots']):,} target OTS/day, busiest around {peak:02d}:00"
            f"{'; lit at night' if s.lit else ''}.")


def plan_product(product: Product, world_day: int, *, traffic: Traffic, sites: list[Site], stores: list[Store],
                 audience: list[int], reviewers: list[dict], news_desk: int | None, held_sites: set[str]) -> Plan:
    """Deterministic plan for (product, world_day, world data); reasons are templates until `write_reasons`."""
    aud = set(audience)
    chosen = select_sites(product, traffic, sites, aud, held_sites)
    planned = [PlannedSite(site_id=c["site"].site_id, facing=c["facing"], creative_id=_creative_for(product, c["site"]),
                           est_target_ots_day=round(c["tgt_ots"]), reason=template_reason(c, traffic))
               for c in chosen]
    intensity = str(product.strategy.get("intensity", "medium"))
    flight = int(product.strategy.get("flight_days", 14))
    kinds = {c.kind: c.creative_id for c in product.creatives}
    reel = {"creative_id": kinds.get("reel"), "audience_rule_ids": list(range(len(product.audience))),
            "audience_size": len(aud), "impressions_day": round(len(aud) * 1.6) if "reel" in kinds else 0,
            "freq_cap": 3}
    news = [d for d in (0, 2, 5, 9) if d < flight] if "newspaper" in kinds else []
    tech = product.category.lower() in ("smartphone", "phone", "laptop", "electronics", "wearable")
    niche = "tech" if tech else "lifestyle"

    def overlap(r: dict) -> tuple[int, int, int]:
        return (int(r.get("niche") == niche), len(set(r.get("followers", [])) & aud), -r["agent_id"])

    n_rev = REVIEWERS_BY_INTENSITY.get(intensity, 4)
    revs = [r["agent_id"] for r in sorted(reviewers, key=overlap, reverse=True)[:n_rev]]
    physical = [s for s in sorted(stores, key=lambda s: s.store_id) if s.kind != "online"]
    want = product.strategy.get("stores")
    st = [s.store_id for s in physical if not want or s.name in want or s.store_id in want]
    st = st[: {"low": 2}.get(intensity, len(st))]
    seed = {"forum": "r/BangaloreTech" if tech else "r/BangaloreStyle", "author": news_desk,
            "title": f"{product.brand} {product.name} launches in Bengaluru at ₹{product.price_inr:,}",
            "day_offset": 0}
    return Plan(sites=planned, reel=reel, newspaper_days=news, reviewers=revs, community_seed=seed, stores=st,
                flight_days=flight, generated_day=world_day)


class ReasonsOut(BaseModel):
    """One reason per site, in input order."""

    reasons: list[str]


async def write_reasons(plan: Plan, product: Product, sites: dict[str, Site], llm: LLMClient) -> Plan:
    """Gemini (Flash) rewrites each site reason from the computed facts; templates stay on failure or offline."""
    if isinstance(llm, FakeGemini) or not plan.sites:
        return plan
    facts = "\n".join(f"{i + 1}. {ps.site_id} · {sites[ps.site_id].kind} at {sites[ps.site_id].area_label} · faces "
                      f"{compass(ps.facing)} · lit={sites[ps.site_id].lit} · {ps.est_target_ots_day} target OTS/day · "
                      f"{ps.reason}" for i, ps in enumerate(plan.sites))
    try:
        res = await llm.generate(models.MODEL_FLASH, PROMPT.read_text(encoding="utf-8").format(
            product=wrap(f"{product.name} ({product.category}); personas: {'; '.join(product.target_personas)}",
                         "product"), facts=wrap(facts, "sites")), ReasonsOut, purpose="site_reasons",
            max_tokens=900, priority_class="P0")
        rs = res.data.reasons
        if len(rs) == len(plan.sites):
            for ps, r in zip(plan.sites, rs, strict=True):
                if r.strip():
                    ps.reason = r.strip()[:240]
    except Exception:  # noqa: BLE001 — templates stay, but say why
        log.warning("site reasons fell back to templates", exc_info=True)
    return plan
