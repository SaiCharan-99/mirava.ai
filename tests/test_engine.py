"""Engine: lease, determinism, checkpoint/resume, movement on the graph, live protocol, tasks, clock."""

import asyncio
import math
import random

import pytest

from engine.clock import Clock
from engine.events import EventBus, NullSink
from engine.lease import Lease
from engine.live import hello, tick_frames
from engine.loop import Engine
from engine.movement import heading
from engine.tasks import TaskQueue
from engine.world import World
from population.genesis import build_world, initial_state, metas_of, profiles_of, run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend
from world.map import get_map

N = 150


@pytest.fixture(scope="module")
def small():
    wm = get_map()
    w = build_world(N, 99, wm)
    return wm, profiles_of(w), metas_of(w)


def make_world(small, sink=None):
    wm, profs, metas = small
    bus = EventBus(sink or NullSink())
    w = World(profs, metas, wm, 99, bus)
    w.init_from_states([initial_state(p, wm) for p in profs])
    return w, bus


def test_lease_single_writer():
    store = MemoryStoreBackend()
    now = [1000.0]
    a = Lease(store, "A", clock=lambda: now[0])
    b = Lease(store, "B", clock=lambda: now[0])
    assert a.acquire() and not b.acquire()
    now[0] += 30
    assert a.renew() and not b.acquire()
    now[0] += 61
    assert b.acquire() and not a.renew()
    b.release()
    assert a.acquire()


def test_determinism_two_days(small):
    hashes = []
    for _ in range(2):
        w, bus = make_world(small)
        for _ in range(2 * 1440):
            w.step()
        hashes.append((bus.digest(), w.state_hash(), bus.count))
    assert hashes[0] == hashes[1] and hashes[0][2] > 1000


def test_movement_on_graph_and_heading(small):
    w, _ = make_world(small)
    nodes = {(round(x, 1), round(y, 1)) for x, y in w.wm.nodes}
    seen = 0
    for _ in range(600):
        w.step()
        for a in w.agents:
            for s in a.route[1:-1]:
                assert (round(s.x0, 1), round(s.y0, 1)) in nodes
                seen += 1
            for s in a.route:
                if math.dist((s.x0, s.y0), (s.x1, s.y1)) > 1:
                    assert s.heading == heading(s.x0, s.y0, s.x1, s.y1)
                    assert s.t1 > s.t0
    assert seen > 50
    assert heading(0, 0, 0, -1) == 0 and heading(0, 0, 1, 0) == 90


def test_needs_bounded_week(small):
    w, _ = make_world(small)
    seen = set()
    for _ in range(3 * 1440):
        w.step()
        if w.t % 30 == 0:
            seen |= {a.activity for a in w.agents}
    assert w.needs.min() >= 0 and w.needs.max() <= 1
    assert {"sleep", "home", "commute", "work", "school", "eat", "shop"} <= seen


def test_live_protocol_shapes(small):
    w, _ = make_world(small)
    c = Clock(3600)
    for _ in range(8 * 60):
        w.step()
    h = hello(w, c, {"used_usd": 0, "cap_usd": 15})
    assert h["type"] == "hello" and h["scale"]["sim_min_per_real_s"] == 0.4
    assert set(h["agents"][0]) == {"id", "x", "y", "h", "mode", "act"}
    st = w.stats()
    assert set(st["counts"]) >= {"agents", "households", "relationships", "conversations_today",
                                 "conversations_total", "thoughts_today", "products_live"}
    kinds = set()
    for _ in range(30):
        w.step()
        for f in tick_frames(w, c):
            kinds.add(f["type"])
            if f["type"] == "seg":
                assert set(f["items"][0]) == {"a", "x0", "y0", "x1", "y1", "t0", "t1", "mode"}
            if f["type"] == "evt":
                assert all("k" in e for e in f["items"])
    assert {"seg", "evt", "clock"} <= kinds


async def test_checkpoint_resume_no_duplicates(tmp_path):
    s = Settings(world_agents=N, world_seed=99, checkpoint_every_sim_minutes=60, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp_path))
    store, files, sink = MemoryStoreBackend(), LocalFiles(str(tmp_path)), NullSink()
    await run_genesis(N, 99, store=store, files=files, sink=NullSink(), llm=None, settings=s)
    kill_at = random.Random(5).randint(200, 400)
    e1 = Engine(s, store, files, sink)
    e1.boot()
    for _ in range(kill_at):
        await e1.tick()
    # crash: no shutdown; restart from the last checkpoint and replay silently
    e2 = Engine(s, store, files, sink)
    e2.boot()
    final = 520
    while e2.world.t < final:
        await e2.tick()
    await e2.bus.flush()
    ids = [e["event_id"] for e in sink.events]
    assert len(ids) == len(set(ids))
    ref = Engine(s, MemoryStoreBackend(), files, NullSink())
    ref.store.set("world", "state", {"last_flushed_t": -1})
    ref.boot()
    while ref.world.t < final:
        ref.world.step()
    assert ref.world.state_hash() == e2.world.state_hash()


async def test_task_queue_applies_at_deterministic_time():
    q = TaskQueue(concurrency=2, timeout_s=1)

    async def slow():
        await asyncio.sleep(0.01)
        return "done"

    async def boom():
        raise RuntimeError

    q.submit("a", slow, 10, 5, lambda: "fb")
    q.submit("b", boom, 10, 5, lambda: "fb")
    assert await q.collect(14) == []
    assert await q.collect(15) == [("a", "done"), ("b", "fb")]


def test_clock_scale():
    c = Clock(3600)
    assert c.real_s_per_tick == 2.5 and c.sim_min_per_real_s == 0.4
    c.set_speed(2)
    assert c.real_s_per_tick == 1.25


def test_lease_revision_handoff():
    store = MemoryStoreBackend()
    old = Lease(store, "old", revision="world-engine-00003-abc")
    new = Lease(store, "new", revision="world-engine-00004-xyz")
    assert old.acquire() and not new.acquire()
    assert new.request_takeover() and old.handoff_requested()
    assert not old.renew()
    old.release()
    assert new.acquire() and not new.handoff_requested()
