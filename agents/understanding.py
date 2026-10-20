"""Understanding (L-03): product profile, claim risk (red/amber/green) and a StimulusRecord per creative."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from media.screen import wrap
from shared import models
from shared.llm import FakeGemini, LLMClient
from shared.schemas.product import Creative, Product, StimulusRecord

PROMPTS = Path(__file__).resolve().parents[1] / "shared" / "prompts"
Risk = Literal["red", "amber", "green"]
_ABSOLUTE = re.compile(r"\b(best|ever|guarantee[ds]?|always|never|every|#1|number one|unbeatable|perfect|only)\b", re.I)
_VAGUE = re.compile(r"\b(pro-level|lightest|fastest|smartest|revolutionary|stunning|amazing|ultimate)\b", re.I)
_SPECIFIC = re.compile(r"\d")
_KIND_SALIENCE = {"hoarding": 0.7, "bus_shelter": 0.55, "reel": 0.75, "social_post": 0.5, "newspaper": 0.45,
                  "store_display": 0.6, "reviewer_kit": 0.0}


class ClaimOut(BaseModel):
    """A claim found in the content, linked to its source."""

    text: str
    source: str
    risk: Risk
    reason: str


class ProfileOut(BaseModel):
    """Understanding agent output (product profile)."""

    summary: str
    claims: list[ClaimOut]
    entities: list[str]
    concerns: list[str]
    competitors: list[str]
    target_hypothesis: str


class RiskOut(BaseModel):
    """Claim risk scanner output, one per claim in input order."""

    ratings: list[ClaimOut]


class StimulusOut(BaseModel):
    """Creative understanding output."""

    salience: float = Field(ge=0, le=1)
    clarity: float = Field(ge=0, le=1)
    hook: str
    claims_carried: list[str]
    tone: str
    readable_at_distance: bool
    description: str


class SpecsOut(BaseModel):
    """Neutral 0..1 rating per attribute (the product's 'truth' for the opinion engine)."""

    battery: float = Field(ge=0, le=1)
    camera: float = Field(ge=0, le=1)
    display: float = Field(ge=0, le=1)
    performance: float = Field(ge=0, le=1)
    software: float = Field(ge=0, le=1)
    design: float = Field(ge=0, le=1)
    price_value: float = Field(ge=0, le=1)
    brand: float = Field(ge=0, le=1)


async def extract_specs(p: Product, llm: LLMClient | None = None) -> dict[str, float]:
    """Truth specs per attribute: keyword rules always; a neutral Flash rating (blended 50/50) when a real model is on."""
    from mind.opinion import heuristic_specs

    rules = heuristic_specs(p.features, p.claims, p.price_inr, p.brand)
    if llm is None or isinstance(llm, FakeGemini):
        return rules
    try:
        res = await llm.generate(models.MODEL_FLASH, PROMPTS.joinpath("specs.md").read_text(encoding="utf-8")
                                 .format(brief=wrap(_brief(p), "product")), SpecsOut, purpose="specs", max_tokens=200,
                                 priority_class="P0")
        got = res.data.model_dump()
        return {a: round(0.5 * rules[a] + 0.5 * float(got[a]), 3) for a in rules}
    except Exception:  # noqa: BLE001 — the rules are the fallback
        return rules


def rule_risk(claim: str) -> tuple[Risk, str]:
    """Heuristic claim risk: absolutes are red, vague superlatives amber, specific numbers green."""
    if _ABSOLUTE.search(claim):
        return "red", "Absolute or guaranteed wording that the specs cannot prove"
    if _VAGUE.search(claim) or not _SPECIFIC.search(claim):
        return "amber", "Unverifiable or vague quality claim"
    return "green", "Specific and verifiable"


def _creative_text(c: Creative) -> str:
    parts = [c.title, c.text or "", c.transcript or "", " ".join(c.scenes)]
    return " ".join(p for p in parts if p).strip()


def rule_stimulus(c: Creative, claims: list[str]) -> StimulusRecord:
    """Heuristic StimulusRecord (offline and fallback)."""
    text = _creative_text(c)
    words = len(text.split())
    carried = [cl for cl in claims if any(w.lower() in text.lower() for w in cl.split()[:3] if len(w) > 3)][:3]
    short = words <= 12
    base = _KIND_SALIENCE.get(c.kind, 0.5)
    salience = round(min(1.0, base + (0.08 if short else -0.05) + (0.05 if c.image_uri else 0)), 2)
    clarity = round(max(0.2, min(1.0, 0.9 - max(0, words - 10) * 0.02)), 2)
    hook = (c.text or c.title or "").split(".")[0][:80]
    tone = "aspirational" if c.kind in ("hoarding", "reel") else "informative"
    desc = (f"A {c.kind.replace('_', ' ')} for the product reading “{hook}”. "
            f"It {'is easy to read from a distance' if short else 'needs a closer look to read'}.")
    return StimulusRecord(creative_id=c.creative_id, salience=salience, clarity=clarity, hook=hook,
                          claims_carried=carried, tone=tone, readable_at_distance=short and c.kind != "newspaper",
                          description=desc)


def _brief(p: Product) -> str:
    lines = [f"Name: {p.name}", f"Brand: {p.brand}", f"Category: {p.category}", f"Price (INR): {p.price_inr}",
             f"Offer: {p.launch_offer or '-'}", "Features: " + "; ".join(p.features), "Claims: " + "; ".join(p.claims),
             "Personas: " + "; ".join(p.target_personas)]
    lines += [f"[{c.creative_id} · {c.kind}] {_creative_text(c)}" for c in p.creatives]
    return "\n".join(lines)


async def understand(p: Product, llm: LLMClient) -> dict:
    """Run profile → claim risk → creative understanding; returns {understanding, stimuli}."""
    offline = isinstance(llm, FakeGemini)
    claims = [{"text": c, "source": "details", "risk": r, "reason": why} for c in p.claims for r, why in [rule_risk(c)]]
    profile = {"summary": f"{p.brand} {p.name}: {p.category} at ₹{p.price_inr:,}.", "entities": [p.brand],
               "concerns": [], "competitors": [], "target_hypothesis": "; ".join(p.target_personas)}
    if not offline:
        brief = wrap(_brief(p), "product")
        try:
            res = await llm.generate(models.MODEL_FLASH, PROMPTS.joinpath("understand.md").read_text(encoding="utf-8")
                                     .format(brief=brief), ProfileOut, purpose="understanding", max_tokens=1500,
                                     priority_class="P0")
            d: ProfileOut = res.data
            profile = {"summary": d.summary, "entities": d.entities[:8], "concerns": d.concerns[:6],
                       "competitors": d.competitors[:5], "target_hypothesis": d.target_hypothesis}
            seen = {c["text"] for c in claims}
            claims += [c.model_dump() for c in d.claims if c.text not in seen][:6]
            res2 = await llm.generate(models.MODEL_PRO, PROMPTS.joinpath("claim_risk.md").read_text(encoding="utf-8")
                                      .format(claims=wrap("\n".join(f"- {c['text']}" for c in claims), "claims"),
                                              brief=brief), RiskOut, purpose="claim_risk", max_tokens=1500,
                                      priority_class="P0")
            for c, r in zip(claims, res2.data.ratings, strict=False):
                c["risk"], c["reason"] = r.risk, r.reason[:200]
        except Exception:  # noqa: BLE001 — heuristic understanding is the fallback
            pass
    stimuli = []
    for c in p.creatives:
        st = rule_stimulus(c, p.claims)
        if not offline and c.kind != "reviewer_kit":
            try:
                res3 = await llm.generate(models.MODEL_FLASH, PROMPTS.joinpath("stimulus.md").read_text(
                    encoding="utf-8").format(kind=c.kind, creative=wrap(_creative_text(c), "creative")),
                    StimulusOut, purpose="creative_understanding", max_tokens=500, priority_class="P0",
                    images=[c.image_uri] if c.image_uri and c.image_uri.startswith("http") else None)
                st = StimulusRecord(creative_id=c.creative_id, **res3.data.model_dump())
            except Exception:  # noqa: BLE001
                pass
        stimuli.append(st)
    return {"understanding": {**profile, "claims": claims}, "stimuli": stimuli, "specs": await extract_specs(p, llm)}
