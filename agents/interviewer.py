"""Interviewer (I-08): answers AS one agent, grounded only in that agent's own memory (recall filtered to the agent)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from media.screen import wrap
from mind.context import build
from mind.memory import MemoryStore
from shared.llm import LLMClient
from shared.models import MODEL_FLASH
from shared.store import DocStore

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "interview.md"


class InterviewOut(BaseModel):
    """In-character answer + which memories it used."""

    answer: str
    memories_used: list[str] = Field(default_factory=list, description="mid values of the memories you relied on")


async def interview(agent_id: int, question: str, *, store: DocStore, llm: LLMClient,
                    history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """One interview turn; `memories_used` is filtered to this agent's own retrieved memories."""
    ms = MemoryStore(agent_id, store, llm)
    mems = await ms.retrieve(question, k=8)
    ctx = await build(agent_id, "interview", question, store=store, llm=llm, k=0)
    lines = "\n".join(f"[{m.mid}] {m.text}" for m in mems) or "(no relevant memories)"
    hist = "\n".join(f"{h['role']}: {h['text']}" for h in (history or [])[-6:])
    prompt = (PROMPT.read_text(encoding="utf-8").replace("{persona}", ctx.render())
              .replace("{memories}", lines).replace("{history}", hist or "(start)")
              .replace("{question}", wrap(question, "question")))
    res = await asyncio.wait_for(llm.generate(MODEL_FLASH, prompt, InterviewOut, purpose="interview", reasoning="low", max_tokens=400,
                             priority_class="interactive"), 35)
    own = {m.mid: m for m in mems}
    used = [mid for mid in res.data.memories_used if mid in own] or [m.mid for m in mems[:2]]
    return {"answer": res.data.answer.strip()[:1200], "memories_used": used,
            "memories": [{"mid": mid, "text": own[mid].text, "t": own[mid].t, "kind": own[mid].kind} for mid in used],
            "cost_usd": res.usage.cost_usd}
