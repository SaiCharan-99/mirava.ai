"""The always-on runner (W-06, E-07): lease, resume, catch-up replay, paced ticks, flushes, checkpoints."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from engine import checkpoint
from engine.clock import Clock
from engine.events import EventBus, Sink
from engine.lease import Lease
from engine.live import LiveHub
from engine.world import World
from population.genesis import genesis_bucket, unpack
from shared import time as simtime
from shared.files import Files
from shared.schemas.agent import AgentProfile, AgentState
from shared.settings import Settings
from shared.store import DocStore
from world.map import WorldMap, get_map

log = logging.getLogger("engine")
FLUSH_EVERY = 4


def load_genesis(files: Files, bucket: str, version: str = "v1") -> dict[str, Any]:
    """Profiles, metas, states and manifest from `genesis/{version}/`."""
    import json

    rd = lambda name: unpack(files.read(bucket, f"genesis/{version}/{name}.msgpack.zst"))  # noqa: E731
    return {"profiles": [AgentProfile.model_validate(p) for p in rd("profiles")],
            "metas": {int(k): v for k, v in rd("meta").items()},
            "states": [AgentState.model_validate(s) for s in rd("states")],
            "manifest": json.loads(files.read(bucket, f"genesis/{version}/manifest.json"))}


class Engine:
    """Owns the World while holding the lease; otherwise waits read-only."""

    def __init__(self, settings: Settings, store: DocStore, files: Files, sink: Sink,
                 wm: WorldMap | None = None) -> None:
        self.s = settings
        self.store = store
        self.files = files
        self.sink = sink
        self.wm = wm or get_map()
        self.bucket = genesis_bucket(settings)
        self.clock = Clock(seconds_per_sim_day=settings.world_seconds_per_sim_day, speed=settings.world_speed)
        self.lease = Lease(store)
        self.hub = LiveHub()
        self.world: World | None = None
        self.bus: EventBus | None = None
        self.last_tick_real = time.time()
        self.started_real = time.time()
        self.tick_ms: list[float] = []
        self.status = "starting"
        self.last_checkpoint: dict[str, Any] = {}
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ setup
    def boot(self) -> None:
        """Load the latest checkpoint (or genesis) and replay to the last published minute without re-emitting."""
        g = load_genesis(self.files, self.bucket)
        doc = self.store.get("world", "state") or {}
        last_flushed = int(doc.get("last_flushed_t", -1))
        self.bus = EventBus(self.sink, suppress_until_t=last_flushed)
        counts = {"agents": g["manifest"]["n"], "households": g["manifest"]["households"],
                  "relationships": g["manifest"]["relationships"]}
        w = World(g["profiles"], g["metas"], self.wm, int(g["manifest"]["world_seed"]), self.bus, counts=counts)
        ck = checkpoint.load_latest(self.files, self.bucket, self.store)
        if ck is not None:
            w.load_checkpoint(ck)
        else:
            w.init_from_states(g["states"])
        self.bus.listeners.clear()
        replay = 0
        while w.t < last_flushed:
            w.step()
            replay += 1
        self.bus.flush_sync(upto_t=w.t)
        self.bus.suppress_until_t = -1          # replay done: everything from here on is new
        self.world = w
        self.bus.new("engine_start", w.t, None, {"holder": self.lease.holder, "resumed_from": ck["t"] if ck else None,
                                                 "replayed_ticks": replay})
        log.info("booted at %s (checkpoint %s, replayed %d)", simtime.fmt(w.t), ck["t"] if ck else "genesis", replay)

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        """Main loop: wait for the lease, boot, then tick forever at the clock's pace."""
        renew = asyncio.create_task(self._renew_loop())
        stats = asyncio.create_task(self._stats_loop())
        try:
            while not self._stop.is_set():
                if not self.lease.held:
                    self.status = "follower"
                    self.world = None
                    if not await asyncio.to_thread(self.lease.acquire):
                        await asyncio.sleep(5)
                        continue
                    await asyncio.to_thread(self.boot)
                    self.status = "running"
                    await self.hub.broadcast_hello(self)
                if self.clock.paused:
                    self.status = "paused"
                    self.last_tick_real = time.time()
                    await asyncio.sleep(0.5)
                    continue
                self.status = "running"
                start = time.time()
                await self.tick()
                spent = time.time() - start
                await asyncio.sleep(max(0.0, self.clock.real_s_per_tick - spent))
        finally:
            renew.cancel()
            stats.cancel()

    async def tick(self) -> None:
        """One sim minute + live push + periodic flush/checkpoint."""
        w, bus = self.world, self.bus
        assert w is not None and bus is not None
        t0 = time.perf_counter()
        w.step()
        self.tick_ms.append((time.perf_counter() - t0) * 1000)
        self.tick_ms = self.tick_ms[-600:]
        self.last_tick_real = time.time()
        await self.hub.push_tick(w, self.clock)
        if w.t % FLUSH_EVERY == 0:
            await bus.flush(upto_t=w.t)
            await asyncio.to_thread(self.store.set, "world", "state",
                                    {"t": w.t, "last_flushed_t": w.t, "label": simtime.fmt(w.t), "status": self.status,
                                     "speed": self.clock.speed, "seconds_per_sim_day": self.clock.seconds_per_sim_day},
                                    True)
        if w.t % self.s.checkpoint_every_sim_minutes == 0:
            await self.save_checkpoint()

    async def save_checkpoint(self) -> None:
        """Checkpoint + Firestore agent-state batch."""
        w, bus = self.world, self.bus
        assert w is not None and bus is not None
        t0 = time.perf_counter()
        state = w.to_checkpoint()
        info = await asyncio.to_thread(checkpoint.save, self.files, self.bucket, self.store, state)
        docs = {}
        for a in w.agents:
            st = w.agent_state(a.id).model_dump()
            ph = w.phones[a.id]
            docs[str(a.id)] = {"state": st, "phone": ph, "row": {"activity": a.activity, "phone": {
                "brand": ph["brand"], "tier": ph["tier"], "bought_t": ph["bought_t"], "condition": ph["condition"]}}}
        await asyncio.to_thread(self.store.set_many, "agents", docs, True)
        info["seconds"] = round(time.perf_counter() - t0, 2)
        self.last_checkpoint = {**info, "t": w.t}
        bus.new("checkpoint", w.t, None, info)
        log.info("checkpoint %s", info)

    async def _renew_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            if self.lease.held:
                ok = await asyncio.to_thread(self.lease.renew)
                if not ok:
                    log.warning("lease lost; switching to follower")

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.world is not None:
                await self.hub.send_all(self.world.stats(self.budget()))

    async def shutdown(self) -> None:
        """Final flush + checkpoint + lease release (SIGTERM on deploy)."""
        self._stop.set()
        if self.world is not None and self.lease.held and self.bus is not None:
            await self.bus.flush(upto_t=self.world.t)
            await self.save_checkpoint()
            await self.bus.flush(upto_t=self.world.t)
            self.store.set("world", "state", {"last_flushed_t": self.world.t, "t": self.world.t}, merge=True)
            self.lease.release()

    # ------------------------------------------------------------------ views
    def budget(self) -> dict[str, float]:
        """Budget used today (governor arrives in phase 3)."""
        return {"used_usd": 0.0, "cap_usd": self.s.daily_cap_usd}

    def healthy(self) -> bool:
        """A tick happened in the last 120 s (or we are paused / waiting for the lease)."""
        return time.time() - self.last_tick_real < 120 or self.status in ("paused",)

    def state(self) -> dict[str, Any]:
        """`GET /world/state` body."""
        t = self.world.t if self.world else int((self.store.get("world", "state") or {}).get("t", 0))
        p95 = sorted(self.tick_ms)[int(len(self.tick_ms) * 0.95)] if self.tick_ms else None
        return {"t": t, "day": simtime.day_of(t), "label": simtime.fmt(t),
                "scale": {"sim_min_per_real_s": self.clock.sim_min_per_real_s, "speed": self.clock.speed},
                "slowed": self.clock.slowed, "status": self.status, "budget": self.budget(),
                "engine": {"holder": self.lease.holder, "lease_held": self.lease.held, "tick_p95_ms": p95,
                           "viewers": len(self.hub.clients), "last_checkpoint": self.last_checkpoint,
                           "events": self.bus.count if self.bus else 0}}

    def command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Apply pause / resume / set_speed (others arrive in later phases)."""
        kind = cmd.get("type")
        if kind == "pause":
            self.clock.paused = True
        elif kind == "resume":
            self.clock.paused = False
        elif kind == "set_speed":
            self.clock.set_speed(float(cmd.get("speed", 1.0)))
        else:
            return {"ok": False, "error": f"unsupported command {kind!r} in this phase"}
        if self.bus is not None and self.world is not None:
            self.bus.new("command", self.world.t, None, {k: v for k, v in cmd.items() if k != "auth"})
        return {"ok": True, "paused": self.clock.paused, "speed": self.clock.speed}
