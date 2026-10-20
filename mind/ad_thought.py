"""Private thought on notice (A-03): one Flash-Lite call over the agent's own context → thought, memory, belief."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from media.screen import wrap
from mind.context import build
from mind.memory import EventHook, MemoryStore
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.memory import MemoryEntry
from shared.schemas.product import StimulusRecord
from shared.store import DocStore

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "ad_thought.md"
CHANNEL_WORDS = {"hoarding": "billboard", "bus_shelter": "bus-shelter poster", "metro_panel": "metro panel",
                 "reel": "reel", "newspaper": "newspaper ad", "store_display": "store display",
                 "community": "community thread", "review": "review"}


class AdThoughtOut(BaseModel):
    """Structured private thought."""

    thought: str
    why_noticed: str
    attitude_delta: float = Field(ge=-0.5, le=0.5)
    reasons_for: list[str]
    reasons_against: list[str]
    open_questions: list[str]
    intent_change: Literal["none", "curious", "research", "visit_store", "tell_friend", "dismiss"]
    wants_to_tell: str
    importance: int = Field(ge=1, le=10)


def describe(channel: str, product_name: str, place: str | None) -> str:
    """Short human label of where the ad was seen."""
    where = f" at {place}" if place else ""
    return f"the {product_name} {CHANNEL_WORDS.get(channel, channel)}{where}"


def rule_thought(stim: StimulusRecord, relevance: float, channel: str, product_name: str,
                 place: str | None) -> dict[str, Any]:
    """Over-cap fallback: deterministic nudge + template memory (rendered=false)."""
    delta = round(0.04 * stim.salience + 0.08 * relevance - 0.02, 3)
    return {"thought": f"Noticed {describe(channel, product_name, place)}.", "why_noticed": "salient creative",
            "attitude_delta": delta, "reasons_for": [], "reasons_against": [], "open_questions": [],
            "intent_change": "curious" if relevance > 0.6 else "none", "wants_to_tell": "",
            "importance": 3 + int(relevance > 0.6)}


async def apply_thought(agent_id: int, product_id: str, out: dict[str, Any], *, t: int, channel: str,
                        event_ref: str, store: DocStore, llm: LLMClient | None, on_event: EventHook | None,
                        product_name: str, place: str | None, set_attitude: bool = True) -> None:
    """L2 memory + L3 belief update (first_heard set once) for the agent's own stores."""
    ms = MemoryStore(agent_id, store, llm, on_event)
    await ms.add(MemoryEntry(mid=f"ad-{event_ref}-{agent_id}", agent_id=agent_id, t=t, kind="ad_thought",
                             text=out["thought"], importance=int(out["importance"]),
                             source={"channel": channel, "event_id": event_ref, "product_id": product_id},
                             entities=[product_name], event_refs=[event_ref]))
    subject = f"product:{product_id}"
    prev = await ms.beliefs([subject])
    b = prev[0] if prev else None
    delta: dict[str, Any] = {"t": t, "sources_seen": {channel: 1},
                             "first_heard": {"channel": channel, "t": t, "ref": event_ref}}
    if set_attitude:                       # off when the opinion engine computes (and mirrors) the attitude
        delta["attitude"] = (b.attitude if b else 0.0) + float(out["attitude_delta"])
    for key in ("reasons_for", "reasons_against", "open_questions"):
        if out.get(key):
            delta[key] = list(dict.fromkeys([*out[key], *(getattr(b, key) if b else [])]))[:3]
    if b is None or b.awareness in ("unaware", "heard"):
        delta["awareness"] = "aware"
    stage = b.stage if b else "unaware"
    if stage == "unaware":
        delta["stage"] = "aware"
    if out.get("intent_change") in ("curious", "research", "visit_store") and stage in ("unaware", "aware"):
        delta["stage"] = "curious"
    await ms.update_belief(subject, delta, cause_event_id=event_ref)


async def think_on_notice(agent_id: int, product_id: str, product_name: str, stim: StimulusRecord, channel: str,
                          place: str | None, t: int, *, store: DocStore, llm: LLMClient, now: str,
                          event_ref: str, on_event: EventHook | None = None, opinions: str = "",
                          set_attitude: bool = True) -> tuple[dict[str, Any], float]:
    """Rendered thought: own context + creative description → private thought, memory and belief update."""
    seen = describe(channel, product_name, place)
    ctx = await build(agent_id, "ad_thought", f"{product_name} {stim.hook}", f"Just noticed {seen}.",
                      store=store, llm=llm, now=now, now_t=t, opinions=opinions)
    prompt = (PROMPT.read_text(encoding="utf-8").replace("{context}", ctx.render())
              .replace("{seen}", seen).replace("{creative}", wrap(stim.description + " Hook: " + stim.hook,
                                                                    "creative")))
    res = await llm.generate(MODEL_LITE, prompt, AdThoughtOut, purpose="ad_thought", reasoning="low",
                             max_tokens=300, priority_class="P1")
    out = res.data.model_dump()
    out["thought"] = out["thought"][:400]
    await apply_thought(agent_id, product_id, out, t=t, channel=channel, event_ref=event_ref, store=store, llm=llm,
                        on_event=on_event, product_name=product_name, place=place, set_attitude=set_attitude)
    return out, res.usage.cost_usd
