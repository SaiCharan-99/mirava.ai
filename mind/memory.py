"""Per-agent MemoryStore (M-07: an instance can only touch its own agent). Phase 2: write path + simple recall."""

from __future__ import annotations

from shared.schemas.memory import Belief, MemoryEntry
from shared.store import DocStore


class MemoryStore:
    """Memories of ONE agent in `agents/{id}/memories`; retrieval and beliefs grow in phase 3."""

    def __init__(self, agent_id: int, store: DocStore) -> None:
        self.agent_id = agent_id
        self._store = store
        self._col = f"agents/{agent_id}/memories"

    def _own(self, entry: MemoryEntry) -> None:
        if entry.agent_id != self.agent_id:
            raise PermissionError(f"MemoryStore({self.agent_id}) cannot write agent {entry.agent_id}'s memory")

    async def add(self, entry: MemoryEntry) -> None:
        """Store one memory of this agent."""
        self._own(entry)
        self._store.set(self._col, entry.mid, entry.model_dump(exclude={"embedding"}))

    def add_many(self, entries: list[MemoryEntry]) -> None:
        """Batch-store memories of this agent (genesis seeds)."""
        for e in entries:
            self._own(e)
        self._store.set_many(self._col, {e.mid: e.model_dump(exclude={"embedding"}) for e in entries})

    async def retrieve(self, query: str, k: int = 6, kinds: list[str] | None = None) -> list[MemoryEntry]:
        """Most important recent memories (keyword boost); vector recall arrives in phase 3."""
        rows = [MemoryEntry.model_validate(r) for r in self._store.list(self._col, limit=500)]
        rows = [r for r in rows if r.agent_id == self.agent_id and (kinds is None or r.kind in kinds)]
        words = {w for w in query.lower().split() if len(w) > 3}
        rows.sort(key=lambda r: (-(r.importance + 3 * len(words & set(r.text.lower().split()))), -r.t))
        return rows[:k]

    async def beliefs(self, subjects: list[str] | None = None) -> list[Belief]:
        """Current beliefs (none before products launch)."""
        rows = [Belief.model_validate(r) for r in self._store.list(f"agents/{self.agent_id}/beliefs")]
        return [b for b in rows if subjects is None or b.subject in subjects]
