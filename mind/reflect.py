"""Nightly reflection and pruning (M-05): 03:00 sim, agents whose day importance ≥ 12, governor-capped."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from mind.context import build
from mind.memory import EventHook, MemoryStore
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.memory import MemoryEntry
from shared.store import DocStore

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "reflect.md"
THRESHOLD = 12
KEEP = 300


class BeliefUpdate(BaseModel):
    """One belief nudge from reflection."""

    subject: str
    attitude_delta: float = Field(ge=-1, le=1)
    reason: str


class ReflectOut(BaseModel):
    """Structured reflection output."""

    reflections: list[str]
    belief_updates: list[BeliefUpdate]
    importance: int = Field(ge=1, le=10)


def day_importance(episodes: list[dict]) -> int:
    """Summed importance of today's working-memory episodes."""
    return sum(int(e.get("importance", 0)) for e in episodes)


async def reflect(agent_id: int, episodes: list[dict], t: int, *, store: DocStore, llm: LLMClient,
                  on_event: EventHook | None = None) -> tuple[dict, float]:
    """Write 1–3 reflections, apply belief updates, prune to 300; returns (`reflection` payload, cost)."""
    today = "\n".join(f"- {e['text']}" for e in episodes[-20:])
    ctx = await build(agent_id, "reflect", today[:400], "Tonight I think back over my day.", store=store, llm=llm,
                      now_t=t)
    prompt = PROMPT.read_text(encoding="utf-8").replace("{context}", ctx.render()).replace("{today}", today)
    res = await llm.generate(MODEL_LITE, prompt, ReflectOut, purpose="reflection", reasoning="low", max_tokens=300,
                             priority_class="P3")
    out: ReflectOut = res.data
    ms = MemoryStore(agent_id, store, llm, on_event)
    for i, text in enumerate(out.reflections[:3]):
        await ms.add(MemoryEntry(mid=f"refl-{t}-{agent_id}-{i}", agent_id=agent_id, t=t, kind="reflection",
                                 text=text, importance=out.importance, source={"channel": "reflection"},
                                 entities=[], event_refs=[]))
    applied = []
    for u in out.belief_updates:
        if not u.subject.startswith(("product:", "brand:", "category:")):
            continue
        prev = await ms.beliefs([u.subject])
        if not prev:
            continue                                   # reflection never invents awareness
        await ms.update_belief(u.subject, {"attitude": prev[0].attitude + u.attitude_delta, "t": t},
                               cause_event_id=f"reflection-{t}")
        applied.append(u.model_dump())
    pruned = await ms.prune(KEEP, now_t=t)
    return {"text": " ".join(out.reflections[:3]), "belief_updates": applied, "pruned_count": pruned}, res.usage.cost_usd
