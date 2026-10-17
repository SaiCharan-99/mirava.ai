"""The deterministic world state and one-minute step (E-01, E-02, P-05, P-06). No I/O, no wall clock."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from engine.events import EventBus
from engine.movement import Router, Seg
from engine.planner import OFFMAP, build_plan
from engine.rng import stream
from population.config import load
from population.genesis import home_spot, snapshot_payload
from population.possessions import daily_hazards, phone_age_years
from shared import time as simtime
from shared.schemas.agent import AgentProfile, AgentState
from world.map import WorldMap

NEEDS = ("energy", "hunger", "social", "fatigue", "stimulation")
WORK_ACTS = {"work", "school", "college", "store_shift", "offmap_work", "roam"}
OUT_ACTS = {"cafe", "eat", "gym", "park", "shop"}
SOCIAL_ACTS = {"cafe", "eat", "park", "school", "college"}
STATE_VERSION = 1


@dataclass
class Agent:
    """Runtime state of one agent (serialised into checkpoints)."""

    id: int
    x: float
    y: float
    heading: float = 0.0
    mode: str = "idle"
    place_id: str | None = None
    activity: str = "sleep"
    plan: list[dict[str, Any]] = field(default_factory=list)
    plan_day: int = 0
    route: list[Seg] = field(default_factory=list)
    route_dest: str | None = None
    offmap: bool = False
    via_metro: bool = False
    offmap_since: int = 0
    dwell_until: int = 0
    mood: float = 0.6
    life_event_at: int = -1
    life_event_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "route"}
        d["route"] = [s.pack() for s in self.route]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Agent:
        """Inverse of to_dict."""
        d = dict(d)
        route = [Seg(*s) for s in d.pop("route", [])]
        a = cls(**d)
        a.route = route
        return a


class World:
    """All mutable world state + `step()` (1 tick = 1 sim minute)."""

    def __init__(self, profiles: list[AgentProfile], metas: dict[int, dict[str, Any]], wm: WorldMap, seed: int,
                 bus: EventBus, *, counts: dict[str, int] | None = None) -> None:
        self.cfg = load("world")
        self.profiles = profiles
        self.pd = [p.model_dump(include={"agent_id", "home_place_id", "workplace_place_id", "routine_id"})
                   for p in profiles]
        self.metas = metas
        self.wm = wm
        self.seed = seed
        self.bus = bus
        self.router = Router(wm, self.cfg["speeds_m_per_min"])
        self.n = len(profiles)
        self.t = 0
        self.agents: list[Agent] = []
        self.needs = np.zeros((self.n, len(NEEDS)), dtype=np.float64)
        self.phones: list[dict[str, Any]] = [dict(p.possessions["phone"]) for p in profiles]
        self.counts = counts or {"agents": self.n, "households": len({p.household_id for p in profiles}),
                                 "relationships": 0}
        self.counters = {"conversations_today": 0, "conversations_total": 0, "thoughts_today": 0}
        self.new_segs: list[dict[str, Any]] = []      # segments started this tick (for /live)
        self.live_evts: list[dict[str, Any]] = []     # evt items this tick (for /live)
        self.products_live: list[dict[str, Any]] = []
        self.sessions: dict[str, Any] = {}

    # ------------------------------------------------------------------ state
    def init_from_states(self, states: list[AgentState]) -> None:
        """Start from genesis states (t = states' t)."""
        self.t = states[0].t if states else 0
        self.agents = [Agent(id=s.agent_id, x=s.x, y=s.y, heading=s.heading, mode=s.mode, place_id=s.place_id,
                             activity=s.activity, mood=s.mood) for s in states]
        for s in states:
            self.needs[s.agent_id] = [s.needs[k] for k in NEEDS]  # type: ignore[index]

    def to_checkpoint(self) -> dict[str, Any]:
        """Full engine state (INTERFACES §4.2)."""
        return {"version": STATE_VERSION, "t": self.t, "world_seed": self.seed,
                "rng_states": {"scheme": "stream(seed, purpose, t|day, agent)"},
                "agents": [a.to_dict() for a in self.agents], "needs": self.needs.round(6).tolist(),
                "phones": self.phones, "segments": [], "sessions": self.sessions, "plans": {},
                "governor": {}, "pending_tasks": [], "products_live": self.products_live,
                "counters": self.counters, "counts": self.counts}

    def load_checkpoint(self, ck: dict[str, Any]) -> None:
        """Restore from `to_checkpoint` output."""
        self.t = int(ck["t"])
        self.agents = [Agent.from_dict(a) for a in ck["agents"]]
        self.needs = np.array(ck["needs"], dtype=np.float64)
        self.phones = ck["phones"]
        self.sessions = ck.get("sessions", {})
        self.products_live = ck.get("products_live", [])
        self.counters = ck.get("counters", self.counters)
        self.counts = ck.get("counts", self.counts)

    def state_hash(self) -> str:
        """Hash of positions, activities, needs and phones (resume checks)."""
        body = json.dumps([[a.id, round(a.x, 2), round(a.y, 2), a.activity, a.mode, a.place_id] for a in self.agents])
        h = hashlib.sha256(body.encode())
        h.update(self.needs.round(6).tobytes())
        h.update(json.dumps(self.phones, sort_keys=True).encode())
        return h.hexdigest()

    # ------------------------------------------------------------------ step
    def step(self) -> None:
        """Advance one sim minute."""
        self.t += 1
        t = self.t
        m = simtime.minute_of_day(t)
        day = simtime.day_of(t)
        self.new_segs = []
        self.live_evts = []
        if m == 0:
            self.counters["conversations_today"] = 0
            self.counters["thoughts_today"] = 0
        for a in self.agents:
            if a.plan_day != day:
                self._new_day(a, day)
            self._act(a, t, m)
        self._needs(m)
        if m == 3 * 60:
            self._snapshots(t)

    def _new_day(self, a: Agent, day: int) -> None:
        """Build today's plan and roll today's phone life event."""
        p = self.pd[a.id]
        a.plan = build_plan(p, self.metas[a.id], day, self.seed)
        a.plan_day = day
        rng = stream(self.seed, "life_event", day, a.id)
        a.life_event_at, a.life_event_type = -1, ""
        ph = self.phones[a.id]
        if ph["condition"] != "lost":
            for kind, prob in sorted(daily_hazards(ph, self.profiles[a.id].persona.lifestyle, self.t).items()):
                if rng.random() < prob:
                    a.life_event_at = (day - 1) * 1440 + int(rng.integers(7 * 60, 22 * 60))
                    a.life_event_type = kind
                    break

    def _block(self, a: Agent, m: int) -> dict[str, Any]:
        for b in a.plan:
            if b["s"] <= m < b["e"]:
                return b
        return a.plan[-1]

    def _act(self, a: Agent, t: int, m: int) -> None:
        """Routine/plan step for one agent: trips, arrivals, activity changes, paydays, life events."""
        if a.route:
            last = a.route[-1]
            if t >= last.t1:
                self._arrive(a, t)
            return
        blk = self._block(a, m)
        target, act = blk["place"], blk["act"]
        if act == "roam":
            if t >= a.dwell_until:
                self._roam(a, t)
            elif a.activity != "roam":
                self._set_activity(a, t, "roam")
        elif target == OFFMAP:
            if not a.offmap:
                self._start_trip(a, t, OFFMAP, act)
            else:
                eff = "metro" if a.via_metro and t - a.offmap_since < 25 else "offmap_work"
                if a.activity != eff:
                    self._set_activity(a, t, eff)
        elif target is not None and (target != a.place_id or a.offmap):
            self._start_trip(a, t, target, act)
        elif a.activity != act:
            self._set_activity(a, t, act)
        if a.life_event_at == t:
            self._life_event(a, t)
        if m == 9 * 60:
            self._payday(a, t)

    def _set_activity(self, a: Agent, t: int, act: str) -> None:
        a.activity = act
        self.bus.new("activity", t, a.id, {"activity": act, "place_id": a.place_id, "mode": a.mode})
        self.live_evts.append({"k": "activity", "a": a.id, "act": act, "place": self._pname(a.place_id)})

    def _pname(self, place_id: str | None) -> str | None:
        """Display name of a non-home place (homes stay anonymous in the ticker)."""
        p = self.wm.place_by_id.get(place_id or "")
        return p.name if p is not None and p.kind != "home" else None

    def _mode_for(self, a: Agent, dist: float) -> str:
        """Travel mode for a trip of `dist` metres."""
        if dist <= self.cfg["walk_max_m"]:
            return "walk"
        mode = self.profiles[a.id].commute_mode
        if mode == "metro":
            return "auto" if dist > 1800 else "walk"
        return mode

    def _start_trip(self, a: Agent, t: int, dest: str, act: str) -> None:
        """Plan a route (possibly via the map edge or the metro station) and announce its segments."""
        prof = self.profiles[a.id]
        area = self.metas[a.id].get("offmap_area")
        segs: list[Seg] = []
        if a.offmap:                                         # re-enter the map
            if a.via_metro:
                sx, sy = self.router.metro_xy
                dx, dy = self._spot(a, dest)
                segs = self.router.leg(sx, sy, dx, dy, "walk", float(t))
            else:
                node = self.router.exit_for(area)
                sx, sy = self.wm.nodes[node]
                dx, dy = self._spot(a, dest)
                segs = self.router.leg(sx, sy, dx, dy, prof.commute_mode, float(t))
            a.offmap = False
            a.via_metro = False
        elif dest == OFFMAP:
            if prof.commute_mode == "metro":
                mx, my = self.router.metro_xy
                segs = self.router.leg(a.x, a.y, mx, my, "walk", float(t))
                a.via_metro = True
            else:
                node = self.router.exit_for(area)
                ex, ey = self.wm.nodes[node]
                mode = prof.commute_mode if prof.commute_mode != "walk" else "auto"
                segs = self.router.leg(a.x, a.y, ex, ey, mode, float(t), end_node=node)
                a.via_metro = False
        else:
            dx, dy = self._spot(a, dest)
            mode = self._mode_for(a, math.dist((a.x, a.y), (dx, dy)))
            segs = self.router.leg(a.x, a.y, dx, dy, mode, float(t))
        a.route = segs
        a.route_dest = dest
        a.place_id = None
        a.mode = segs[0].mode if segs else "walk"
        a.heading = segs[0].heading if segs else a.heading
        if a.activity != "commute":
            self._set_activity(a, t, "commute")
        self.new_segs.extend(s.wire(a.id) for s in segs)

    def _arrive(self, a: Agent, t: int) -> None:
        last = a.route[-1]
        a.x, a.y = last.x1, last.y1
        a.heading = last.heading
        dest = a.route_dest
        a.route = []
        a.route_dest = None
        if dest == OFFMAP:
            a.offmap, a.offmap_since, a.mode, a.place_id = True, t, "offmap", None
            act = "metro" if a.via_metro else "offmap_work"
        else:
            a.mode, a.place_id = "idle", dest
            blk = self._block(a, simtime.minute_of_day(t))
            act = "roam" if blk["act"] == "roam" else blk["act"]
            if blk["place"] not in (dest, None):
                act = blk["act"]
        self.bus.new("arrive", t, a.id, {"place_id": a.place_id, "activity": act})
        a.activity = act
        self.live_evts.append({"k": "activity", "a": a.id, "act": act, "place": self._pname(a.place_id)})

    def _roam(self, a: Agent, t: int) -> None:
        """Gig work: hop to a random shop/restaurant/home nearby, then dwell 4–14 min."""
        rng = stream(self.seed, "roam", t, a.id)
        kinds = ("shop", "restaurant", "cafe", "home")
        near = [p for p in self.wm.places_near(a.x, a.y, 900) if p.kind in kinds]
        if not near:
            near = [self.wm.place_by_id[self.profiles[a.id].home_place_id]]
        dest = near[int(rng.integers(len(near)))].place_id
        a.dwell_until = t + int(rng.integers(4, 15))
        if dest == a.place_id:
            return
        dx, dy = self._spot(a, dest)
        segs = self.router.leg(a.x, a.y, dx, dy, self.profiles[a.id].commute_mode, float(t))
        a.dwell_until += int(segs[-1].t1 - t) if segs else 0
        a.route, a.route_dest, a.place_id = segs, dest, None
        a.mode = segs[0].mode if segs else "walk"
        if a.activity != "roam":
            self._set_activity(a, t, "roam")
        self.new_segs.extend(s.wire(a.id) for s in segs)

    def _spot(self, a: Agent, place_id: str) -> tuple[float, float]:
        """Standing point at a place's entrance (deterministic per agent)."""
        if place_id == self.profiles[a.id].home_place_id:
            return home_spot(self.profiles[a.id], self.wm)
        ex, ey = self.wm.place_by_id[place_id].entrances[0]
        j = (a.id * 104729) % 100
        return round(ex + (j % 10 - 4.5) * 0.8, 1), round(ey + (j // 10 - 4.5) * 0.8, 1)

    def _life_event(self, a: Agent, t: int) -> None:
        """Apply a phone life event (lost / broken / slow)."""
        ph = self.phones[a.id]
        kind = a.life_event_type
        before = ph["condition"]
        ph["condition"] = {"lost": "lost", "broken": "cracked", "slow": "slow"}[kind]
        ph["satisfaction"] = round(max(0.0, ph["satisfaction"] - 0.25), 2)
        ph["history"] = [*ph.get("history", []), {"t": t, "event": kind}]
        self.bus.new("life_event", t, a.id, {"type": kind, "category": "phone", "before": before,
                                             "after": ph["condition"],
                                             "phone_age_years": round(phone_age_years(ph, t), 2)})
        self.live_evts.append({"k": "life_event", "a": a.id, "type": kind})

    def _payday(self, a: Agent, t: int) -> None:
        money = self.profiles[a.id].money
        day = simtime.day_of(t)
        weekly = money.pay_cycle == "weekly"
        due = ((day - 1) % 7 == money.payday) if weekly else (((day - 1) % 30) + 1 == money.payday)
        if due:
            amount = money.monthly_income_inr // 4 if weekly else money.monthly_income_inr
            self.bus.new("payday", t, a.id, {"amount": amount, "cycle": money.pay_cycle})
            self.live_evts.append({"k": "payday", "a": a.id, "amount": amount})

    def _needs(self, m: int) -> None:
        """Vectorised needs drift by activity group; values stay in [0, 1]."""
        acts = [a.activity for a in self.agents]
        sleep = np.array([x == "sleep" for x in acts])
        work = np.array([x in WORK_ACTS for x in acts])
        out = np.array([x in OUT_ACTS or x == "commute" for x in acts])
        social = np.array([x in SOCIAL_ACTS for x in acts])
        eat = np.array([x == "eat" for x in acts]) | (
            np.array([x == "home" for x in acts]) & (m in range(470, 500) or m in range(800, 830) or m in range(1230, 1260)))
        c = self.cfg["needs"]
        n = self.needs
        n[:, 0] += np.where(sleep, c["energy"]["sleep"], np.where(work | out, c["energy"]["active"], c["energy"]["rest"]))
        n[:, 1] += np.where(eat, c["hunger"]["eat"], c["hunger"]["any"])
        n[:, 2] += np.where(social, c["social"]["social"], c["social"]["alone"])
        n[:, 3] += np.where(sleep, c["fatigue"]["sleep"], np.where(work, c["fatigue"]["work"],
                                                                     np.where(out, c["fatigue"]["active"], c["fatigue"]["rest"])))
        n[:, 4] += np.where(out | work, c["stimulation"]["out"], np.where(sleep, 0.0, c["stimulation"]["home"]))
        np.clip(n, 0.0, 1.0, out=n)
        if m % 15 == 0:
            for i, a in enumerate(self.agents):
                e, h, s, f, st = n[i]
                a.mood = round(float(np.clip(0.5 + 0.3 * e - 0.3 * h + 0.2 * s - 0.2 * f + 0.1 * st, 0, 1)), 3)

    def _snapshots(self, t: int) -> None:
        """Daily agent_snapshot events (03:00)."""
        for a in self.agents:
            prof = self.profiles[a.id]
            st = self.agent_state(a.id)
            payload = snapshot_payload(prof.model_copy(update={"possessions": {"phone": self.phones[a.id]}}), st, t)
            self.bus.new("agent_snapshot", t, a.id, payload)

    # ------------------------------------------------------------------ views
    def position(self, a: Agent, t: float) -> tuple[float, float, float]:
        """(x, y, heading) at sim time t, interpolating the current route."""
        for s in a.route:
            if s.t0 <= t < s.t1:
                x, y = s.at(t)
                return x, y, s.heading
        return a.x, a.y, a.heading

    def agent_state(self, i: int) -> AgentState:
        """AgentState model for one agent (current t)."""
        a = self.agents[i]
        x, y, h = self.position(a, float(self.t))
        return AgentState(agent_id=i, t=self.t, x=round(x, 1), y=round(y, 1), heading=h, mode=a.mode,
                          place_id=a.place_id, activity=a.activity,
                          needs={k: round(float(self.needs[i, j]), 3) for j, k in enumerate(NEEDS)},  # type: ignore[misc]
                          mood=a.mood, plan=[{"s": b["s"], "e": b["e"], "act": b["act"], "place": b["place"]}
                                             for b in a.plan])

    def wire_agents(self) -> list[dict[str, Any]]:
        """`hello.agents` items."""
        out = []
        for a in self.agents:
            x, y, h = self.position(a, float(self.t))
            out.append({"id": a.id, "x": round(x, 1), "y": round(y, 1), "h": round(h), "mode": a.mode, "act": a.activity})
        return out

    def wire_segments(self) -> list[dict[str, Any]]:
        """Remaining segments of agents en route."""
        return [s.wire(a.id) for a in self.agents for s in a.route if s.t1 > self.t]

    def stats(self, budget: dict[str, float] | None = None) -> dict[str, Any]:
        """`stats` frame body (W-09)."""
        return {"type": "stats", "t": self.t,
                "counts": {**self.counts, **self.counters, "products_live": len(self.products_live)},
                "budget": budget or {"used_usd": 0.0, "cap_usd": 15.0}, "awareness": {}}
