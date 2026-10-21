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


def _conv_events(db):  # noqa: F811
    import json as _j

    from tests.test_insights import _ev

    evs = [_ev("conversation", 2900, 3, {"kind": "social", "place_id": "", "product_mentions": ["pulse-5"],
                                         "topics": ["battery"], "n_messages": 2}, other_id=4, session_id="s-1"),
           _ev("message", 2900, 3, {"seq": 0, "speaker": 3, "listener": 4, "text": "Seen the Pulse 5 hoarding?",
                                    "conv_kind": "social"}, other_id=4, session_id="s-1"),
           _ev("message", 2901, 4, {"seq": 1, "speaker": 4, "listener": 3, "text": "Yes, two-day battery.",
                                    "conv_kind": "social"}, other_id=3, session_id="s-1", seq=1),
           _ev("share_plan", 2899, 3, {"withheld_count": 1}, session_id="s-1"),
           _ev("debrief", 2902, 3, {"belief_deltas": [{"subject": "product:pulse-5", "attitude_delta": 0.2}]},
               session_id="s-1"),
           _ev("conversation", 2000, 4, {"kind": "social", "product_mentions": ["pulse-5"], "n_messages": 2},
               other_id=9, session_id="s-0"),
           _ev("wom", 2950, 7, {"teller": 4, "product_id": "pulse-5"}, other_id=4, product_id="pulse-5")]
    db.insert("events", [{**e, "payload": _j.dumps(e["payload"])} for e in evs])


def test_conversation_list_detail_and_spread(client, db):  # noqa: F811
    c, store = client
    _conv_events(db)
    store.set("conversations", "s-1", {"session_id": "s-1", "participants": [3, 4], "t": 2900,
                                       "conversation": {"kind": "social", "product_mentions": ["pulse-5", "old-x"]},
                                       "messages": [{"seq": 0, "speaker": 3, "listener": 4, "text": "Seen it?"}],
                                       "private": {"3": {"share_plan": {"opening": "Hi", "points_to_share": ["hoarding"],
                                                                        "candidates": [{"text": "hoarding", "tag": "opinion"},
                                                                                       {"text": "can't afford it", "tag": "sensitive"}],
                                                                        "withheld_count": 1},
                                                         "debrief": {"summary": "Battery sounds good", "importance": 6}}}})
    lst = c.get("/api/insights/conversations/list").json()
    row = next(r for r in lst["rows"] if r["session_id"] == "s-1")
    assert row["first_line"] == "Seen the Pulse 5 hoarding?" and row["products"][0]["name"] == "Pulse 5"
    assert row["sentiment"] == "positive"
    assert [r["session_id"] for r in c.get("/api/insights/conversations/list", params={"q": "two-day"}).json()["rows"]] == ["s-1"]
    assert c.get("/api/insights/conversations/list", params={"kind": "store"}).json()["rows"] == []
    d = c.get("/api/insights/conversations/s-1").json()
    a = next(p for p in d["people"] if p["agent_id"] == 3)
    assert a["plan"]["kept"] == ["can't afford it"] and a["plan"]["private"] and a["memory"]["importance"] == 6
    assert [p["id"] for p in d["products"]] == ["pulse-5"]                       # archived product dropped
    assert [x["agent_id"] for x in d["spread"]["chain"]] == [9, 4, 3]
    k = c.get("/api/insights/conversations").json()
    assert k["errors"] == [] and k["kpis"][3][1].endswith("people") and int(k["kpis"][3][1].split()[0]) >= 1


def test_interview_embedding_outage_and_provider_error(client, monkeypatch):
    from agents.interviewer import InterviewOut
    from shared.llm import FakeGemini, LLMError, LLMResult

    class WithoutEmbeddings(FakeGemini):
        async def embed(self, *args, **kwargs):
            raise LLMError("embedding unavailable")

        async def generate(self, *args, **kwargs):
            return LLMResult(data=InterviewOut(answer="I would want to know more before deciding."))

    c, _ = client
    monkeypatch.setattr(ins, "get_llm", lambda: WithoutEmbeddings())
    r = c.post("/api/insights/interview", json={"agent_id": 0, "question": "What matters in a new phone?"})
    assert r.status_code == 200 and r.json()["answer"]

    class Unavailable(WithoutEmbeddings):
        async def generate(self, *args, **kwargs):
            raise LLMError("secret provider diagnostics")

    monkeypatch.setattr(ins, "get_llm", lambda: Unavailable())
    r = c.post("/api/insights/interview", json={"agent_id": 0, "question": "What matters in a new phone?"})
    assert r.status_code == 200 and "secret" not in r.text and r.json()["fallback"] and "recall" in r.json()["answer"]


def test_interview_never_500_old_history_and_crashes(client, monkeypatch):
    import agents.interviewer as iv
    from agents.interviewer import InterviewOut
    from shared.llm import FakeGemini, LLMResult

    class Ok(FakeGemini):
        async def generate(self, *args, **kwargs):
            return LLMResult(data=InterviewOut(answer="Battery life matters most to me."))

    c, store = client
    store.set("insight_sessions", "iv-3", {"agent_id": 3, "turns": [{"q": "old"}, "junk", {"role": "me"}]})
    monkeypatch.setattr(ins, "get_llm", lambda: Ok())
    r = c.post("/api/insights/interview", json={"agent_id": 3, "question": "What matters?"})
    assert r.status_code == 200 and r.json()["answer"].startswith("Battery")

    async def boom(*a, **k):
        raise KeyError("persona")

    monkeypatch.setattr(iv, "build", boom)
    r = c.post("/api/insights/interview", json={"agent_id": 3, "question": "What matters?"})
    assert r.status_code == 200 and r.json()["fallback"]


def test_interview_recall_timeout_uses_recent(monkeypatch):
    import agents.interviewer as iv
    from shared.store import MemoryStoreBackend

    st = MemoryStoreBackend()
    st.set("agents/7/memories", "m1", {"mid": "m1", "agent_id": 7, "t": 5, "kind": "observation", "text": "Saw a hoarding",
                                       "importance": 3, "source": {}, "entities": [], "event_refs": []})

    async def slow(self, *a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(iv.MemoryStore, "retrieve", slow)
    monkeypatch.setattr(iv, "RETRIEVE_TIMEOUT_S", 0.05)
    mems = asyncio.run(iv._recall(7, "q", st, None))  # type: ignore[arg-type]
    assert [m.mid for m in mems] == ["m1"]
