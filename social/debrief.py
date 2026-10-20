"""Private debrief (T-02 step 3): own context + spoken transcript → reaction, beliefs, episodic memory, intents."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from mind.context import build
from mind.memory import EventHook, MemoryStore
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.memory import MemoryEntry
from shared.schemas.social import Message
from shared.store import DocStore
from shared.subjects import canonical

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "debrief.md"
SUBJECT_PREFIXES = ("product:", "brand:", "category:")


class BeliefDelta(BaseModel):
    """One belief change."""

    subject: str
    attitude_delta: float = Field(ge=-1, le=1)
    reason: str


class HeardClaim(BaseModel):
    """Something the OTHER person said aloud about one attribute of a product (never anything unspoken)."""

    subject: str
    attribute: Literal["battery", "camera", "display", "performance", "software", "design", "price_value", "brand"]
    direction: Literal["+", "-"]
    strength: float = Field(ge=0, le=1)


class DebriefOut(BaseModel):
    """Structured debrief output."""

    reaction: str
    belief_deltas: list[BeliefDelta]
    heard_claims: list[HeardClaim] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)       # what the OTHER person said aloud they want in a phone
    summary: str
    importance: int = Field(ge=1, le=10)
    intents: list[str]


def render_transcript(msgs: list[Message], names: dict[int, str]) -> str:
    """Spoken lines only (the only thing that crosses between agents)."""
    return "\n".join(f"{names.get(m.speaker, str(m.speaker))}: {m.text}" for m in msgs)


async def debrief(agent_id: int, other_id: int, other_name: str, msgs: list[Message], names: dict[int, str], t: int,
                  *, store: DocStore, llm: LLMClient, now: str = "", product_ids: list[str] | None = None,
                  on_event: EventHook | None = None, priority_class: str = "P3",
                  catalog: dict[str, str] | None = None, opinions: str = "") -> tuple[DebriefOut, float]:
    """Run one agent's private debrief and write its own episodic memory and belief updates."""
    transcript = render_transcript(msgs, names)
    sid = msgs[0].session_id if msgs else ""
    ctx = await build(agent_id, "debrief", f"{other_name} {transcript[:300]}", f"Conversation with {other_name}.",
                      store=store, llm=llm, now=now, now_t=t, opinions=opinions)
    prompt = PROMPT.read_text(encoding="utf-8").replace("{context}", ctx.render()).replace("{transcript}", transcript)
    res = await llm.generate(MODEL_LITE, prompt, DebriefOut, purpose="conv_debrief", reasoning="low", max_tokens=350,
                             priority_class=priority_class)
    out: DebriefOut = res.data
    ms = MemoryStore(agent_id, store, llm, on_event)
    await ms.add(MemoryEntry(mid=f"conv-{sid}-{agent_id}", agent_id=agent_id, t=t, kind="conversation",
                             text=out.summary, importance=out.importance,
                             source={"channel": "conversation", "person_id": other_id, "session_id": sid},
                             entities=[other_name, *(product_ids or [])], event_refs=[]))
    spoken = transcript.lower()
    for d in out.belief_deltas:
        if not d.subject.startswith(SUBJECT_PREFIXES):
            continue
        if catalog is not None:                        # one product = one subject; unknown products are dropped
            canon = canonical(d.subject, catalog)
            if canon is None:
                continue
            d = d.model_copy(update={"subject": canon})
        prev = await ms.beliefs([d.subject])
        # with the opinion engine on (catalog given) a product's attitude is computed, not summed from model deltas
        engine_managed = catalog is not None and d.subject.startswith("product:")
        att = (prev[0].attitude if prev else 0.0) + (0.0 if engine_managed else d.attitude_delta)
        delta: dict = {"attitude": att, "t": t, "sources_seen": {"word_of_mouth": 1}}
        key = "reasons_for" if d.attitude_delta >= 0 else "reasons_against"
        delta[key] = list(dict.fromkeys([d.reason, *(getattr(prev[0], key) if prev else [])]))[:3]
        if not prev or prev[0].awareness == "unaware":
            delta["awareness"] = "heard"
            delta["stage"] = "aware"
        if d.subject.split(":", 1)[1].replace("-", " ") in spoken.replace("-", " "):
            delta["first_heard"] = {"channel": "word_of_mouth", "t": t, "ref": sid, "person_id": other_id}
        await ms.update_belief(d.subject, delta, cause_event_id=sid)
    return out, res.usage.cost_usd
