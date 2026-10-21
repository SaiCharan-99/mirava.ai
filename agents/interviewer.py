"""Interviewer (I-08): answers AS one agent, grounded only in that agent's own memory (recall filtered to the agent)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from media.screen import wrap
from mind.context import build
from mind.memory import MemoryStore
from shared.llm import LLMClient
from shared.models import MODEL_FLASH
from shared.schemas.memory import MemoryEntry
from shared.store import DocStore

log = logging.getLogger(__name__)
PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "interview.md"
RETRIEVE_TIMEOUT_S = 8
CANT_RECALL = "Sorry, I can't quite recall right now. My head is a bit full today. Could you ask me again in a moment?"


class InterviewOut(BaseModel):
    """In-character answer + which memories it used."""

    answer: str
    memories_used: list[str] = Field(default_factory=list, description="mid values of the memories you relied on")


def recent_memories(agent_id: int, store: DocStore, k: int = 8) -> list[MemoryEntry]:
    """This agent's most recent memories (fallback when vector search is slow or down)."""
    out: list[MemoryEntry] = []
    for r in store.list(f"agents/{agent_id}/memories", limit=2000):
        try:
            m = MemoryEntry.model_validate(r)
        except Exception:  # an old or partial row must never break an interview
            continue
        if m.agent_id == agent_id:
            out.append(m)
    out.sort(key=lambda m: (-m.t, m.mid))
    return out[:k]


async def _recall(agent_id: int, question: str, store: DocStore, llm: LLMClient) -> list[MemoryEntry]:
    """Relevance recall with a timeout; falls back to the most recent memories (query embedding only, no backfill)."""
    try:
        return await asyncio.wait_for(MemoryStore(agent_id, store, llm).retrieve(question, k=8), RETRIEVE_TIMEOUT_S)
    except Exception:
        log.warning("interview recall failed for agent %s; using recent memories", agent_id, exc_info=True)
        try:
            return recent_memories(agent_id, store)
        except Exception:
            log.exception("interview: could not read memories for agent %s", agent_id)
            return []


def history_lines(history: list[dict[str, Any]] | None) -> str:
    """Last 6 turns as 'role: text', tolerating old rows with missing keys."""
    rows = []
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and (h.get("text") or h.get("answer") or h.get("question")):
            rows.append(f"{h.get('role') or 'me'}: {h.get('text') or h.get('answer') or h.get('question')}")
    return "\n".join(rows)


def fallback(reason: str = "") -> dict[str, Any]:
    """In-character 'can't recall' reply used whenever the turn cannot be completed."""
    return {"answer": CANT_RECALL, "memories_used": [], "memories": [], "cost_usd": 0.0, "fallback": True,
            "fallback_reason": reason}


async def interview(agent_id: int, question: str, *, store: DocStore, llm: LLMClient,
                    history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One interview turn; `memories_used` is filtered to this agent's own retrieved memories."""
    mems = await _recall(agent_id, question, store, llm)
    ctx = await build(agent_id, "interview", question, store=store, llm=llm, k=0)
    lines = "\n".join(f"[{m.mid}] {m.text}" for m in mems) or "(no relevant memories)"
    prompt = (PROMPT.read_text(encoding="utf-8").replace("{persona}", ctx.render())
              .replace("{memories}", lines).replace("{history}", history_lines(history) or "(start)")
              .replace("{question}", wrap(question, "question")))
    res = await asyncio.wait_for(llm.generate(MODEL_FLASH, prompt, InterviewOut, purpose="interview", reasoning="low",
                                              max_tokens=400, priority_class="interactive"), 35)
    own = {m.mid: m for m in mems}
    used = [mid for mid in res.data.memories_used if mid in own] or [m.mid for m in mems[:2]]
    return {"answer": (res.data.answer or "").strip()[:1200] or CANT_RECALL, "memories_used": used,
            "memories": [{"mid": mid, "text": own[mid].text, "t": own[mid].t, "kind": own[mid].kind} for mid in used],
            "cost_usd": res.usage.cost_usd}


async def safe_interview(agent_id: int, question: str, *, store: DocStore, llm: LLMClient,
                         history: list[dict[str, Any]] | None = None, timeout: float = 45) -> dict[str, Any]:
    """`interview` that never raises: any failure becomes the in-character fallback plus a logged error."""
    try:
        return await asyncio.wait_for(interview(agent_id, question, store=store, llm=llm, history=history), timeout)
    except Exception as exc:
        log.exception("insights interview failed for agent %s", agent_id)
        return fallback(type(exc).__name__)
