"""API endpoints over an in-memory store (engine unreachable → Firestore fallbacks)."""

import pytest
from fastapi.testclient import TestClient

import api.main as m
from engine.events import NullSink
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    store = MemoryStoreBackend()
    tmp = tmp_path_factory.mktemp("g")
    import asyncio

    asyncio.run(run_genesis(1000, 4271, store=store, files=LocalFiles(str(tmp)), sink=NullSink(), llm=None,
                            settings=Settings(gcs_bucket_worlds="w")))
    m.store = lambda: store  # type: ignore[assignment]
    m._engine_get = lambda path: None  # type: ignore[assignment]
    m._cache.clear()
    return TestClient(m.app), store


def test_healthz_both_paths(client):
    c, _ = client
    for path in ("/healthz", "/api/healthz"):
        r = c.get(path)
        assert r.status_code == 200 and r.json()["ok"] is True


def test_world_state_and_stats(client):
    c, _ = client
    st = c.get("/api/world/state").json()
    assert st["label"] == "Day 1 · Mon 00:00" and st["scale"]["sim_min_per_real_s"] > 0
    counts = c.get("/api/world/stats").json()["counts"]
    assert counts["agents"] == 1000 and counts["relationships"] > 5000


def test_agents_filters_phone_age(client):
    c, _ = client
    allr = c.get("/api/agents", params={"page_size": 1000}).json()
    assert allr["total"] == 1000
    old = c.get("/api/agents", params={"phone_age_gt": 5, "page_size": 1000}).json()
    assert old["total"] == allr["phone_old_count"] and 150 <= old["total"] <= 200
    young = c.get("/api/agents", params={"age": "18-24"}).json()
    assert all(18 <= r["age"] <= 24 for r in young["rows"])


def test_agent_detail_and_watchlist(client):
    c, _ = client
    d = c.get("/api/agents/0").json()
    assert d["profile"]["agent_id"] == 0 and d["relationships"] and d["relationships"][0]["other"]["name"]
    assert "age_years" in d["profile"]["possessions"]["phone"] and d["profile"]["household_size"] >= 1
    assert c.put("/api/watchlist", json={"agent_ids": [3, 1, 3]}).json() == {"agent_ids": [1, 3]}
    assert c.get("/api/agents", params={"watched": 1}).json()["total"] == 2


def test_conversation_only_shows_own_private_parts(client):
    c, store = client
    store.set("conversations", "s1", {"session_id": "s1", "participants": [1, 2], "t": 500,
                                      "conversation": {"session_id": "s1", "n_messages": 2},
                                      "messages": [{"seq": 0, "speaker": 1, "listener": 2, "text": "Hi!", "t": 500}],
                                      "private": {"1": {"share_plan": {"opening": "Hi!", "secret": "A-only"},
                                                        "debrief": {"reaction": "A felt fine"}},
                                                  "2": {"share_plan": {"opening": "Hey", "secret": "B-only"},
                                                        "debrief": {"reaction": "B felt odd"}}}})
    store.set("agents/1/conversations", "s1", {"session_id": "s1", "with": 2, "t": 500, "n_messages": 2})
    r = c.get("/api/conversations/s1", params={"as_agent": 1}).json()
    body = str(r)
    assert "A-only" in body and "A felt fine" in body and "B-only" not in body and "B felt odd" not in body
    assert r["messages"][0]["text"] == "Hi!"
    assert c.get("/api/conversations/s1", params={"as_agent": 3}).status_code == 404
    lst = c.get("/api/agents/1/conversations").json()
    assert lst[0]["session_id"] == "s1" and lst[0]["with_name"]


def test_memories_and_thoughts_endpoints(client):
    c, store = client
    store.set("agents/5/memories", "x", {"mid": "x", "agent_id": 5, "t": 9, "kind": "observation", "text": "Rainy day",
                                         "importance": 3, "source": {}, "entities": [], "event_refs": [],
                                         "embedding": [0.1] * 768})
    mems = c.get("/api/agents/5/memories", params={"q": "rain"}).json()
    assert any(m["mid"] == "x" for m in mems) and all("embedding" not in m for m in mems)
    store.set("agents/5/thoughts", "e1", {"t": 10, "text": "hmm", "trigger": {"channel": "reflection"}})
    assert c.get("/api/agents/5/thoughts").json()[0]["text"] == "hmm"
    assert c.get("/api/world/highlights", params={"day": 99}).status_code == 404
