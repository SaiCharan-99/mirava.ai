"""Live focus groups (Phases E–F): one shared timer, live counts, the room's live state, viewers; the session runs to
the end with nobody watching."""

import asyncio
import json

import pytest

from api.surveys import timer
from engine.events import NullSink
from engine.live import LiveHub
from engine.loop import Engine
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend
from tests.test_survey import _survey


def test_seconds_to_start_uses_the_world_clock_rate():
    assert timer(1000, {"t": 900, "scale": {"sim_min_per_real_s": 0.4}})["seconds_to_start"] == 250.0
    slowed = timer(1000, {"t": 900, "scale": {"sim_min_per_real_s": 0.2}, "slowed": True})
    assert slowed["seconds_to_start"] == 500.0                     # a slowed world → the timer stretches
    assert timer(800, {"t": 900, "scale": {"sim_min_per_real_s": 0.4}})["seconds_to_start"] == 0.0
    assert timer(None, {"t": 900})["seconds_to_start"] is None


def test_viewers_are_counted_and_announced():
    sent: list[str] = []

    class WS:
        async def send_text(self, s):
            sent.append(s)

    async def go():
        hub, a, b = LiveHub(), WS(), WS()
        hub.on_client_message(a, '{"type":"sub","survey_id":"sv-1"}')
        hub.on_client_message(b, '{"type":"sub","survey_id":"sv-1"}')
        await asyncio.sleep(0)
        assert hub.viewers("sv-1") == 2
        hub.leave(a)
        await asyncio.sleep(0)
        return hub

    hub = asyncio.run(go())
    assert hub.viewers("sv-1") == 1
    ns = [json.loads(s)["n"] for s in sent if '"survey_viewers"' in s]
    assert ns and ns[-1] == 1


@pytest.fixture(scope="module")
def watched(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("live")
    s = Settings(world_agents=240, world_seed=11, checkpoint_every_sim_minutes=10**6, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp))
    store = MemoryStoreBackend()
    asyncio.run(run_genesis(240, 11, store=store, files=LocalFiles(str(tmp)), sink=NullSink(), llm=None, settings=s))

    async def go():
        e = Engine(s, store, LocalFiles(str(tmp)), NullSink())
        e.boot()
        assert not e.hub.clients                                     # nobody has the site open
        for _ in range(8 * 60 - e.world.t % 1440):
            await e.tick()
        store.set("surveys", "sv-live", _survey("sv-live"))
        e.command({"type": "survey_launch", "survey_id": "sv-live"})
        evts, states = [], []
        for _ in range(6 * 60):
            await e.tick()
            evts += [x for x in e.world.live_evts if x.get("k") == "survey"]
            if e.surveys.active is not None:
                states.append(e.surveys.live_state("sv-live", include_private=True))
            if (store.get("surveys", "sv-live") or {}).get("status") == "completed" and e.surveys.active is None:
                break
        return e, evts, states

    return asyncio.run(go())


def test_runs_to_the_end_with_nobody_watching(watched):
    e, evts, _ = watched
    assert e.store.get("surveys", "sv-live")["status"] == "completed"
    assert evts[-1]["status"] == "completed" and evts[-1]["attended"] > 0


def test_live_events_carry_start_time_and_counts(watched):
    _, evts, _ = watched
    rec = [x for x in evts if x["status"] in ("recruiting", "gathering")]
    assert rec and all(x["start_at_t"] == rec[0]["start_at_t"] for x in rec)
    assert set(rec[-1]["counts"]) == {"invited", "replied", "accepted", "waitlist", "walking", "arrived"}
    assert max(x["counts"]["arrived"] for x in evts) > 0 and max(x["counts"]["walking"] for x in rec) > 0


def test_live_state_shows_the_room_as_it_is(watched):
    _, _, states = watched
    sess = [s for s in states if s["status"] == "in_session"]
    assert sess and sess[0]["tables"]
    qs = [s["q_index"] for s in sess]
    assert qs == sorted(qs) and qs[-1] > 0                         # re-entering later shows a later question
    last = sess[-1]
    tid = last["tables"][0]["table_id"]
    assert last["messages"][tid] and len(last["messages"][tid]) <= 30
    assert all(p["private"] for p in last["private"]) and last["private"]
    early = [s for s in states if s["status"] in ("recruiting", "gathering")]
    assert early and early[-1]["phase"] == "gathering" and early[-1]["arrived_ids"]
