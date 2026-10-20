"""The always-on runner (W-06, E-07): lease, resume, catch-up replay, paced ticks, flushes, checkpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from engine import checkpoint
from engine.clock import Clock
from engine.commerce_rt import CommerceRuntime
from engine.events import EventBus, Sink
from engine.governor import BudgetGovernor
from engine.highlights import HighlightRecorder, day_of_end, encode, key_for
from engine.lease import Lease
from engine.live import LiveHub
from engine.media_rt import MediaRuntime
from engine.social_rt import SocialRuntime
from engine.survey.runtime import SurveyRuntime
from engine.world import World
from mind.decision import get_decider
from mind.opinion import OpinionEngine
from population.genesis import genesis_bucket, unpack
from shared import time as simtime
from shared.files import Files
from shared.llm import LLMClient, get_llm
from shared.schemas.agent import AgentProfile, AgentState
from shared.schemas.events import Event
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
            "relationships": rd("relationships"),
            "manifest": json.loads(files.read(bucket, f"genesis/{version}/manifest.json"))}


class Engine:
    """Owns the World while holding the lease; otherwise waits read-only."""

    def __init__(self, settings: Settings, store: DocStore, files: Files, sink: Sink,
                 wm: WorldMap | None = None, llm: LLMClient | None = None, social: bool = True,
                 media: bool = True, commerce: bool = True) -> None:
        self.s = settings
        self.store = store
        self.files = files
        self.sink = sink
        self.wm = wm or get_map()
        self.bucket = genesis_bucket(settings)
        self.clock = Clock(seconds_per_sim_day=settings.world_seconds_per_sim_day, speed=settings.world_speed)
        self.lease = Lease(store)
        self.llm = llm or get_llm(settings)
        self.gov = BudgetGovernor()
        self.social_enabled = social
        self.social: SocialRuntime | None = None
        self.media_enabled = media
        self.media: MediaRuntime | None = None
        self.commerce_enabled = commerce and media
        self.commerce: CommerceRuntime | None = None
        self.surveys: SurveyRuntime | None = None
        self.opinion: OpinionEngine | None = None
        self.highlights: HighlightRecorder | None = None
        self._first_line: dict[str, str] = {}
        self.hub = LiveHub()
        self.world: World | None = None
        self.bus: EventBus | None = None
        self.last_tick_real = time.time()
        self.started_real = time.time()
        self.tick_ms: list[float] = []
        self.status = "starting"
        self.last_checkpoint: dict[str, Any] = {}
        self._stop = asyncio.Event()
        self.retired = False
        self._lock = asyncio.Lock()
        self._reload_key: str | None = None     # demo snapshot checkpoint to reboot from (tools.demo_snapshot)
        self._tasks: set[asyncio.Future] = set()

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
        self.opinion = OpinionEngine(w.profiles, w.seed, phones=w.phones)
        if ck is not None and ck.get("opinion"):
            self.opinion.load(ck["opinion"])
        if self.social_enabled:
            watched = {int(d["agent_id"]) for d in self.store.where("agents", "watched", True)}
            self.social = SocialRuntime(self.store, self.llm, get_decider(self.llm, self.s), self.gov,
                                        g["relationships"], watched=watched, opinion=self.opinion)
            if ck is not None and ck.get("social"):
                self.social.load(ck["social"])
        if self.media_enabled:
            self.media = MediaRuntime(self.store, self.llm, self.gov, w, social=self.social, opinion=self.opinion)
            if self.social is not None:
                media = self.media
                self.social.catalog_fn = lambda: {pid: lp.p.name for pid, lp in media.live.items()}
            if ck is not None and ck.get("media"):
                self.media.load(ck["media"])
        if self.commerce_enabled and self.media is not None:
            self.commerce = CommerceRuntime(self.store, self.llm, get_decider(self.llm, self.s), self.gov, w,
                                            media=self.media, social=self.social, opinion=self.opinion)
            self.media.commerce = self.commerce
            if ck is not None and ck.get("commerce"):
                self.commerce.load(ck["commerce"])
            else:
                self.commerce.seed_from_media(w.t)
        if self.media is not None:
            self.surveys = SurveyRuntime(self.store, self.llm, get_decider(self.llm, self.s), self.gov, w, hub=self.hub,
                                         commerce=self.commerce, social=self.social)
            if ck is not None and ck.get("surveys"):
                self.surveys.load(ck["surveys"])
        self.highlights = HighlightRecorder({p.agent_id: p.name.split()[0] for p in g["profiles"]})
        if ck is not None and ck.get("highlights"):
            self.highlights.load(ck["highlights"])
        replay = 0
        while w.t < last_flushed:
            w.step()
            replay += 1
        self.bus.flush_sync(upto_t=w.t)
        self.bus.suppress_until_t = -1          # replay done: everything from here on is new
        if self.social is not None:
            self.bus.listeners.append(self.social.on_event)
        if self.commerce is not None:
            self.bus.listeners.append(self.commerce.on_event)
        if self.surveys is not None:
            self.bus.listeners.append(self.surveys.on_event)
        self.bus.listeners.append(self._highlight_event)
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
                if self.retired:
                    self.status = "handed_off"
                    await asyncio.sleep(5)
                    continue
                if not self.lease.held:
                    self.status = "follower"
                    self.world = None
                    if not await asyncio.to_thread(self.lease.acquire):
                        await asyncio.to_thread(self.lease.request_takeover)
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
                if self._reload_key is not None:
                    async with self._lock:
                        await self._reload()
                    await self.hub.broadcast_hello(self)
                start = time.time()
                async with self._lock:
                    if self.world is None:
                        continue
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
        if self.social is not None:
            await self.social.tick(w, bus)
        if self.media is not None:
            await self.media.tick(w, bus)
        if self.commerce is not None:
            await self.commerce.tick(w, bus)
        if self.surveys is not None:
            await self.surveys.tick(w, bus)
        if self.highlights is not None:
            self.highlights.sample(w.t, [w.position(a, float(w.t))[:2] for a in w.agents])
            done = day_of_end(w.t)
            if done is not None:
                h = self.highlights.finish_day(done)
                await asyncio.to_thread(self.files.write, self.bucket, key_for(done), encode(h))
                self._first_line.clear()
        if w.t % 60 == 0:
            gs = self.gov.on_sim_hour(w.t)
            self.clock.slowed = self.gov.slowed
            self.clock.budget_factor = self.gov.speed_factor
            bus.new("budget", w.t, None, {**vars(gs), **({"social": self.social.stats} if self.social else {}),
                                          **({"media": self.media.stats} if self.media else {}),
                                          **({"commerce": self.commerce.stats} if self.commerce else {})})
            self._log_metrics(gs)
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

    async def _reload(self) -> None:
        """Reboot in place from a snapshot checkpoint: point `world/state` at it, then boot (no replay)."""
        key, self._reload_key = self._reload_key, None
        assert key is not None
        if self.bus is not None:
            await self.bus.flush()
        t = int(checkpoint.unpack(await asyncio.to_thread(self.files.read, self.bucket, key))["t"])
        await asyncio.to_thread(self.store.set, "world", "state",
                                {"last_checkpoint": key, "checkpoint_t": t, "last_flushed_t": t, "t": t}, True)
        await asyncio.to_thread(self.boot)
        log.info("reloaded from snapshot %s at t=%s", key, t)

    async def save_checkpoint(self) -> None:
        """Checkpoint + Firestore agent-state batch."""
        w, bus = self.world, self.bus
        assert w is not None and bus is not None
        t0 = time.perf_counter()
        state = w.to_checkpoint()
        if self.social is not None:
            state["social"] = self.social.to_dict()
        if self.opinion is not None:
            state["opinion"] = self.opinion.to_dict()
        if self.media is not None:
            state["media"] = self.media.to_dict()
        if self.commerce is not None:
            state["commerce"] = self.commerce.to_dict()
        if self.surveys is not None:
            state["surveys"] = self.surveys.to_dict()
        if self.highlights is not None:
            state["highlights"] = self.highlights.to_dict()
        info = await asyncio.to_thread(checkpoint.save, self.files, self.bucket, self.store, state)
        docs = {}
        for a in w.agents:
            st = w.agent_state(a.id).model_dump()
            ph = w.phones[a.id]
            row: dict[str, Any] = {"activity": a.activity, "phone": {
                "brand": ph["brand"], "tier": ph["tier"], "bought_t": ph["bought_t"], "condition": ph["condition"]}}
            if self.commerce is not None:
                row["stages"] = self.commerce.stages_of(a.id)
                row["need"] = self.commerce.need(w, a.id)
            docs[str(a.id)] = {"state": st, "phone": ph, "row": row}
        await asyncio.to_thread(self.store.set_many, "agents", docs, True)
        info["seconds"] = round(time.perf_counter() - t0, 2)
        self.last_checkpoint = {**info, "t": w.t}
        bus.new("checkpoint", w.t, None, info)
        log.info("checkpoint %s", info)

    async def _renew_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            if self.lease.held and await asyncio.to_thread(self.lease.handoff_requested):
                log.info("newer revision requested the lease; handing off")
                self.retired = True
                await self.handoff()
            elif self.lease.held:
                ok = await asyncio.to_thread(self.lease.renew)
                if not ok:
                    log.warning("lease lost; switching to follower")

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.world is not None:
                await self.hub.send_all(self.stats_frame())

    def stats_frame(self) -> dict[str, Any]:
        """`stats` frame: world counts + budget + live product funnel."""
        assert self.world is not None
        frame = self.world.stats(self.budget())
        if self.commerce is not None:
            frame["funnel"] = self.commerce.funnel()
        if self.media is not None:
            frame["campaigns"] = self.media.campaigns(self.world.t)
        return frame

    async def handoff(self) -> None:
        """Final flush + checkpoint + lease release, then stay idle."""
        async with self._lock:
            await self._handoff()

    async def _handoff(self) -> None:
        if self.world is not None and self.lease.held and self.bus is not None:
            await self.bus.flush(upto_t=self.world.t)
            await self.save_checkpoint()
            await self.bus.flush(upto_t=self.world.t)
            self.store.set("world", "state", {"last_flushed_t": self.world.t, "t": self.world.t}, merge=True)
            self.lease.release()
        self.world = None

    async def shutdown(self) -> None:
        """SIGTERM on deploy: hand off and stop."""
        self._stop.set()
        await self.handoff()

    def _highlight_event(self, ev: Event) -> None:
        """Bus listener feeding the day's highlight candidates."""
        if self.highlights is None or self.world is None:
            return
        if ev.kind == "message":
            if ev.payload.get("seq") == 0 and ev.session_id:
                self._first_line[ev.session_id] = ev.payload.get("text", "")
            return
        xy = None
        if ev.agent_id is not None and 0 <= ev.agent_id < len(self.world.agents):
            xy = self.world.position(self.world.agents[ev.agent_id], float(ev.t))[:2]
        self.highlights.on_event(ev, xy, self._first_line.pop(ev.session_id or "", ""))

    # ------------------------------------------------------------------ views
    def _log_metrics(self, gs: Any) -> None:
        """One structured line per sim hour → Cloud Logging jsonPayload → log-based metrics (guide 13 dashboard)."""
        p95 = sorted(self.tick_ms)[int(len(self.tick_ms) * 0.95)] if self.tick_ms else 0.0
        done = self.gov.rendered + self.gov.unrendered
        print(json.dumps({"severity": "INFO", "message": "engine metrics", "metric": "engine", "t": self.world.t if self.world else None,
                          "tick_p95_ms": round(p95, 1), "spend_today_usd": round(self.gov.spent_today, 4),
                          "rendered_ratio": round(self.gov.rendered / done, 3) if done else 1.0,
                          "live_viewers": len(self.hub.clients), "slowed": bool(getattr(gs, "slowed", False))}),
              flush=True)

    def budget(self) -> dict[str, float]:
        """Budget used today (background world) from the governor."""
        return {"used_usd": round(self.gov.spent_today, 3), "cap_usd": self.s.daily_cap_usd,
                "slowed": self.gov.slowed, "speed_factor": self.gov.speed_factor}

    def healthy(self) -> bool:
        """A tick happened in the last 120 s (or we are paused / waiting for the lease)."""
        return time.time() - self.last_tick_real < 120 or self.status in ("paused", "follower", "handed_off")

    def state(self) -> dict[str, Any]:
        """`GET /world/state` body."""
        t = self.world.t if self.world else int((self.store.get("world", "state") or {}).get("t", 0))
        p95 = sorted(self.tick_ms)[int(len(self.tick_ms) * 0.95)] if self.tick_ms else None
        return {"t": t, "day": simtime.day_of(t), "label": simtime.fmt(t),
                "scale": {"sim_min_per_real_s": self.clock.sim_min_per_real_s, "speed": self.clock.speed},
                "slowed": self.clock.slowed, "status": self.status, "budget": self.budget(),
                "surveys": self.surveys.status() if self.surveys else None,
                "interactive": {"used_usd": round(self.gov.interactive_today, 4),
                                "cap_usd": float(self.gov.cfg["interactive_cap_usd"])},
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
        elif kind == "reload":
            key = str(cmd.get("checkpoint", ""))
            if not key.startswith("snapshots/") or not self.files.exists(self.bucket, key):
                return {"ok": False, "error": "unknown snapshot checkpoint"}
            self._reload_key = key
        elif kind == "poll":
            if self.world is None or self.bus is None:
                return {"ok": False, "error": "engine not running"}
            from engine.poll_rt import run_poll

            fut = asyncio.ensure_future(run_poll(self.world, self.bus, get_decider(self.llm, self.s), self.gov,
                                                 self.store, cmd, commerce=self.commerce, social=self.social,
                                                 llm=self.llm))
            self._tasks.add(fut)
            fut.add_done_callback(self._tasks.discard)
        elif kind in ("survey_launch", "survey_cancel"):
            if self.surveys is None or self.world is None or self.bus is None:
                return {"ok": False, "error": "survey runtime not running"}
            sid = str(cmd.get("survey_id", ""))
            res = self.surveys.launch(sid) if kind == "survey_launch" else self.surveys.cancel(sid, self.world, self.bus)
            self.bus.new("command", self.world.t, None, {k: v for k, v in cmd.items() if k != "auth"})
            return {**res, "ok": True}
        elif kind == "launch":
            if self.media is None:
                return {"ok": False, "error": "media runtime not running"}
            self.media.request_launch(str(cmd.get("product_id", "")))
        else:
            return {"ok": False, "error": f"unsupported command {kind!r} in this phase"}
        if self.bus is not None and self.world is not None:
            self.bus.new("command", self.world.t, None, {k: v for k, v in cmd.items() if k != "auth"})
        return {"ok": True, "paused": self.clock.paused, "speed": self.clock.speed}
