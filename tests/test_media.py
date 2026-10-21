"""Attention model, launch + channels in the engine (fakes): exposures, private thoughts, reviews, community."""

import asyncio

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api.main as m
import api.products as ap
from engine.events import NullSink
from engine.loop import Engine
from media.attention import AttentionCtx, attend, cfg, dwell_seconds, is_night, ots, p_glance, p_notice
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.schemas.product import StimulusRecord
from shared.schemas.world import Site
from shared.settings import Settings
from shared.store import MemoryStoreBackend

SITE = Site(site_id="S", kind="billboard", x=0, y=0, facings=[180.0], width_m=6, height_m=3, lit=False,
            cone_half_angle_deg=50, max_distance_m=80, rate_card_inr_week=50000, area_label="test")
STIM = StimulusRecord(creative_id="c", salience=0.7, clarity=0.7, hook="h", claims_carried=[], tone="t",
                      readable_at_distance=True, description="d. e.")


# ---------------------------------------------------------------- geometry (A-01)

def test_geometry_cases():
    # the face points south (180°): y grows southwards, so the audience is at +y
    assert ots(SITE, 180, 0, 40, 0) is not None                      # in front, walking north towards it
    assert ots(SITE, 180, 0, -40, 180) is None                       # behind the board
    assert ots(SITE, 180, 60, 10, 270) is None                       # outside the cone
    assert ots(SITE, 180, 0, 120, 0) is None                         # out of range
    assert ots(SITE, 180, 0, 40, 180) is None                        # heading away
    assert ots(SITE, 180, 0, 40, 0, minute_of_day=22 * 60) is None   # unlit at night
    lit = SITE.model_copy(update={"lit": True})
    assert ots(lit, 180, 0, 40, 0, minute_of_day=22 * 60) is not None
    assert is_night(23 * 60) and not is_night(12 * 60)
    assert dwell_seconds(SITE, "walk", False) > dwell_seconds(SITE, "car", False)


# ---------------------------------------------------------------- attention (A-02, A-05)

def _rates(n=20000, **kw):
    rng = np.random.default_rng(3)
    outs = []
    for i in range(n):
        d = 10 + (i % 70)
        o = ots(SITE, 180, 0, d, 0)
        mode = ["walk", "two_wheeler", "car", "bus"][i % 4]
        ctx = AttentionCtx(mode=mode, dwell_s=dwell_seconds(SITE, mode, False), clutter=i % 3,
                           on_phone=i % 5 == 0, fatigue=(i % 10) / 20, relevance=(i % 7) / 10, **kw)
        outs.append(attend(SITE, o, STIM, ctx, rng))
    g = sum(x != "pass" for x in outs) / n
    nt = sum(x == "notice" for x in outs) / n
    return g, nt


def test_attention_calibration_and_direction():
    g, nt = _rates()
    assert 0.2 <= g <= 0.5 and 0.02 <= nt <= 0.15   # loose: the gated calibration runs on the demo world below
    o = ots(SITE, 180, 0, 30, 0)
    base = AttentionCtx(relevance=0.3)
    assert p_glance(SITE, o, STIM, AttentionCtx(on_phone=True)) < p_glance(SITE, o, STIM, AttentionCtx())
    assert p_notice(STIM, AttentionCtx(relevance=0.9)) > p_notice(STIM, base)
    # repetition: the 10th exposure is less likely to be noticed than the 2nd (novelty + wear-out)
    assert p_notice(STIM, AttentionCtx(n_seen=9, n_noticed=8)) < p_notice(STIM, AttentionCtx(n_seen=1))
    old = cfg()["glance"]["a4"]
    try:
        cfg()["glance"]["a4"] = old + 1.0
        assert _rates(4000)[0] > g
    finally:
        cfg()["glance"]["a4"] = old


# ---------------------------------------------------------------- engine: launch + channels

N = 400


@pytest.fixture(scope="module")
def launched(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("media")
    s = Settings(world_agents=N, world_seed=99, checkpoint_every_sim_minutes=10**6, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp))
    store, files, sink = MemoryStoreBackend(), LocalFiles(str(tmp)), NullSink()
    asyncio.run(run_genesis(N, 99, store=store, files=files, sink=NullSink(), llm=None, settings=s))
    m.store = ap.store = lambda: store  # type: ignore[assignment]
    m._engine_get = lambda path: None  # type: ignore[assignment]
    ap._cache.clear()
    c = TestClient(m.app)
    pid = c.post("/api/products", json={
        "name": "Nova X1", "brand": "Arcline", "category": "Smartphone", "price_inr": 89999,
        "features": ["200MP camera", "Night mode"], "claims": ["The best camera ever put in a phone."],
        "target_personas": ["Young professionals into photography", "Tech early adopters"],
        "strategy": {"intensity": "high", "flight_days": 14}}).json()["product_id"]
    for kind, title, text in (("hoarding", "Hoarding", "SEE THE NIGHT."), ("bus_shelter", "Shelter", "Night shots."),
                              ("reel", "After dark", "After dark, Bengaluru changes."),
                              ("newspaper", "Print", "The best camera ever put in a phone."),
                              ("store_display", "Display", "Try night mode here")):
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
        evts = []
        for _ in range(int(1.6 * 1440)):
            await e.tick()
            evts += e.world.live_evts
        for _ in range(5):
            await asyncio.sleep(0.05)
        await e.bus.flush()
        return e, evts

    e, evts = asyncio.run(run())
    return e, sink, store, pid, evts


def test_launch_event_and_live(launched):
    e, sink, store, pid, evts = launched
    la = [x for x in sink.events if x["kind"] == "launch"]
    assert len(la) == 1 and la[0]["product_id"] == pid
    assert store.get("products", pid)["launched_at_t"] == la[0]["t"]
    le = next(x for x in evts if x["k"] == "launch")
    assert le["sites"] and le["stores"] and le["audience"]
    assert {s["site_id"] for s in e.world.sites_live if s["product_id"] == pid} == {s["site_id"] for s in le["sites"]}
    assert e.world.products_live[0]["id"] == pid and e.world.awareness[pid] > 0


def test_exposures_begin_within_an_hour_of_commutes(launched):
    e, sink, _, pid, _ = launched
    ex = [x for x in sink.events if x["kind"] == "exposure" and x["product_id"] == pid]
    chans = {x["payload"]["channel"] for x in ex}
    assert {"reel", "newspaper"} <= chans and chans & {"hoarding", "bus_shelter"}
    outs = {x["payload"]["outcome"] for x in ex}
    assert {"pass", "glance"} <= outs or {"scroll"} <= outs
    hoard = [x for x in ex if x["payload"]["channel"] in ("hoarding", "bus_shelter")]
    assert all({"distance_m", "angle_deg", "dwell_s", "facing", "mode", "lit"} <= set(x["payload"]) for x in hoard)
    readers = {p["agent_id"] for p in (d["profile"] | {"agent_id": d["agent_id"]} for d in e.store.list("agents"))
               if p["media"]["newspaper"]}
    assert all(x["agent_id"] in readers for x in ex if x["payload"]["channel"] == "newspaper")


def test_reels_reach_the_audience(launched):
    e, sink, _, pid, _ = launched
    aud = e.media.live[pid].audience
    reel = [x for x in sink.events if x["kind"] == "exposure" and x["product_id"] == pid
            and x["payload"]["channel"] == "reel"]
    assert reel and sum(x["agent_id"] in aud for x in reel) / len(reel) >= 0.7
    per_day: dict = {}
    for x in reel:
        k = (x["agent_id"], x["day"])
        per_day[k] = per_day.get(k, 0) + 1
    assert max(per_day.values()) <= 3


def test_every_rendered_notice_has_thought_memory_belief(launched):
    e, sink, store, pid, _ = launched
    th = [x for x in sink.events if x["kind"] == "thought" and x["product_id"] == pid]
    assert th and all(x["private"] for x in th)
    ex_ids = {x["event_id"] for x in sink.events if x["kind"] == "exposure"
              and x["payload"]["outcome"] in ("notice", "partial", "full")}
    assert all(x["payload"]["trigger_event_id"] in ex_ids for x in th)
    for x in [x for x in th if x["rendered"]][:20]:
        aid, trig = x["agent_id"], x["payload"]["trigger_event_id"]
        assert store.get(f"agents/{aid}/memories", f"ad-{trig}-{aid}") is not None
        b = store.get(f"agents/{aid}/beliefs", f"product:{pid}")
        assert b and b["awareness"] in ("aware", "familiar") and b["first_heard"]
    assert any(t["kind"] == "thought" and t["private"] and t["product_id"] == pid for t in sink.texts)
    assert any(i.product_id for lst in e.social.agenda.items.values() for i in lst)   # noticed products are on people's minds


def test_reviewer_publishes_and_community(launched):
    e, sink, store, pid, _ = launched
    priv = [x for x in sink.events if x["kind"] == "review_private"]
    pub = [x for x in sink.events if x["kind"] == "review_published"]
    assert priv and pub and priv[0]["private"] and not pub[0]["private"]
    assert pub[0]["payload"]["private_event_id"] in {x["event_id"] for x in priv}
    assert "private_opinion" not in pub[0]["payload"]
    threads = [x for x in sink.events if x["kind"] == "thread"]
    assert len(threads) >= 2                     # news desk + review thread
    assert store.list("threads") and store.list("reviews")
    assert any(x["kind"] == "exposure" and x["payload"]["channel"] == "community" for x in sink.events)


def test_baseline_ads_on_free_sites(launched):
    e, sink, _, pid, _ = launched
    held = {s["site_id"] for s in e.world.sites_live if s["product_id"] == pid}
    base = [s for s in e.world.sites_live if s["product_id"].startswith("baseline:")]
    assert base and not held & {s["site_id"] for s in base}
    assert any(x["kind"] == "exposure" and str(x["product_id"]).startswith("baseline:") for x in sink.events)


def test_zz_print_summary(launched):
    e, sink, _, pid, _ = launched
    from collections import Counter

    ex = [x for x in sink.events if x["kind"] == "exposure"]
    by = Counter((x["payload"]["channel"], x["payload"]["outcome"]) for x in ex if x["product_id"] == pid)
    print("\nSTATS", e.media.stats, "\nBY", sorted(by.items()))
    hoard = [x for x in ex if x["payload"]["channel"] in ("hoarding", "bus_shelter")]
    print("HOARD all products", len(hoard), Counter(x["payload"]["outcome"] for x in hoard))
    print("KINDS", Counter(x["kind"] for x in sink.events if x["kind"] in
                           ("thread", "comment", "upvote", "community_thought", "review_private", "review_published")))


def test_demo_world_calibration(launched):
    _, sink, _, _, _ = launched
    hoard = [x for x in sink.events if x["kind"] == "exposure" and x["payload"]["channel"] in ("hoarding", "bus_shelter")]
    n = len(hoard)
    g = sum(x["payload"]["outcome"] != "pass" for x in hoard) / n
    nt = sum(x["payload"]["outcome"] == "notice" for x in hoard) / n
    assert n > 300 and 0.30 <= g <= 0.40 and 0.04 <= nt <= 0.10, (n, g, nt)


async def test_store_display_exposure(launched):
    e, sink, _, pid, _ = launched
    lp = e.media.live[pid]
    st = next(s for s in e.wm.stores if s.store_id in lp.p.plan.stores)
    a = next(a for a in e.world.agents if not a.route and a.activity != "store_shift" and not a.offmap)
    a.place_id, a.activity = st.place_id, "shop"
    before = len(sink.events)
    e.media._store_displays(e.world, e.bus, e.world.t)
    await e.bus.flush()
    new = [x for x in sink.events[before:] if x["kind"] == "exposure" and x["payload"]["channel"] == "store_display"]
    assert new and new[0]["agent_id"] == a.id and new[0]["payload"]["store_id"] == st.store_id


def test_site_daily_view_totals(launched, tmp_path):
    from pathlib import Path

    from engine.events import DuckDBSink

    _, sink, _, pid, _ = launched
    db = DuckDBSink(Settings(duckdb_path=str(tmp_path / "v.duckdb"))).db
    db.insert("events", sink.events)
    for v in ("a0_retired_products", "a1_events_current", "v_exposures", "v_site_daily"):
        db.con.execute(db.translate(Path(f"infra/bigquery/views/{v}.sql").read_text(), "mirava"))
    rows = db.query("SELECT * FROM v_site_daily WHERE product_id = @p", {"p": pid})
    hoard = [x for x in sink.events if x["kind"] == "exposure" and x["product_id"] == pid
             and x["payload"]["channel"] in ("hoarding", "bus_shelter", "metro_panel")]
    assert rows and sum(r["ots"] for r in rows) == len(hoard)
    assert sum(r["notices"] for r in rows) == sum(x["payload"]["outcome"] == "notice" for x in hoard)
    assert all(0 <= r["glance_rate"] <= 1 and r["target_share"] is not None for r in rows)
    assert any(r["thoughts"] for r in rows)
