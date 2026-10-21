"""Phase 5 engine behaviour: staggered outreach, decisions, leave times, tables from who shows up, incentives."""

import asyncio
import math

import pytest

from engine.events import NullSink
from engine.loop import Engine
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend
from tests.test_survey import N, _run_until, _survey

LEAD = 180            # sim minutes until the long-notice survey starts
SHORT = 8             # … and the short-notice one


@pytest.fixture(scope="module")
def run2(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("outreach")
    s = Settings(world_agents=N, world_seed=11, checkpoint_every_sim_minutes=10**6, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp))
    store, files, sink = MemoryStoreBackend(), LocalFiles(str(tmp)), NullSink()
    asyncio.run(run_genesis(N, 11, store=store, files=files, sink=NullSink(), llm=None, settings=s))

    async def go():
        e = Engine(s, store, files, sink)
        e.boot()
        for _ in range(10 * 60 - e.world.t % 1440):               # 10:00
            await e.tick()
        t0 = e.world.t
        d1 = _survey("sv-lead", n=30)
        d1.update({"start_at_t": t0 + LEAD, "incentive": {"cash_inr": 500, "goodies": [
            {"kind": "accessory", "label": "earbuds", "value_inr": 1200}], "note": ""}})
        store.set("surveys", "sv-lead", d1)
        e.command({"type": "survey_launch", "survey_id": "sv-lead"})
        await _run_until(e, "sv-lead", 8 * 60)
        t1 = e.world.t
        d2 = _survey("sv-short", n=30)
        d2.update({"start_at_t": t1 + SHORT})
        store.set("surveys", "sv-short", d2)
        e.command({"type": "survey_launch", "survey_id": "sv-short"})
        await _run_until(e, "sv-short", 8 * 60)
        return e, t0, t1

    e, t0, t1 = asyncio.run(go())
    return e, sink, store, t0, t1


def _k(sink, kind, sid):
    return [x for x in sink.events if x["kind"] == kind and (x["payload"] or {}).get("survey_id") == sid]


def test_a_chosen_start_time_is_honoured(run2):
    _, sink, store, t0, _ = run2
    assert store.get("surveys", "sv-lead")["start_at_t"] == t0 + LEAD
    created = _k(sink, "survey_created", "sv-lead")[0]["payload"]
    assert created["start_at_t"] == t0 + LEAD and set(created["channels"]) == {"panel", "community", "word_of_mouth", "store_flyer"}


def test_nobody_hears_instantly_and_channels_are_recorded(run2):
    _, sink, store, t0, _ = run2
    inv = _k(sink, "survey_invite", "sv-lead")
    assert inv
    times = {x["t"] for x in inv}
    assert min(times) >= t0 + 1 and len(times) > 3                     # staggered (glances, then phone sessions), not all at launch
    assert {x["payload"]["channel"] for x in inv} <= {"panel", "community", "word_of_mouth", "store_flyer"}
    assert "panel" in {x["payload"]["channel"] for x in inv}
    rsvp = _k(sink, "survey_rsvp", "sv-lead")
    assert len(rsvp) == len(inv) and all(r["private"] for r in rsvp)
    out = store.get("surveys", "sv-lead")["outreach"]
    print("OUTREACH lead", out, "invite minutes", sorted(times)[:6], "…", len(times), "distinct")
    print("OUTREACH short", store.get("surveys", "sv-short")["outreach"])
    assert out["reached"] == len(inv) and out["accepted"] >= out["checked_in"] >= 1
    assert out["seen_by_channel"]["panel"] >= 1


def test_people_leave_early_enough_to_arrive_and_the_careless_cut_it_fine(run2):
    _, sink, store, t0, _ = run2
    doc = store.get("surveys", "sv-lead")
    start = t0 + LEAD
    went = [p for p in doc["participants"] if p["rsvp"] in ("attended", "no_show") and p.get("leave_t") is not None]
    assert went
    for p in went:
        assert p["seen_t"] >= t0 + 1 and p["leave_t"] >= p["seen_t"] and p["eta"] >= 1
        assert p["leave_t"] <= start - p["eta"] + 10                       # at worst ~10 min late for the careless
    arrived = [p for p in doc["participants"] if p["rsvp"] == "attended"]
    assert arrived and all(p["arrived_t"] is not None for p in arrived)
    assert max(p["arrived_t"] for p in arrived) <= start + 20 + 5           # the session waited at most the gather timeout


def test_tables_are_made_from_the_people_who_turned_up(run2):
    _, _, store, _, _ = run2
    doc = store.get("surveys", "sv-lead")
    att = [p for p in doc["participants"] if p["rsvp"] == "attended" and not p.get("late")]
    tables = [tb for tb in doc["tables"] if not tb.get("late")]          # late arrivals get a side seat (B3.8)
    assert att and len(tables) == math.ceil(len(att) / 8)
    seated = {a for tb in tables for a in tb["seats"]}
    assert seated == {p["agent_id"] for p in att}
    assert all(p.get("table_id") for p in att)
    assert not any(p.get("table_id") for p in doc["participants"] if p["rsvp"] in ("no_show", "declined"))


def test_attenders_are_paid_and_start_telling_people(run2):
    e, sink, store, _, _ = run2
    doc = store.get("surveys", "sv-lead")
    att = {p["agent_id"] for p in doc["participants"] if p["rsvp"] == "attended"}
    paid = _k(sink, "incentive_paid", "sv-lead")
    assert {x["agent_id"] for x in paid} == att
    assert all(x["payload"]["cash_inr"] == 500 and x["payload"]["goodies"] == ["earbuds"] for x in paid)
    assert any(i.kind == "got_goodies" for a in att for i in e.social.agenda.items.get(a, []))
    assert _k(sink, "survey_checkin", "sv-lead")


def test_short_notice_only_reaches_people_who_can_get_there(run2):
    _, sink, store, t0, t1 = run2
    acc = [p for p in store.get("surveys", "sv-short")["participants"] if p["rsvp"] in ("accepted", "attended", "no_show")]
    for p in acc:
        assert p["seen_t"] + p["eta"] <= t1 + SHORT + 8                      # nobody says yes to the impossible
    late = [x for x in _k(sink, "survey_rsvp", "sv-short") if "too late" in x["payload"]["reason"]]
    lead_acc = sum(1 for p in store.get("surveys", "sv-lead")["participants"] if p["rsvp"] in ("attended", "no_show"))
    assert len(acc) < lead_acc or late                                       # fewer come, and some are 'too late'
    assert len(acc) >= 1, "with 8 minutes' notice at least someone nearby should make it"
