"""Persona core (P-02): attribute-consistent template + Gemini Flash bios in batches, validated; persona cards."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from engine.rng import stream
from shared.llm import LLMClient
from shared.models import MODEL_FLASH
from shared.schemas.agent import PersonaCore

PROMPT = Path("shared/prompts/persona_batch.md")
BATCH = 25

_STYLE = {
    "student_life": "casual English with Kannada slang, short bursts", "traditional": "polite, English mixed with Kannada and Hindi phrases",
    "young_professional": "crisp English, a little startup jargon", "family_first": "warm, English with Hindi phrases",
    "fitness_focused": "upbeat, short sentences", "creative": "expressive, English with Kannada phrases",
    "frugal": "practical and direct, English with Tamil or Kannada words", "social_butterfly": "chatty, lots of emojis in texts",
}
_VALUES = {
    "student_life": ["fun", "friends", "independence"], "traditional": ["family", "faith", "thrift"],
    "young_professional": ["growth", "convenience", "status"], "family_first": ["family", "security", "health"],
    "fitness_focused": ["health", "discipline", "energy"], "creative": ["self-expression", "quality", "curiosity"],
    "frugal": ["value for money", "security", "family"], "social_butterfly": ["friends", "fun", "trends"],
}
_MONEY = {
    "frugal": "I compare prices a lot and hate wasting money.", "traditional": "I save first and spend later.",
    "young_professional": "I don't mind paying for things that save me time.",
    "family_first": "Most of my money goes to the family, so I plan big buys.",
    "student_life": "Money is tight, so I wait for sales.", "creative": "I'd rather buy one good thing than three cheap ones.",
    "fitness_focused": "I spend on health and gear, not much else.", "social_butterfly": "I spend on going out with friends.",
}


class BioItem(BaseModel):
    """One model-written persona item."""

    agent_id: int
    bio_first_person: str
    speaking_style: str
    values: list[str]


class BioBatch(BaseModel):
    """A batch of persona items."""

    items: list[BioItem]


def base_persona(p: dict[str, Any], seed: int) -> PersonaCore:
    """Attribute-consistent persona core without a model call (also the fallback)."""
    rng = stream(seed, "persona", p["i"])
    shift = {"social_butterfly": {"E": 0.2}, "creative": {"O": 0.2}, "frugal": {"C": 0.15},
             "fitness_focused": {"C": 0.15, "E": 0.1}, "traditional": {"O": -0.15, "C": 0.1}}.get(p["lifestyle"], {})
    big5 = {k: round(float(np.clip(rng.normal(0.5 + shift.get(k, 0.0), 0.17), 0.03, 0.97)), 2) for k in "OCEAN"}
    disclosure = {
        "opinions": round(float(np.clip(0.3 + 0.6 * big5["E"] + rng.normal(0, 0.1), 0, 1)), 2),
        "money": round(float(np.clip(0.15 + 0.4 * big5["A"] - 0.2 * big5["C"] + rng.normal(0, 0.12), 0, 1)), 2),
        "feelings": round(float(np.clip(0.2 + 0.4 * big5["A"] + 0.2 * big5["E"] + rng.normal(0, 0.12), 0, 1)), 2),
        "plans": round(float(np.clip(0.3 + 0.4 * big5["E"] + rng.normal(0, 0.12), 0, 1)), 2),
    }
    first = p["name"].split()[0]
    work = p["work_phrase"]
    bio = (f"I'm {first}, {p['age']}, {work}. I'm into {', '.join(p['interests'][:2])}. "
           f"{_MONEY[p['lifestyle']]}")
    attitudes = {p["phone"]["brand"]: round(float(np.clip(p["phone"]["satisfaction"] * 2 - 1, -1, 1)), 2)}
    return PersonaCore(bio_first_person=bio, big5=big5, values=_VALUES[p["lifestyle"]], lifestyle=p["lifestyle"],  # type: ignore[arg-type]
                       interests=list(p["interests"]), brand_attitudes=attitudes, speaking_style=_STYLE[p["lifestyle"]],
                       disclosure=disclosure)  # type: ignore[arg-type]


def word(v: float) -> str:
    """Disclosure value → open / guarded / private."""
    return "open" if v >= 0.6 else ("guarded" if v >= 0.35 else "private")


def persona_card(p: dict[str, Any], core: PersonaCore) -> str:
    """Fixed ≤150-token card used in every prompt for this agent (M-06)."""
    ph = p["phone"]
    b = core.big5
    d = core.disclosure
    card = (f"{p['name']}, {p['age']}, {p['gender']}, {p['label']}{p['work_card']}. Indiranagar, household of "
            f"{p['household_size']} ({p['role']}). Income {p['income_band']}/month. Lifestyle {core.lifestyle.replace('_', ' ')}; "
            f"into {', '.join(core.interests[:3])}. Values {', '.join(core.values[:3])}. Phone {ph['brand']} {ph['tier']}, "
            f"{p['phone_age']:.1f} y, {ph['condition'].replace('_', ' ')}. Big5 O{b['O']:.1f} C{b['C']:.1f} E{b['E']:.1f} "
            f"A{b['A']:.1f} N{b['N']:.1f}. Speaks {core.speaking_style}. Shares opinions {word(d['opinions'])}, "
            f"money {word(d['money'])}, feelings {word(d['feelings'])}.")
    return card


def card_tokens(card: str) -> int:
    """Rough token count (≈ 4 chars per token)."""
    return (len(card) + 3) // 4


def valid_bio(p: dict[str, Any], item: BioItem) -> bool:
    """A model bio is kept only if it is consistent with the sampled attributes."""
    bio = item.bio_first_person
    first = p["name"].split()[0]
    return (item.agent_id == p["i"] and bio.startswith(f"I'm {first}") and str(p["age"]) in bio[:40]
            and 120 <= len(bio) <= 420 and not any(w in bio.lower() for w in ("as an ai", "fictional")))


async def write_bios(people: list[dict[str, Any]], cores: dict[int, PersonaCore], llm: LLMClient,
                     concurrency: int = 8) -> dict[str, Any]:
    """Ask Gemini Flash for bios in batches of 25; keep valid ones, fall back to templates. Returns stats."""
    sem = asyncio.Semaphore(concurrency)
    tmpl = PROMPT.read_text(encoding="utf-8")
    stats = {"batches": 0, "model_bios": 0, "fallback": 0, "cost_usd": 0.0}
    by = {p["i"]: p for p in people}

    async def run(batch: list[dict[str, Any]]) -> None:
        cards = "\n".join(f"- agent_id={p['i']} | {p['persona_card']}" for p in batch)
        async with sem:
            try:
                res = await llm.generate(MODEL_FLASH, tmpl.replace("{cards}", cards), BioBatch, purpose="persona_batch",
                                         reasoning="low", max_tokens=200 * len(batch), priority_class="P5")
            except Exception:  # noqa: BLE001 — any model failure falls back to templates
                stats["fallback"] += len(batch)
                return
        stats["batches"] += 1
        stats["cost_usd"] += res.usage.cost_usd or 0.0
        got = {it.agent_id: it for it in (res.data.items if res.data else [])}
        for p in batch:
            it = got.get(p["i"])
            if it is not None and valid_bio(by[p["i"]], it):
                c = cores[p["i"]]
                cores[p["i"]] = c.model_copy(update={"bio_first_person": it.bio_first_person.strip(),
                                                     "speaking_style": it.speaking_style.strip()[:120] or c.speaking_style,
                                                     "values": [v[:30] for v in it.values[:3]] or c.values})
                stats["model_bios"] += 1
            else:
                stats["fallback"] += 1

    await asyncio.gather(*(run(people[k:k + BATCH]) for k in range(0, len(people), BATCH)))
    return stats
