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
