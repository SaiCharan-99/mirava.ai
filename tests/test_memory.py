"""Memory isolation (M-07), retrieval (M-03), beliefs (M-04), pruning (M-05) and context assembly (M-06)."""

import random

import pytest

from mind.context import build, count_tokens
from mind.memory import MemoryStore
from shared.llm import FakeGemini
from shared.schemas.memory import MemoryEntry
from shared.store import MemoryStoreBackend

MARKER = "Zubin"
A, B = 7, 42
FILLER = ["Took the metro to work, it was packed.", "Had filter coffee near the market.",
          "My phone battery died by evening.", "Watched a cricket match with friends.",
          "Paid the electricity bill.", "Rain flooded 100 Feet Road again.", "Cooked rajma for dinner."]


def mem(aid: int, i: int, text: str, t: int = 0, importance: int = 4) -> MemoryEntry:
    """A small memory entry."""
    return MemoryEntry(mid=f"m{aid}-{i}", agent_id=aid, t=t, kind="observation", text=text, importance=importance,
                       source={"channel": "life"}, entities=[], event_refs=[])


def seed_profile(store: MemoryStoreBackend, aid: int, name: str) -> None:
    """Minimal agents/{id} doc with a persona card."""
    store.set("agents", str(aid), {"agent_id": aid, "profile": {"name": name, "persona_card": f"I am {name}, 30, "
                                   "a designer in Indiranagar. I like coffee and cricket."}})


@pytest.fixture
async def world() -> tuple[MemoryStoreBackend, FakeGemini]:
    """Two agents; A holds a private marker fact."""
    store, llm = MemoryStoreBackend(), FakeGemini()
    seed_profile(store, A, "Meera")
    seed_profile(store, B, "Arjun")
    ma, mb = MemoryStore(A, store, llm), MemoryStore(B, store, llm)
    for i, txt in enumerate(FILLER * 5):
        await ma.add(mem(A, i, txt, t=i * 30))
        await mb.add(mem(B, i, txt, t=i * 30))
    await ma.add(mem(A, 999, f"My cousin is named {MARKER}; he is moving to Pune next month.", t=600, importance=7))
    return store, llm


async def test_cannot_touch_other_agents_memory(world: tuple[MemoryStoreBackend, FakeGemini]) -> None:
    store, llm = world
    with pytest.raises(PermissionError):
        await MemoryStore(B, store, llm).add(mem(A, 1, "sneaky"))


async def test_retrieval_finds_planted_memory_and_never_other_agent(world: tuple[MemoryStoreBackend, FakeGemini]) -> None:
    store, llm = world
    top = await MemoryStore(A, store, llm).retrieve(f"My cousin is named {MARKER}; he is moving to Pune next month.")
    assert len(top) <= 6 and any(MARKER in m.text for m in top)
    assert all(m.agent_id == A for m in top)
    other = await MemoryStore(B, store, llm).retrieve(f"cousin {MARKER} Pune")
    assert all(m.agent_id == B for m in other) and not any(MARKER in m.text for m in other)


async def test_marker_never_enters_other_agents_context(world: tuple[MemoryStoreBackend, FakeGemini]) -> None:
    store, llm = world
    rng = random.Random(3)
    queries = [f"talking with Meera about {w}" for w in ("family", "cousin", MARKER, "Pune", "moving", "coffee")]
    for _ in range(200):
        ctx = await build(B, "prep", rng.choice(queries), stimulus="Meera says hi.", store=store, llm=llm)
        assert MARKER not in ctx.model_dump_json()
        assert ctx.agent_id == B and all(m.agent_id == B for m in ctx.memories)
    own = await build(A, "prep", f"cousin {MARKER} moving to Pune", store=store, llm=llm)
    assert any(MARKER in m.text for m in own.memories)


async def test_context_under_900_tokens(world: tuple[MemoryStoreBackend, FakeGemini]) -> None:
    store, llm = world
    ctx = await build(A, "thought", "coffee", stimulus="x " * 2000, store=store, llm=llm)
    assert count_tokens(ctx.render()) <= 900
    assert "Meera" in ctx.persona_card


async def test_belief_first_heard_immutable(world: tuple[MemoryStoreBackend, FakeGemini]) -> None:
    store, llm = world
    ms = MemoryStore(A, store, llm)
    b1 = await ms.update_belief("product:nova-x1", {"awareness": "heard", "attitude": 0.3,
                                                    "first_heard": {"channel": "hoarding", "t": 10, "ref": "e1"}}, "e1")
    b2 = await ms.update_belief("product:nova-x1", {"attitude": 0.5, "reasons_for": ["camera"],
                                                    "first_heard": {"channel": "friend", "t": 99, "ref": "e2"}}, "e2")
    assert b1.first_heard == b2.first_heard == {"channel": "hoarding", "t": 10, "ref": "e1"}
    assert b2.attitude == 0.5 and b2.reasons_for == ["camera"]
    assert [b.subject for b in await ms.beliefs()] == ["product:nova-x1"]
    assert await MemoryStore(B, store, llm).beliefs() == []


async def test_prune_keeps_top(world: tuple[MemoryStoreBackend, FakeGemini]) -> None:
    store, llm = world
    ms = MemoryStore(A, store, llm)
    n0 = len(store.list(f"agents/{A}/memories"))
    removed = await ms.prune(keep=10)
    assert removed == n0 - 10 and len(store.list(f"agents/{A}/memories")) == 10
    assert any(MARKER in m["text"] for m in store.list(f"agents/{A}/memories"))  # most important survives
    assert len(store.list(f"agents/{B}/memories")) == 35
