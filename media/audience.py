"""Target personas → audience rules (L-05): filters over agent attributes; personas aim, never create agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from media.screen import wrap
from population.possessions import phone_age_years
from shared import models
from shared.llm import FakeGemini, LLMClient
from shared.schemas.product import AudienceRule

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "audience.md"
INCOME_BANDS = ["<25k", "25-50k", "50k-1L", "1-2L", ">2L"]
INTERESTS = ["anime", "art", "bikes", "books", "coffee", "cooking", "cricket", "design", "devotional", "family",
             "fashion", "finance", "fitness", "food", "football", "gadgets", "gaming", "gardening", "golf", "health",
             "movies", "music", "news", "photography", "reading", "running", "shopping", "startups", "tech", "travel",
             "tv_serials", "walking", "wine"]
_KEYWORDS: list[tuple[str, dict]] = [
    (r"photo|camera|creator|instagram", {"interests_any": ["photography", "fashion", "travel"]}),
    (r"tech|gadget|engineer|developer|early adopter", {"interests_any": ["tech", "gadgets", "startups"]}),
    (r"gam", {"interests_any": ["gaming", "anime"]}),
    (r"fitness|gym|runner", {"interests_any": ["fitness", "running"]}),
    (r"student|college", {"age": [17, 24]}),
    (r"young professional|professional|office", {"age": [22, 38]}),
    (r"parent|family", {"age": [30, 50]}),
    (r"senior|retired|elder", {"age": [58, 90]}),
    (r"premium|affluent|high income|flagship", {"income_bands": ["1-2L", ">2L"]}),
    (r"budget|value|price.sensitive", {"income_bands": ["<25k", "25-50k", "50k-1L"]}),
    (r"old phone|upgrade|ageing phone|aging phone", {"phone_age_gt": 3}),
]


class RuleOut(BaseModel):
    """One compiled audience rule (model output)."""

    description: str
    interests_any: list[str] = Field(default_factory=list)
    age_min: int = Field(0, ge=0, le=100)
    age_max: int = Field(100, ge=0, le=100)
    income_bands: list[str] = Field(default_factory=list)
    phone_age_gt: float = Field(0, ge=0, le=15)


class RulesOut(BaseModel):
    """Model output: audience rules for a product."""

    rules: list[RuleOut]


def _clean(r: RuleOut) -> dict:
    f: dict[str, Any] = {}
    ints = [i for i in r.interests_any if i in INTERESTS]
    if ints:
        f["interests_any"] = ints
    if r.age_min > 0 or r.age_max < 100:
        f["age"] = [min(r.age_min, r.age_max), max(r.age_min, r.age_max)]
    bands = [b for b in r.income_bands if b in INCOME_BANDS]
    if bands:
        f["income_bands"] = bands
    if r.phone_age_gt > 0:
        f["phone_age_gt"] = r.phone_age_gt
    return f


def rule_compile(personas: list[str]) -> list[dict]:
    """Deterministic keyword compiler: one filter per persona (used offline and as fallback)."""
    out = []
    for p in personas:
        f: dict[str, Any] = {}
        for pat, add in _KEYWORDS:
            if re.search(pat, p, re.I):
                for k, v in add.items():
                    f[k] = sorted(set(f.get(k, [])) | set(v)) if k in ("interests_any", "income_bands") else v
        out.append({"description": p, "filter": f})
    return out


def matches(profile: dict, flt: dict, t: int = 0) -> bool:
    """Does an agent profile satisfy a filter?"""
    if profile.get("special_role", "none") not in ("none", "reviewer"):
        return False
    ints = flt.get("interests_any")
    if ints and not set(ints) & set(profile.get("persona", {}).get("interests", [])):
        return False
    age = flt.get("age")
    if age and not age[0] <= profile.get("age", 0) <= age[1]:
        return False
    bands = flt.get("income_bands")
    if bands and profile.get("income_band") not in bands:
        return False
    pa = flt.get("phone_age_gt")
    if pa:
        ph = profile.get("possessions", {}).get("phone", {})
        if "bought_t" not in ph or phone_age_years(ph, t) <= pa:
            return False
    return True


def audience_ids(rules: list[AudienceRule] | list[dict], profiles: list[dict], t: int = 0) -> list[int]:
    """Agent ids matching any rule (sorted)."""
    flts = [r.filter if isinstance(r, AudienceRule) else r["filter"] for r in rules]
    flts = [f for f in flts if f]
    if not flts:
        return []
    return sorted(p["agent_id"] for p in profiles if any(matches(p, f, t) for f in flts))


async def compile_rules(personas: list[str], profiles: list[dict], llm: LLMClient | None, t: int = 0,
                        use_model: bool = True) -> list[AudienceRule]:
    """Personas → audience rules with live counts; Gemini compiles, the keyword compiler backs it up."""
    personas = [p.strip() for p in personas if p.strip()]
    if not personas:
        return []
    compiled: list[dict[str, Any]] = rule_compile(personas)
    if llm is not None and use_model and not isinstance(llm, FakeGemini):
        try:
            prompt = PROMPT.read_text(encoding="utf-8").format(
                personas=wrap("\n".join(f"- {p}" for p in personas), "personas"),
                interests=", ".join(INTERESTS), bands=", ".join(INCOME_BANDS))
            res = await llm.generate(models.MODEL_FLASH, prompt, RulesOut, purpose="audience_rules",
                                     max_tokens=800, priority_class="P0")
            got = [{"description": r.description[:120] or personas[min(i, len(personas) - 1)], "filter": _clean(r)}
                   for i, r in enumerate(res.data.rules)]
            got = [g for g in got if g["filter"]]
            if got:
                compiled = got
        except Exception:  # noqa: BLE001 — keyword rules are a safe fallback
            pass
    return [AudienceRule(description=str(c["description"]), filter=dict(c["filter"]),
                         count=len(audience_ids([c], profiles, t))) for c in compiled]
