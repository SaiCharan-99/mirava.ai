"""Every Insights endpoint on a seeded local world (Phases B–C): 200, expected keys, archived products never shown."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.insights as ins
import api.main as m
import api.products as prods
from engine.events import NullSink
from insights.tools import DuckRunner
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend
from tests.test_insights import db  # noqa: F401 — shared DuckDB fixture (product pulse-5, 40 agents)


@pytest.fixture(scope="module")
def client(db, tmp_path_factory):  # noqa: F811
    store = MemoryStoreBackend()
    asyncio.run(run_genesis(150, 99, store=store, files=LocalFiles(str(tmp_path_factory.mktemp("g"))), sink=NullSink(),
                            llm=None, settings=Settings(gcs_bucket_worlds="w")))
    store.set("products", "pulse-5", {"product_id": "pulse-5", "name": "Pulse 5", "status": "live", "price_inr": 19999,
                                      "launched_at_t": 1440, "color": "#22c55e"})
    store.set("products", "old-x", {"product_id": "old-x", "name": "Old X", "status": "archived", "price_inr": 9999,
                                    "launched_at_t": 100, "color": "#f97316"})
    store.set("products", "draft-y", {"product_id": "draft-y", "name": "Draft Y", "status": "draft", "price_inr": 1,
                                      "color": "#8b5cf6"})
    r = DuckRunner(db)
    mp = pytest.MonkeyPatch()
    mp.setattr(ins, "store", lambda: store)
    mp.setattr(ins, "runner", lambda: r)
    mp.setattr(ins, "_now_t", lambda: 3000)
    mp.setattr(m, "store", lambda: store)
    mp.setattr(m, "_engine_get", lambda path: None)
    mp.setattr(prods, "store", lambda: store)
    m._cache.clear()
    yield TestClient(m.app), store
    mp.undo()


def test_overview_cumulative_and_active_only(client):
    c, _ = client
    d = c.get("/api/insights/overview").json()
    assert d["funnel"]["cols"] == ["Pulse 5"] and "Old X" not in str(d)
    counts = [row[1]["n"] for row in d["funnel"]["rows"]]
    assert counts == sorted(counts, reverse=True) and counts[0] >= 40 and counts[2] == 20


@pytest.mark.parametrize("path,keys", [
    ("/api/insights/sources", {"labels", "stacks", "paths", "note"}),
    ("/api/insights/hoardings", {"kpis", "rows", "heat", "themes"}),
    ("/api/insights/segments", {"products", "heat", "lifestyles"}),
    ("/api/insights/conversations", {"topics", "gap", "reviewers", "threads", "errors"}),
])
def test_every_dashboard_endpoint(client, path, keys):
    c, _ = client
    r = c.get(path)
    assert r.status_code == 200 and keys <= set(r.json())
    assert "old-x" not in r.text and "Old X" not in r.text
    if path.endswith("conversations"):
        assert r.json()["errors"] == []


def test_products_list_hides_archived(client):
    c, _ = client
    ids = [p["product_id"] for p in c.get("/api/products").json()]
    assert "old-x" not in ids and {"pulse-5", "draft-y"} <= set(ids)
    assert [p["product_id"] for p in c.get("/api/products", params={"active": 1}).json()] == ["pulse-5"]


def test_ask_prompt_has_only_active_products(client):
    c, _ = client
    with c.stream("POST", "/api/insights/ask", json={"question": "Who is likely to buy Pulse 5, by segment?"}) as r:
        body = "".join(r.iter_text())
    assert r.headers["cache-control"] == "no-cache" and body.count('"answer"') == 1
    assert "Old X" not in body and "old-x" not in body


def test_interview_agents_list(client):
    c, _ = client
    rows = c.get("/api/insights/interview/agents").json()
    assert 0 < len(rows) <= 20 and {"agent_id", "name", "age", "occupation", "phone"} <= set(rows[0])
    some = rows[0]["name"].split()[0]
    assert all(some.lower() in (r["name"] + r["occupation"]).lower()
               for r in c.get("/api/insights/interview/agents", params={"q": some}).json())
    assert c.get("/api/insights/interview/agents", params={"agent": 140}).json()[0]["agent_id"] == 140


def test_archive_endpoint(client):
    c, store = client
    assert c.post("/api/products/draft-y/archive").json()["status"] == "archived"
    assert "draft-y" not in [p["product_id"] for p in c.get("/api/products").json()]
