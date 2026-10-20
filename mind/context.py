"""Context assembly for ONE agent (M-06): persona card + now + beliefs + memories + stimulus, ≤ 900 tokens."""

from __future__ import annotations

from pydantic import BaseModel

from mind.memory import MemoryStore
from shared.llm import LLMClient
from shared.schemas.memory import Belief, MemoryEntry
from shared.store import DocStore

MAX_TOKENS = 900
MAX_BELIEFS = 3


def count_tokens(text: str) -> int:
    """Cheap token estimate (≈4 characters per token)."""
    return (len(text) + 3) // 4


class AgentContext(BaseModel):
    """Everything a prompt may know about ONE agent."""

    agent_id: int
    persona_card: str
    now: str
    beliefs: list[Belief]
    memories: list[MemoryEntry]
    stimulus: str
    opinions: str = ""             # how THIS person sees the phones in play (from the opinion engine; own view only)

    def render(self) -> str:
        """Prompt block for this agent (wrap in delimiters at the call site)."""
        bel = "\n".join(f"- {b.subject}: {b.awareness}, attitude {b.attitude:+.1f}, stage {b.stage}"
                        + (f"; for: {', '.join(b.reasons_for[:3])}" if b.reasons_for else "")
                        + (f"; against: {', '.join(b.reasons_against[:3])}" if b.reasons_against else "")
                        for b in self.beliefs) or "- (none)"
        mem = "\n".join(f"- {m.text}" for m in self.memories) or "- (none)"
        opin = f"HOW I SEE THESE PHONES:\n{self.opinions}\n\n" if self.opinions else ""
        return (f"WHO I AM:\n{self.persona_card}\n\nNOW:\n{self.now}\n\nWHAT I BELIEVE:\n{bel}\n\n{opin}"
                f"WHAT I REMEMBER:\n{mem}\n\nWHAT IS HAPPENING:\n{self.stimulus}")


def _pick_beliefs(beliefs: list[Belief], text: str) -> list[Belief]:
    """Subjects mentioned in the query/stimulus first, then the most recently updated."""
    low = text.lower()

    def mentioned(b: Belief) -> bool:
        return b.subject.split(":", 1)[-1].replace("-", " ") in low.replace("-", " ")

    return sorted(beliefs, key=lambda b: (not mentioned(b), -b.updated_t, b.subject))[:MAX_BELIEFS]


async def build(agent_id: int, purpose: str, query: str, stimulus: str = "", *, store: DocStore,
                llm: LLMClient | None, now: str = "", now_t: int | None = None, k: int = 6,
                opinions: str = "") -> AgentContext:
    """Assemble the context of `agent_id` only; trims stimulus, then memories, to stay ≤ 900 tokens."""
    doc = store.get("agents", str(agent_id)) or {}
    card = (doc.get("profile") or {}).get("persona_card", "")
    ms = MemoryStore(agent_id, store, llm)
    mems = await ms.retrieve(query, k=k, now_t=now_t)
    beliefs = _pick_beliefs(await ms.beliefs(), f"{query} {stimulus}")
    ctx = AgentContext(agent_id=agent_id, persona_card=card, now=now or f"(purpose: {purpose})", beliefs=beliefs,
                       memories=mems, stimulus=stimulus, opinions=opinions)
    over = count_tokens(ctx.render()) - MAX_TOKENS
    if over > 0 and ctx.stimulus:
        keep = max(0, len(ctx.stimulus) - over * 4 - 8)
        ctx.stimulus = ctx.stimulus[:keep].rstrip() + " …"
    while count_tokens(ctx.render()) > MAX_TOKENS and ctx.memories:
        ctx.memories = ctx.memories[:-1]
    return ctx
