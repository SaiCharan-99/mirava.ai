"""Per-agent MemoryStore (M-07: an instance can only touch its own agent's memories and beliefs)."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from shared.llm import LLMClient, LLMError
from shared.schemas.memory import Belief, MemoryEntry
from shared.store import DocStore

log = logging.getLogger(__name__)

W_RECENCY, W_IMPORTANCE, W_RELEVANCE = 0.35, 0.25, 0.40
CANDIDATES = 24                      # vector pre-selection before the full re-rank
_EMB_LRU: OrderedDict[str, list[float]] = OrderedDict()
_EMB_LRU_MAX = 20_000
_BACKFILLED: set[tuple[int, int]] = set()   # (id(store), agent_id) whose old memories have embeddings

EventHook = Callable[[str, dict[str, Any]], None]


def recency(t_mem: int, now_t: int) -> float:
    """0.995 ^ sim hours since the memory."""
    return 0.995 ** (max(0, now_t - t_mem) / 60)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity (inputs need not be normalised)."""
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


async def embed_cached(llm: LLMClient, texts: list[str]) -> list[list[float]]:
    """Embed texts through the in-RAM LRU (hot agents and repeated queries cost nothing)."""
    missing = [t for t in dict.fromkeys(texts) if t not in _EMB_LRU]
    if missing:
        if time.monotonic() < getattr(llm, "_memory_embed_retry_at", 0):
            raise LLMError("Embedding temporarily unavailable")
        try:
            vectors = await llm.embed(missing, 768)
        except Exception:
            setattr(llm, "_memory_embed_retry_at", time.monotonic() + 60)  # noqa: B010 — duck-typed backoff flag
            raise
        for t, v in zip(missing, vectors, strict=True):
            _EMB_LRU[t] = v
    out = []
    for t in texts:
        _EMB_LRU.move_to_end(t)
        out.append(_EMB_LRU[t])
    while len(_EMB_LRU) > _EMB_LRU_MAX:
        _EMB_LRU.popitem(last=False)
    return out


def _default_belief(agent_id: int, subject: str, t: int) -> Belief:
    """An unaware belief for a new subject."""
    return Belief(agent_id=agent_id, subject=subject, awareness="unaware", attitude=0.0, confidence=0.0,
                  reasons_for=[], reasons_against=[], open_questions=[], first_heard=None, sources_seen={},
                  stage="unaware", updated_t=t)


class MemoryStore:
    """Memories (`agents/{id}/memories`) and beliefs (`agents/{id}/beliefs`) of ONE agent."""

    def __init__(self, agent_id: int, store: DocStore, llm: LLMClient | None = None,
                 on_event: EventHook | None = None) -> None:
        self.agent_id = agent_id
        self._store = store
        self._llm = llm
        self._on_event = on_event
        self._col = f"agents/{agent_id}/memories"
        self._bcol = f"agents/{agent_id}/beliefs"

    def _own(self, entry: MemoryEntry) -> None:
        if entry.agent_id != self.agent_id:
            raise PermissionError(f"MemoryStore({self.agent_id}) cannot write agent {entry.agent_id}'s memory")

    def _rows(self) -> list[MemoryEntry]:
        """All of this agent's memories (filtered again by agent_id as a second guard)."""
        rows = [MemoryEntry.model_validate(r) for r in self._store.list(self._col, limit=2000)]
        return [r for r in rows if r.agent_id == self.agent_id]

    async def add(self, entry: MemoryEntry) -> None:
        """Store one memory of this agent, embedded when an LLM client is available."""
        self._own(entry)
        if entry.embedding is None and self._llm is not None:
            try:
                vec = await asyncio.wait_for(embed_cached(self._llm, [entry.text]), 5)
                entry = entry.model_copy(update={"embedding": vec[0]})
            except Exception:  # embeddings are an index; never lose the underlying memory
                log.warning("Embedding unavailable; storing memory without a vector", exc_info=True)
        self._store.set(self._col, entry.mid, entry.model_dump(exclude_none=True))

    def add_many(self, entries: list[MemoryEntry]) -> None:
        """Batch-store memories of this agent (genesis seeds; embedded lazily on first retrieval)."""
        for e in entries:
            self._own(e)
        self._store.set_many(self._col, {e.mid: e.model_dump(exclude_none=True) for e in entries})

    async def _backfill(self) -> None:
        """Embed memories written without an embedding (genesis seeds), once per agent per process."""
        key = (id(self._store), self.agent_id)
        if key in _BACKFILLED or self._llm is None:
            return
        todo = [r for r in self._rows() if r.embedding is None]
        if todo:
            vecs = await embed_cached(self._llm, [r.text for r in todo])
            self._store.set_many(self._col, {r.mid: {**r.model_dump(exclude_none=True), "embedding": v}
                                             for r, v in zip(todo, vecs, strict=True)})
        _BACKFILLED.add(key)

    async def retrieve(self, query: str, k: int = 6, kinds: list[str] | None = None,
                       now_t: int | None = None) -> list[MemoryEntry]:
        """Top-k by 0.35·recency + 0.25·importance + 0.40·relevance, searched only within this agent."""
        if k <= 0:
            return []
        if self._llm is None:
            cands = self._rows()
            qv: list[float] | None = None
        else:
            try:
                # Query embedding is enough; do not backfill an agent's entire history on an interactive read.
                qv = (await asyncio.wait_for(embed_cached(self._llm, [query]), 5))[0]
                docs = self._store.nearest(self._col, "embedding", qv, CANDIDATES * (3 if kinds else 1),
                                           "agent_id", self.agent_id)
                cands = [MemoryEntry.model_validate(d) for d in docs]
                if not cands:
                    cands = self._rows()
            except Exception:
                log.warning("Vector retrieval unavailable; using this agent's stored memories", exc_info=True)
                qv, cands = None, self._rows()
        cands = [c for c in cands if c.agent_id == self.agent_id and (kinds is None or c.kind in kinds)]
        if not cands:
            return []
        now = now_t if now_t is not None else max(c.t for c in cands)

        def score(m: MemoryEntry) -> float:
            words = set(re.findall(r"\w+", query.lower()))
            lexical = len(words & set(re.findall(r"\w+", m.text.lower()))) / max(1, len(words))
            rel = cosine(qv, m.embedding) if qv is not None and m.embedding else lexical
            return W_RECENCY * recency(m.t, now) + W_IMPORTANCE * m.importance / 10 + W_RELEVANCE * rel

        cands.sort(key=lambda m: (-score(m), -m.t, m.mid))
        return cands[:k]

    async def beliefs(self, subjects: list[str] | None = None) -> list[Belief]:
        """Current beliefs, optionally for given subjects."""
        rows = [Belief.model_validate(r) for r in self._store.list(self._bcol)]
        return sorted([b for b in rows if b.agent_id == self.agent_id and (subjects is None or b.subject in subjects)],
                      key=lambda b: b.subject)

    async def update_belief(self, subject: str, delta: dict, cause_event_id: str) -> Belief:
        """Apply a partial update; `first_heard` is set once and never changes. Emits `belief_change`."""
        doc_id = subject.replace("/", "_")
        raw = self._store.get(self._bcol, doc_id)
        before = Belief.model_validate(raw) if raw else _default_belief(self.agent_id, subject, int(delta.get("t", 0)))
        upd = {k: v for k, v in delta.items() if k in Belief.model_fields and k not in ("agent_id", "subject")}
        if before.first_heard is not None:
            upd.pop("first_heard", None)
        if "sources_seen" in upd:
            seen = dict(before.sources_seen)
            for ch, n in upd["sources_seen"].items():
                seen[ch] = seen.get(ch, 0) + int(n)
            upd["sources_seen"] = seen
        if "attitude" in upd:
            upd["attitude"] = max(-1.0, min(1.0, float(upd["attitude"])))
        if "t" in delta:
            upd["updated_t"] = int(delta["t"])
        after = before.model_copy(update=upd)
        after = Belief.model_validate(after.model_dump())
        self._store.set(self._bcol, doc_id, after.model_dump())
        if self._on_event is not None:
            keys = ("awareness", "attitude", "confidence", "stage")
            self._on_event("belief_change", {"subject": subject, "before": {k: getattr(before, k) for k in keys},
                                             "after": {k: getattr(after, k) for k in keys},
                                             "cause_event_id": cause_event_id})
        return after

    async def prune(self, keep: int = 300, now_t: int | None = None) -> int:
        """Keep the top `keep` memories by importance × recency; the raw log (L0) keeps everything."""
        rows = self._rows()
        if len(rows) <= keep:
            return 0
        now = now_t if now_t is not None else max(r.t for r in rows)
        rows.sort(key=lambda r: (-(r.importance * recency(r.t, now)), -r.t, r.mid))
        for r in rows[keep:]:
            self._store.delete(self._col, r.mid)
        return len(rows) - keep
