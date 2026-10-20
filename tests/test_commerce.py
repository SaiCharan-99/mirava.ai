"""Buying (S-01 … S-06, T-03): need, consideration, store inquiries, purchases — unit rules + a 3-day engine run (fakes)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.main as m
import api.products as ap
from commerce.consideration import Pair, next_stage
from commerce.need import affordability, phone_need
from commerce.purchase import Option, gate
from engine.events import NullSink
from engine.loop import Engine
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend

N = 400
DAYS = 3


# ---------------------------------------------------------------- unit rules

def test_need_from_phone_factors_and_life_event():
    new = {"bought_t": 0, "condition": "ok", "battery_health": 1.0, "satisfaction": 0.9}
    old = {"bought_t": 0, "condition": "ok", "battery_health": 0.6, "satisfaction": 0.4}
    t = 6 * 525600
    assert phone_need(new, 0, "Software engineer") < 0.2
    assert phone_need(old, t, "Software engineer") > phone_need(old, t // 3, "Software engineer")
    broken = {**new, "condition": "cracked"}
    assert phone_need(broken, 10, "Delivery partner", last_life_event_t=5) >= 0.5   # above the inquiry threshold
    assert phone_need({**new, "condition": "lost"}, 10, "Student") == 1.0


def test_affordability_methods():
    rich = {"savings_inr": 200000, "credit_card_limit_inr": 0, "emi_eligible": False, "monthly_income_inr": 90000}
    card = {"savings_inr": 0, "credit_card_limit_inr": 100000, "emi_eligible": False, "monthly_income_inr": 40000}
    emi = {"savings_inr": 0, "credit_card_limit_inr": 0, "emi_eligible": True, "monthly_income_inr": 40000}
    assert affordability(20000, rich)[1] == "cash"
    assert affordability(20000, card)[1] == "card"
    assert affordability(20000, emi)[1] == "emi"
    assert affordability(90000, {**emi, "monthly_income_inr": 10000})[1] is None


def test_state_machine_rules():
    p = Pair(stage="unaware", aware=True)
    assert next_stage(p, 0.2, set(), 0)[0] == "aware"
    p = Pair(stage="aware", aware=True, attitude=0.6, fit=0.5)
    assert next_stage(p, 0.2, set(), 0)[0] == "curious"
    p = Pair(stage="curious", aware=True, attitude=0.5, open_questions=["battery?"])
    assert next_stage(p, 0.2, set(), 0) is None                        # needs a feed session
    assert next_stage(p, 0.2, {"feed"}, 0)[0] == "researching"
    p = Pair(stage="researching", aware=True, attitude=0.6, fit=0.5, review=0.8)
    assert next_stage(p, 0.2, {"store_route"}, 0) is None              # need too low
    assert next_stage(p, 0.7, {"store_route"}, 0)[0] == "inquiring"
    assert next_stage(Pair(stage="aware", aware=True, attitude=-0.6), 0.9, set(), 0)[0] == "rejected"


def test_purchase_gate_needs_need_and_margin():
    a = Option("pulse-5", "Pulse 5", 20000, 0.8, "cash", 1.0)
    b = Option("baseline:mid", "mid", 22000, 0.5, "cash", 1.0)
    assert gate(0.3, [a, b], False)[0] == "not_buying"
    assert gate(0.3, [a, b], True)[0] == "buy"                          # a life event overrides low need
    assert gate(0.8, [a, b], False)[0] == "buy"
    assert gate(0.8, [a, Option("baseline:mid", "mid", 22000, 0.78, "cash", 1.0)], False)[0] == "postpone"
    assert gate(0.8, [Option("x", "x", 99999, 0.9, None, 0.1)], False)[0] == "postpone"


# ---------------------------------------------------------------- engine run

@pytest.fixture(scope="module")
def bought(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("commerce")
    s = Settings(world_agents=N, world_seed=7, checkpoint_every_sim_minutes=10**6, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp))
    store, files, sink = MemoryStoreBackend(), LocalFiles(str(tmp)), NullSink()
    asyncio.run(run_genesis(N, 7, store=store, files=files, sink=NullSink(), llm=None, settings=s))
    m.store = ap.store = lambda: store  # type: ignore[assignment]
    m._engine_get = lambda path: None  # type: ignore[assignment]
    ap._cache.clear()
    c = TestClient(m.app)
    pid = c.post("/api/products", json={
        "name": "Pulse 5", "brand": "Voltix", "category": "Smartphone", "price_inr": 18999,
        "launch_offer": "₹1,500 off on launch week",
        "features": ["6,000 mAh battery", "120Hz display", "50MP camera", "33W fast charging"],
        "claims": ["Two-day battery life."], "target_personas": ["Students and young workers", "Gamers on a budget"],
        "strategy": {"intensity": "high", "flight_days": 14}}).json()["product_id"]
    for kind, title, text in (("hoarding", "Hoarding", "TWO DAYS. ONE CHARGE."), ("reel", "Battery", "Game all night."),
                              ("store_display", "Display", "Try the Pulse 5 here")):
        c.post(f"/api/products/{pid}/creatives", json={"kind": kind, "title": title, "text": text})
    c.post(f"/api/products/{pid}/audience", json={})
    c.post(f"/api/products/{pid}/understand")
    c.post(f"/api/products/{pid}/plan")
    c.post(f"/api/products/{pid}/ready")

    async def run():
        e = Engine(s, store, files, sink)
        e.boot()
        ap._engine_command = lambda cmd: e.command(cmd)  # type: ignore[assignment]
        assert c.post(f"/api/products/{pid}/launch").json()["status"] == "live"
        for _ in range(DAYS * 1440):
            await e.tick()
        for _ in range(5):
            await asyncio.sleep(0.05)
        await e.bus.flush()
        return e

    e = asyncio.run(run())
    return e, sink, store, pid


def _ev(sink, kind):
    return [x for x in sink.events if x["kind"] == kind]


def test_store_inquiries_with_transcripts(bought):
    e, sink, store, pid = bought
    inq = [x for x in _ev(sink, "inquiry") if x["rendered"]]
    print("inquiries", len(inq), "purchases", len(_ev(sink, "purchase")), e.commerce.stats)
    assert len(inq) >= 5
    for x in inq:
        msgs = [y for y in _ev(sink, "message") if y["session_id"] == x["session_id"]]
        thoughts = [y for y in _ev(sink, "store_thought") if y["session_id"] == x["session_id"]]
        assert msgs and thoughts and all(y["private"] for y in thoughts)
        assert x["payload"]["topics"]
        per = {}
        for y in msgs:
            per[y["payload"]["speaker"]] = per.get(y["payload"]["speaker"], 0) + 1
        assert max(per.values()) <= 10
        doc = store.get("conversations", x["session_id"])
        assert doc and len(doc["messages"]) == len(msgs)
        assert str(x["agent_id"]) in doc["private"] and doc["private"][str(x["agent_id"])]["store_thoughts"]


def test_need_driven_purchase(bought):
    e, sink, _, pid = bought
    buys = _ev(sink, "purchase")
    assert len(buys) >= 1
    theta = 0.5
    for b in buys:
        assert b["payload"]["need"] >= theta or b["payload"]["life_event"]
        assert b["payload"]["method"] in ("cash", "card", "emi")
        ph = e.world.phones[b["agent_id"]]
        assert ph["bought_t"] == b["t"] and ph["condition"] == "ok"


def test_every_transition_has_a_cause(bought):
    _, sink, _, _ = bought
    ids = {x["event_id"] for x in sink.events}
    tr = _ev(sink, "consideration")
    assert tr
    for x in tr:
        c = x["payload"]["cause_event_id"]
        assert c and (c in ids or c.startswith("seed:")), x


def test_salesperson_never_sees_store_thoughts(bought):
    """Marker fact: store_thought texts never appear in a salesperson prompt (echo check through the transcript)."""
    from mind.decision import FakeDecision
    from shared.llm import FakeGemini
    from social.store_inquiry import Customer, Salesperson, run_inquiry

    e, _, store, pid = bought
    marker = "ZEBRA-MARKER-4417"
    prompts: list[tuple[str, str]] = []

    class Spy(FakeGemini):
        async def generate(self, model, prompt, schema=None, **kw):
            prompts.append((kw.get("purpose", ""), str(prompt)))
            res = await super().generate(model, prompt, schema, **kw)
            if kw.get("purpose") == "store_think":
                res.data.thought = f"My budget is secretly {marker}."
                res.data.withhold = [marker]
            return res

    cust = Customer(1, "Asha", "plain", "now", [f"agenda {marker}"])
    sales = Salesperson(2, "Ravi", "friendly", "ST-X", "Store X", pid, "Pulse 5", {"general": "facts"}, {pid: 3}, [])
    out = asyncio.run(run_inquiry("s1", cust, sales, 100, store=store, llm=Spy(), decider=FakeDecision()))
    sales_prompts = [p for purpose, p in prompts if purpose.startswith("salesperson")]
    assert sales_prompts and all(marker not in p for p in sales_prompts)
    assert any(ev["kind"] == "store_thought" and marker in ev["payload"]["thought"] for ev in out.events)


def test_all_views_run_on_duckdb(bought, tmp_path):
    """Every curated view compiles on the DuckDB twin and the funnel/purchase views match raw events."""
    from pathlib import Path

    from engine.events import DuckDBSink

    _, sink, _, pid = bought
    db = DuckDBSink(Settings(duckdb_path=str(tmp_path / "v.duckdb"))).db
    db.insert("events", sink.events)
    for v in sorted(Path("infra/bigquery/views").glob("*.sql")):
        db.con.execute(db.translate(v.read_text(encoding="utf-8"), "mirava"))
    buys = db.query("SELECT COUNT(*) AS n FROM v_purchases")[0]["n"]
    assert buys == len(_ev(sink, "purchase"))
    f = db.query("SELECT SUM(inquiries) AS i, SUM(purchases) AS p FROM v_funnel_daily WHERE product_id = @p", {"p": pid})
    assert f[0]["i"] == len([x for x in _ev(sink, "inquiry") if x["product_id"] == pid])
    fh = db.query("SELECT channel, COUNT(*) AS n FROM v_first_heard WHERE product_id = @p GROUP BY 1", {"p": pid})
    assert sum(r["n"] for r in fh) == db.query(
        "SELECT COUNT(DISTINCT agent_id) AS n FROM v_first_heard WHERE product_id = @p", {"p": pid})[0]["n"]
    assert db.query("SELECT COUNT(*) AS n FROM v_paths WHERE path LIKE '%store%'")[0]["n"] > 0
    for v in ("beliefs_latest", "beliefs_daily", "v_thoughts", "v_inquiries", "v_posts", "v_reviews"):
        db.query(f"SELECT * FROM {v} LIMIT 5")


def test_funnel_counts_live_products_only(bought):
    e, sink, store, pid = bought
    f = e.commerce.funnel()
    assert set(f) == {pid}
    row = f[pid]
    assert row["aware"] >= row["curious_plus"] >= row["purchased"] >= 0
    assert row["aware"] == sum(1 for k, p in e.commerce.pairs.items()
                               if k.endswith(f"|{pid}") and p.stage not in ("unaware", "rejected"))
    frame = e.stats_frame()
    assert frame["funnel"] == f and pid in frame["campaigns"] and frame["campaigns"][pid]["active"]


def test_prune_products_drops_deleted(bought):
    e, sink, store, pid = bought
    c = e.commerce
    from commerce.consideration import Pair

    c.pairs["1|demo-gone"] = Pair(stage="aware", aware=True)
    c.visits[1] = {"pid": "demo-gone", "day": 1}
    assert c.prune_products({pid}) >= 1
    assert "1|demo-gone" not in c.pairs and 1 not in c.visits
    assert any(k.endswith(f"|{pid}") for k in c.pairs)           # real product untouched


def test_inquiry_round_uses_two_calls_and_salesperson_never_sees_agenda(bought):
    """Phase 0.5: per round ONE salesperson call + ONE customer call (+ one debrief), no model 'decide' call."""
    from mind.decision import FakeDecision
    from shared.llm import FakeGemini
    from social.store_inquiry import Customer, Salesperson, run_inquiry

    e, _, store, pid = bought
    marker = "AGENDA-SECRET-9921"
    calls: list[str] = []
    seen: dict[str, list[str]] = {}

    class Spy(FakeGemini):
        async def generate(self, model, prompt, schema=None, **kw):
            calls.append(kw.get("purpose", ""))
            seen.setdefault(kw.get("purpose", ""), []).append(str(prompt))
            return await super().generate(model, prompt, schema, **kw)

    cust = Customer(1, "Asha", "plain", "now", [f"is the battery any good? {marker}"])
    sales = Salesperson(2, "Ravi", "friendly", "ST-X", "Store X", pid, "Pulse 5", {"general": "facts"}, {pid: 3}, [])
    out = asyncio.run(run_inquiry("s2", cust, sales, 100, store=store, llm=Spy(), decider=FakeDecision()))
    rounds = sum(1 for m in out.messages if m.speaker == 1)
    assert rounds >= 1
    assert calls.count("salesperson_reply") == calls.count("store_think") == rounds
    assert calls.count("inquiry_debrief") == 1
    assert set(calls) <= {"salesperson_reply", "store_think", "inquiry_debrief"}
    assert all(marker not in p for p in seen["salesperson_reply"])
    assert len(calls) <= 2 * rounds + 1


def test_word_of_mouth_flows_without_model_chats(bought):
    """Phase 2a: unrendered chats still carry what's on people's minds; every wom event has a teller and a listener."""
    e, sink, store, pid = bought
    woms = _ev(sink, "wom")
    print("wom events", len(woms), "conversations", e.world.counters["conversations_total"])
    assert woms, "no word-of-mouth events in a 3-day run"
    for x in woms:
        assert x["other_id"] is not None and x["agent_id"] != x["other_id"] and x["rendered"] is False
    assert any(x["payload"].get("product_id") for x in woms) or any(x["payload"]["kind"] == "phone_trouble" for x in woms)
    assert e.social.agenda.items                                   # people have things on their minds


def test_street_encounters_and_standing_exposures(bought):
    """Phase 2b: people who know each other meet on the move, and people standing near boards can be exposed."""
    e, sink, store, pid = bought
    greets, talks = _ev(sink, "greet"), [x for x in _ev(sink, "gate") if x["payload"].get("reason", "").startswith("known")]
    standing = [x for x in _ev(sink, "exposure") if x["payload"].get("standing")]
    print("street stats", e.social.stats, "greets", len(greets), "gate talks", len(talks), "standing exposures", len(standing))
    for g in greets:
        assert g["other_id"] is not None and g["agent_id"] != g["other_id"]
        assert (min(g["agent_id"], g["other_id"]), max(g["agent_id"], g["other_id"])) in e.social.rel
    assert standing, "nobody standing near a board was ever exposed in 3 days"
    assert all(x["payload"]["mode"] == "idle" for x in standing)


def test_visible_ad_finds_the_board_in_front_and_not_behind(bought):
    """Phase 2c: friends chatting in front of a live campaign board can see it; behind it they cannot."""
    import math as m_

    e, _, _, pid = bought
    media = e.media
    t = (e.world.t // 1440) * 1440 + 12 * 60           # noon: lit and visible
    live = [(sid, asg) for sid, asg in media.site_map.items() if asg["product_id"] == pid and asg["facing"] is not None]
    assert live, "the launched product has no assigned board"
    sid, asg = live[0]
    s = next(x for x in media.sites if x.site_id == sid)
    f = float(asg["facing"])
    front = (s.x + 15 * m_.sin(m_.radians(f)), s.y - 15 * m_.cos(m_.radians(f)))
    behind = (s.x - 15 * m_.sin(m_.radians(f)), s.y + 15 * m_.cos(m_.radians(f)))
    got = media.visible_ad(*front, t)
    assert got is not None and got[0] == pid and got[1]
    assert media.visible_ad(*behind, t) is None or media.visible_ad(*behind, t)[0] != pid
    assert media.visible_ad(s.x + 500, s.y + 500, t) is None


def test_phone_chats_and_meetups_in_a_real_run(bought):
    """Phase 2d: people text friends from their phones, and friends plan to meet."""
    e, sink, store, pid = bought
    texts = [x for x in _ev(sink, "gate") if x["payload"].get("channel") == "phone"]
    meets = _ev(sink, "meetup_planned")
    print("phone chats", len(texts), "meetups", len(meets))
    assert texts, "nobody texted anyone in 3 days"
    for x in texts:
        assert x["payload"]["conv_kind"] == "social"
        assert (min(x["agent_id"], x["other_id"]), max(x["agent_id"], x["other_id"])) in e.social.rel
        assert e.social.rel[(min(x["agent_id"], x["other_id"]), max(x["agent_id"], x["other_id"]))]["channel"] in ("online", "both")
    assert meets, "no friends planned to meet in 3 days"
    assert all(x["payload"]["act"] in ("cafe", "park") for x in meets)
