"""Reviewers (C-04) and community replies (C-05): private opinion/thought first, then public text."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from media.screen import wrap
from mind.context import build
from shared.llm import LLMClient
from shared.models import MODEL_FLASH, MODEL_LITE
from shared.schemas.product import Product
from shared.store import DocStore

PROMPTS = Path(__file__).resolve().parents[1] / "shared" / "prompts"


class ReviewOut(BaseModel):
    """Reviewer output: the private opinion and the review they choose to publish."""

    private_opinion: str
    title: str
    summary: str
    rating: float = Field(ge=0, le=10)
    pros: list[str]
    cons: list[str]


class CommunityOut(BaseModel):
    """A reader's private thought on a thread and what they decide to do publicly."""

    thought: str
    action: Literal["none", "upvote", "comment"]
    comment: str
    attitude_delta: float = Field(ge=-0.5, le=0.5)


def facts(p: Product) -> str:
    """Product facts block for reviewers (data, not instructions)."""
    kit = next((c for c in p.creatives if c.kind == "reviewer_kit"), None)
    lines = [f"{p.brand} {p.name} · {p.category} · ₹{p.price_inr:,}", f"Offer: {p.launch_offer or '-'}",
             "Features: " + "; ".join(p.features), "Marketing claims: " + "; ".join(p.claims)]
    if kit and kit.text:
        lines.append("Reviewer kit: " + kit.text[:600])
    return wrap("\n".join(lines), "product")


def template_review(p: Product, reviewer_id: int) -> dict[str, Any]:
    """Fallback review (rendered=false)."""
    f = p.features[:2] or ["design"]
    return {"private_opinion": f"The {p.name} seems solid; I need more time with it.", "title": f"{p.name} first look",
            "summary": f"Early impressions of the {p.name}: {', '.join(f)} stand out.", "rating": 7.0,
            "pros": f, "cons": ["price"]}


async def write_review(reviewer_id: int, p: Product, t: int, *, store: DocStore, llm: LLMClient,
                       now: str) -> tuple[dict[str, Any], float]:
    """Reviewer's own context + product facts → private opinion and the published review."""
    ctx = await build(reviewer_id, "review", f"{p.name} {p.category}", f"Reviewing the {p.name}.",
                      store=store, llm=llm, now=now, now_t=t)
    prompt = (PROMPTS / "review.md").read_text(encoding="utf-8").replace("{context}", ctx.render()) \
        .replace("{facts}", facts(p))
    res = await llm.generate(MODEL_FLASH, prompt, ReviewOut, purpose="review", reasoning="low", max_tokens=600,
                             priority_class="P5")
    return res.data.model_dump(), res.usage.cost_usd


async def reply(agent_id: int, thread: dict[str, Any], comments: list[str], t: int, *, store: DocStore,
                llm: LLMClient, now: str) -> tuple[dict[str, Any], float]:
    """Reader's private thought on a thread + decision + (if commenting) the public comment."""
    ctx = await build(agent_id, "community", thread["title"], f"Reading a thread in {thread['forum']}.",
                      store=store, llm=llm, now=now, now_t=t)
    body = f"{thread['forum']} · {thread['title']}\n{thread.get('body', '')[:500]}\n" + \
        "\n".join(f"- {c[:200]}" for c in comments[:3])
    prompt = (PROMPTS / "community_reply.md").read_text(encoding="utf-8").replace("{context}", ctx.render()) \
        .replace("{thread}", wrap(body, "thread"))
    res = await llm.generate(MODEL_LITE, prompt, CommunityOut, purpose="community", reasoning="low", max_tokens=250,
                             priority_class="P5")
    out = res.data.model_dump()
    out["comment"] = out["comment"][:400] if out["action"] == "comment" else ""
    return out, res.usage.cost_usd
