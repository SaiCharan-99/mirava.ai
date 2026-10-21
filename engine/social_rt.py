"""Engine-side social runtime: encounters → gate → sessions → queued conversations, working memory, reflection."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any

from engine.encounters import EncounterTracker, Presence
from engine.events import EventBus
from engine.governor import BudgetGovernor
from engine.planner import insert_block
from engine.rng import stream
from engine.tasks import TaskQueue
from engine.world import World
from mind.decision import DecisionAdapter, DecisionRequest, DecisionResult, FakeDecision
from mind.memory import MemoryStore, embed_cached
from mind.opinion import attrs_in
from mind.reflect import THRESHOLD, day_importance, reflect
from population.config import load
from shared import time as simtime
from shared.llm import LLMClient
from shared.schemas.events import Event
from shared.schemas.memory import MemoryEntry
from shared.store import DocStore
from shared.subjects import canonical
from social.agenda import Agenda
from social.conversation import ConvExtras, Outcome, Participant, run_conversation, template_memories, unrendered
from social.gate import GateResult, Side, gate, topics_for
from social.meetups import plan_meetups
from social.remote import friends_online, pick_partner, wants_to_text
from social.sessions import SessionRegistry
from social.stop import LONG_MIN, MODE_RECOGNISE, QUICK_MIN, StopCtx, decide_stop, urgency
from social.wom import tell

log = logging.getLogger("engine.social")
WM_MAX = 20
CONV_DELAY = 10              # sim minutes until a conversation's result is applied (~25 s real at 1 day/h)
STREET_RADIUS = 30.0         # metres: close enough to spot someone you know across the road
STREET_COOLDOWN = 180        # sim minutes before the same pair can stop for each other again
STREET_RETRY = 20            # a pair that passed without recognising each other is not re-drawn for this long
REFLECT_DELAY = 30
REFLECT_AT = 3 * 60
FREE = {"cafe": 1.0, "eat": 0.9, "park": 1.0, "home": 0.8, "gym": 0.5, "shop": 0.6, "roam": 0.2}
TEXT_KINDS = {"message", "share_plan", "debrief", "reflection"}
REL_LABEL = {"family": "family", "partner": "partners", "friend": "friends", "colleague": "colleagues",
             "neighbour": "neighbours"}


class MicroBatcher:
    """Collects `decide` calls made in the same loop turn and sends them as one `decide_batch`."""

    def __init__(self, inner: DecisionAdapter) -> None:
        self.inner = inner
        self._q: list[tuple[DecisionRequest, asyncio.Future]] = []

    async def decide(self, req: DecisionRequest) -> DecisionResult:
        """Queue one request; resolved by the next flush."""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        if not self._q:
            asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self._flush()))
        self._q.append((req, fut))
        return await fut

    async def decide_batch(self, reqs: list[DecisionRequest]) -> list[DecisionResult]:
        """Pass-through."""
        return await self.inner.decide_batch(reqs)

    async def _flush(self) -> None:
        q, self._q = self._q, []
        try:
            res = await self.inner.decide_batch([r for r, _ in q])
            for (_, f), r in zip(q, res, strict=True):
                if not f.done():                  # the caller may have been cancelled or timed out
                    f.set_result(r)
        except Exception as e:  # noqa: BLE001
            for _, f in q:
                if not f.done():
                    f.set_exception(e)


class SocialRuntime:
    """Runs after every World.step(); all results land at deterministic sim times via the TaskQueue."""

    def __init__(self, store: DocStore, llm: LLMClient, decider: DecisionAdapter, governor: BudgetGovernor,
                 relationships: list[dict[str, Any]], *, watched: set[int] | None = None,
                 embed_texts: bool = True, opinion: Any = None) -> None:
        self.store = store
        self.llm = llm
        self.decider = MicroBatcher(decider)
        self.gate_decider = FakeDecision()          # talk/skip is rule-based: no I/O inside the tick (DECISIONS #75)
        self.gov = governor
        self.rel: dict[tuple[int, int], dict[str, Any]] = {}
        for r in relationships:
            if r.get("kind") != "follower":
                self.rel[(min(r["a"], r["b"]), max(r["a"], r["b"]))] = r
        self.tracker = EncounterTracker()
        self.sessions = SessionRegistry()
        self._speech: list[tuple[int, dict[str, Any]]] = []
        # turn-by-turn chats make ~20 sequential calls; a few at a time finish, many at once all starve on ICA's slots
        self.queue = TaskQueue(concurrency=8, timeout_s=150.0, queue_wait_s=900.0)
        self.wm: dict[int, list[dict[str, Any]]] = {}
        self.agenda = Agenda()                             # what is on each person's mind to tell people
        self.name_of: Callable[[int], str] = lambda aid: f"Agent {aid}"          # first name (set by the engine)
        self.product_name_of: Callable[[str], str] = lambda pid: pid              # product display name (set by the engine)
        self.intent_hook: Callable[[int, str], None] | None = None               # plan intents → commerce (set by the engine)
        self.on_phone: Callable[[int, int], bool] = lambda aid, m: False         # is this person scrolling their phone now
        self.visible_fn: Callable[[float, float, int], tuple[str, str] | None] | None = None   # campaign board in view
        self._street_tried: dict[tuple[int, int], int] = {}
        self.survey_hook: Callable[[int, int, float, str], None] | None = None   # survey invite passed on (set by the engine)
        self.errands: Any = None                                      # the commerce runtime's Errands (set by the engine)
        self._online = friends_online(self.rel)                      # who can text whom
        self._feed_at: dict[int, list[int]] | None = None            # minute of day → people starting a phone session
        self._remote_last: dict[tuple[int, int], int] = {}
        self._remote_today = 0
        self._meet_pairs = [(a, b, float(r["closeness"])) for (a, b), r in sorted(self.rel.items())
                            if r.get("kind") in ("friend", "partner") and float(r.get("closeness", 0.0)) >=
                            float(load("social")["meetups"]["min_closeness"])]
        self.watched = watched or set()
        self.opinion = opinion                                     # OpinionEngine (None: no computed opinions)
        self.catalog_fn: Callable[[], dict[str, str]] | None = None   # product id → name (set by the engine)
        self.embed_texts = embed_texts
        self._pclass: dict[str, str] = {}
        self._bg: set[asyncio.Future] = set()
        self.stats = {"rendered": 0, "unrendered": 0, "reflections": 0, "cost_usd": 0.0, "street_pairs": 0,
                      "street_recognised": 0, "street_nod": 0, "street_quick": 0, "street_long": 0}

    # ------------------------------------------------------------------ working memory (L1)
    def remember(self, aid: int, text: str, importance: int, kind: str, t: int, tag: str | None = None) -> None:
        """Add to today's buffer (≤ 20 newest)."""
        buf = self.wm.setdefault(aid, [])
        buf.append({"t": t, "text": text, "importance": importance, "kind": kind, "tag": tag})
        del buf[:-WM_MAX]

    def on_event(self, ev: Event) -> None:
        """Bus listener: life events enter working memory."""
        if ev.kind == "life_event" and ev.agent_id is not None:
            typ = ev.payload.get("type", "")
            self.remember(ev.agent_id, f"My phone got {typ} today.", 5, "life_event", ev.t, tag=f"phone {typ}")
            self.agenda.add(ev.agent_id, "phone_trouble", ev.t, hint=f"phone {typ}", about=typ)

    # ------------------------------------------------------------------ per tick
    def presences(self, w: World) -> list[Presence]:
        """Available agents standing at a place (not travelling, sleeping, off-map or in a session)."""
        return [Presence(a.id, a.x, a.y, a.place_id) for a in w.agents
                if not a.route and not a.offmap and a.place_id and a.activity not in ("sleep", "commute")
                and not self.sessions.busy(a.id) and w.t >= a.talk_until]

    def side(self, w: World, aid: int) -> Side:
        """Gate view of one agent (tags only, never private text)."""
        prof = w.profiles[aid]
        tags = [e["tag"] for e in self.wm.get(aid, []) if e.get("tag")]
        hints = self.agenda.hints(aid, 3, w.t)
        return Side(aid, list(prof.persona.interests), salient=list(dict.fromkeys([*hints, *tags]))[-3:],
                    products_salient=self.agenda.product_ids(aid, w.t),
                    free=FREE.get(w.agents[aid].activity, 0.3), watched=aid in self.watched)

    async def tick(self, w: World, bus: EventBus) -> None:
        """Gate new encounters, apply finished conversations/reflections, run the nightly job."""
        t = w.t
        await self._apply(w, bus, t)
        w.live_evts.extend(event for due, event in self._speech if due <= t)
        self._speech = [(due, event) for due, event in self._speech if due > t]
        self.sessions.expire(t)
        pairs = self.tracker.update(t, self.presences(w))
        if pairs:
            await asyncio.gather(*(self._encounter(w, bus, a, b, t) for a, b in pairs))
        await self._street(w, bus, t)
        await self._remote(w, bus, t)
        if simtime.minute_of_day(t) == 7 * 60:
            self._plan_meetups(w, bus, t)
        if simtime.minute_of_day(t) == REFLECT_AT:
            self._nightly(w, bus, t)

    # ------------------------------------------------------------------ phone chats (people who are apart)
    async def _remote(self, w: World, bus: EventBus, t: int) -> None:
        """At the start of a phone session someone with something on their mind may text a friend."""
        m = simtime.minute_of_day(t)
        cfg = load("social")["remote"]
        if m == 0:
            self._remote_today = 0
        if self._feed_at is None:
            self._feed_at = {}
            for p in w.profiles:
                for start, _minutes, _app in p.media.feed_sessions:
                    self._feed_at.setdefault(int(start), []).append(p.agent_id)
        if self._remote_today >= int(cfg["max_per_day"]):
            return
        seed = int(getattr(self.opinion, "seed", 0))
        for aid in self._feed_at.get(m, []):
            a = w.agents[aid]
            if a.activity == "sleep" or self.sessions.busy(aid) or t < a.talk_until or aid not in self._online:
                continue
            rng = stream(seed, "remote", t, aid)
            top = self.agenda.top(aid, 1, None, t)
            if not wants_to_text(top[0].weight if top else 0.0, float(w.needs[aid, 2]),
                                 float(w.profiles[aid].persona.big5.get("E", 0.5)), float(rng.random()), cfg):
                continue
            awake = {o for o, _ in self._online[aid] if w.agents[o].activity != "sleep" and not self.sessions.busy(o)
                     and t >= w.agents[o].talk_until
                     and t - self._remote_last.get((min(aid, o), max(aid, o)), -10**9) >= int(cfg["pair_cooldown_min"])}
            other = pick_partner(self._online[aid], awake, float(rng.random()))
            if top and top[0].kind == "errand_question" and top[0].target_id in awake:
                other = top[0].target_id                              # I'm buying them a phone: ask them
            if other is None:
                continue
            self._remote_last[(min(aid, other), max(aid, other))] = t
            self._remote_today += 1
            await self._phone_chat(w, bus, aid, other, t, float(cfg["est_cost_usd"]))
            if self._remote_today >= int(cfg["max_per_day"]):
                return

    async def _phone_chat(self, w: World, bus: EventBus, ia: int, ib: int, t: int, est: float) -> None:
        pair = (min(ia, ib), max(ia, ib))
        rel = self.rel.get(pair)
        topics, product = topics_for(self.side(w, ia), self.side(w, ib))
        closeness = float((rel or {}).get("closeness", 0.0))
        rendered = self.gov.allow("P4", est)
        g = GateResult(pair, True, "social", topics, "phone chat", 2.0 * (product is not None) + closeness, "P4",
                       rendered, product)
        bus.new("gate", t, pair[0], {**g.payload(), "channel": "phone"}, other_id=pair[1], rendered=rendered)
        await self._converse(w, bus, g, ia, ib, t, rel=rel, pname="WhatsApp", where="on WhatsApp", remote=True)

    # ------------------------------------------------------------------ planned meetups
    def _plan_meetups(self, w: World, bus: EventBus, t: int) -> None:
        """07:00: friends who agree to meet get a café or park hour in both of today's plans."""
        cfg = load("social")["meetups"]
        day = simtime.day_of(t)
        weekend = (day - 1) % 7 >= 5
        seed = int(getattr(self.opinion, "seed", 0))
        meets = plan_meetups(
            self._meet_pairs, day=day, weekend=weekend, seed=seed, cfg=cfg,
            extraversion=lambda x: float(w.profiles[x].persona.big5.get("E", 0.5)),
            satisfaction=lambda x: float(w.needs[x, 2]),
            plan_of=lambda x: w.agents[x].plan if w.agents[x].plan_day == day else [],
            haunts=lambda x, k: list((w.metas[x].get("haunts") or {}).get(k) or []))
        for mt in meets:
            place = w.wm.place_by_id.get(mt.place_id)
            pname = place.name if place else "a café"
            for me, other in ((mt.a, mt.b), (mt.b, mt.a)):
                ag = w.agents[me]
                ag.plan = insert_block(ag.plan, mt.start, mt.start + mt.minutes, mt.act, mt.place_id)
                self.remember(me, f"Meeting {self.name_of(other)} at {pname} later today.", 3, "conversation", t)
            bus.new("meetup_planned", t, mt.a, {"place_id": mt.place_id, "act": mt.act, "start_minute": mt.start,
                                                "minutes": mt.minutes}, other_id=mt.b, rendered=False)
            w.live_evts.append({"k": "meetup_planned", "a": mt.a, "b": mt.b, "place": pname,
                                "at": f"{mt.start // 60:02d}:{mt.start % 60:02d}"})

    # ------------------------------------------------------------------ street (people on the move who know each other)
    async def _street(self, w: World, bus: EventBus, t: int) -> None:
        """Walkers (and riders) who pass someone they know may notice them; then decide to nod, stop briefly or chat."""
        movers = [a for a in w.agents if a.route and not a.offmap and a.mode in MODE_RECOGNISE
                  and not self.sessions.busy(a.id) and t >= a.talk_until]
        if len(movers) < 2:
            return
        cell = STREET_RADIUS
        pos = {a.id: w.position(a, float(t))[:2] for a in movers}
        grid: dict[tuple[int, int], list[int]] = {}
        for aid, (x, y) in pos.items():
            grid.setdefault((int(x // cell), int(y // cell)), []).append(aid)
        cands: set[tuple[int, int]] = set()
        for (cx, cy), ids in grid.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for q in grid.get((cx + dx, cy + dy), []):
                        for p in ids:
                            if p < q and (p, q) in self.rel and math.dist(pos[p], pos[q]) <= STREET_RADIUS:
                                cands.add((p, q))
        if not cands:
            return
        self._street_tried = {k: v for k, v in self._street_tried.items() if t - v < STREET_RETRY}
        seed = int(getattr(self.opinion, "seed", 0))
        m = simtime.minute_of_day(t)
        used: set[int] = set()
        for ia, ib in sorted(cands):
            if ia in used or ib in used or (ia, ib) in self._street_tried:
                continue
            if t - self.tracker.last_met.get((ia, ib), -10**9) < STREET_COOLDOWN:
                continue
            a, b = w.agents[ia], w.agents[ib]
            rel = self.rel[(ia, ib)]
            closeness = float(rel.get("closeness", 0.0))
            rng = stream(seed, "street", t, ia, ib)
            self._street_tried[(ia, ib)] = t
            self.stats["street_pairs"] += 1
            p_rec = (0.75 * min(MODE_RECOGNISE[a.mode], MODE_RECOGNISE[b.mode]) * (0.6 + 0.4 * closeness)
                     * (0.5 if (self.on_phone(ia, m) or self.on_phone(ib, m)) else 1.0))
            if rng.random() >= p_rec:
                continue
            self.stats["street_recognised"] += 1
            ua = urgency(w._block(a, m).get("act"), a.activity, a.mode)
            ub = urgency(w._block(b, m).get("act"), b.activity, b.mode)
            ta, tb = self.agenda.pick_to_tell(ia, ib, t), self.agenda.pick_to_tell(ib, ia, t)
            last = self.tracker.last_met.get((ia, ib))
            ctx = StopCtx(closeness=closeness, hurry=max(ua, ub), agenda=max(ta.weight if ta else 0.0, tb.weight if tb else 0.0),
                          social_need=1.0 - float((w.needs[ia, 2] + w.needs[ib, 2]) / 2), mood=(a.mood + b.mood) / 2,
                          days_since_met=7.0 if last is None else (t - last) / 1440.0,
                          jitter=float(rng.random() - 0.5) * 0.16)
            outcome = decide_stop(ctx)
            if outcome == "ignore":
                continue
            used.update((ia, ib))
            self.stats[f"street_{outcome}"] += 1
            if outcome == "nod":
                self.tracker.met((ia, ib), t)
                self._greet(w, bus, ia, ib, t)
                continue
            lo, hi = QUICK_MIN if outcome == "quick" else LONG_MIN
            hold = int(rng.integers(lo, hi + 1))
            await self._encounter(w, bus, ia, ib, t, street={"hold": hold, "kind": outcome})
            if outcome == "long":
                self._maybe_coffee(w, ia, ib, t, hold, rng)

    def _greet(self, w: World, bus: EventBus, ia: int, ib: int, t: int) -> None:
        """A wave or a nod in passing: no model, a faint memory for each."""
        bus.new("greet", t, ia, {"mode_a": w.agents[ia].mode, "mode_b": w.agents[ib].mode}, other_id=ib, rendered=False)
        for me, other in ((ia, ib), (ib, ia)):
            self.remember(me, f"Waved to {self.name_of(other)} on the road.", 1, "conversation", t)
        if ia in self.watched or ib in self.watched:
            w.live_evts.append({"k": "greet", "a": ia, "b": ib})

    def _maybe_coffee(self, w: World, ia: int, ib: int, t: int, hold: int, rng: Any) -> None:
        """After a long chat, friends with free time may go for a coffee together (a café block in both plans)."""
        pa, pb = w.profiles[ia].persona.big5, w.profiles[ib].persona.big5
        rel = self.rel.get((ia, ib)) or {}
        p = 0.15 + 0.35 * float(rel.get("closeness", 0.0)) * (float(pa.get("E", 0.5)) + float(pb.get("E", 0.5)))
        if float(rng.random()) >= p:
            return
        a = w.agents[ia]
        cafes = [x for x in w.wm.places_near(a.x, a.y, 400, {"cafe"})]
        m = simtime.minute_of_day(t)
        start = m + hold + 8
        if not cafes or start + 45 >= 1440:
            return
        cafe = cafes[int(rng.integers(len(cafes)))]
        for x in (ia, ib):
            ag = w.agents[x]
            ag.plan = insert_block(ag.plan, start, start + 40, "cafe", cafe.place_id)
        w.live_evts.append({"k": "meetup", "a": ia, "b": ib, "place": cafe.name})

    async def _encounter(self, w: World, bus: EventBus, ia: int, ib: int, t: int,
                         street: dict[str, Any] | None = None) -> None:
        self.tracker.met((ia, ib), t)
        pair = (min(ia, ib), max(ia, ib))
        rel = self.rel.get(pair)
        place = None if street else w.wm.place_by_id.get(w.agents[ia].place_id or "")
        vis = None
        if self.visible_fn is not None and rel is not None:                  # friends chatting in front of a campaign board
            ax, ay = w.position(w.agents[ia], float(t))[:2]
            vis = self.visible_fn(ax, ay, t)
        g = await gate(self.side(w, ia), self.side(w, ib), rel, place.kind if place else None, t, self.gate_decider,
                       self.gov, force_talk=street is not None, extra_product=vis[0] if vis else None)
        bus.new("gate", t, pair[0], g.payload(), other_id=pair[1], rendered=g.rendered)
        if not g.talk:
            return
        pname = "the street" if street else ((place.name if place else "the street")
                                             if place and place.kind != "home" else "home")
        where = "the street" if street else w._pname(w.agents[ia].place_id)
        await self._converse(w, bus, g, ia, ib, t, rel=rel, pname=pname, where=where, street=street, vis=vis)

    async def _converse(self, w: World, bus: EventBus, g: Any, ia: int, ib: int, t: int, *, rel: dict[str, Any] | None,
                        pname: str, where: str | None, street: dict[str, Any] | None = None,
                        vis: tuple[str, str] | None = None, remote: bool = False) -> None:
        """Open the session, stop the people (unless it is a phone chat), then render the talk or note it briefly."""
        hold = int(street["hold"]) if street else 0
        delay = max(CONV_DELAY, hold)
        sid = self.sessions.open([ia, ib], g.kind, t=t, timeout=delay + 15)
        if sid is None:
            return
        if not remote:
            for x in (ia, ib):
                if not (street and w.hold(w.agents[x], t, hold)):          # on the street: stop where they stand
                    w.agents[x].talk_until = t + delay
        pa = self._participant(w, ia)
        pb = self._participant(w, ib)
        w.live_evts.append({"k": "talk", "a": ia, "b": ib, "session_id": sid, "topic": g.topics[0] if g.topics else "",
                            "rendered": g.rendered, "place": where})
        if not g.rendered:
            out = await unrendered(sid, pa, pb, g, t, None)
            if remote:
                out.events[0]["payload"]["channel"] = "phone"
            self._background(asyncio.to_thread(template_memories, self.store, sid, pa, pb, g, t))
            self._emit(w, bus, out, t, g.priority_class)
            return
        pids = [x.split(":", 1)[1] for x in g.topics if x.startswith("product:")]
        opinions = ({ia: self.opinion.brief_many(ia, pids), ib: self.opinion.brief_many(ib, pids)}
                    if self.opinion is not None and pids else None)
        rel_label = REL_LABEL.get((rel or {}).get("kind", ""), "strangers")
        closeness = float((rel or {}).get("closeness", 0.0))
        extras = self._extras(w, g, ia, ib, t, closeness, pids, vis, street, remote)
        fallback_gate = g

        def fallback() -> Outcome:
            return Outcome(sid, rendered=False, minutes=5, events=[{
                "kind": "interaction", "agent_id": ia, "other_id": ib,
                "payload": {"topic": fallback_gate.topics[0] if fallback_gate.topics else "small talk",
                            "minutes": 5, "conv_kind": fallback_gate.kind, "fallback": True}}])

        self.queue.submit(sid, lambda: run_conversation(sid, pa, pb, g, rel_label, closeness, pname, t,
                                                        store=self.store, llm=self.llm, decider=self.decider,
                                                        catalog=self.catalog_fn() if self.catalog_fn else None,
                                                        opinions=opinions, extras=extras),
                          t, delay, fallback)
        self._pclass[sid] = g.priority_class

    def _extras(self, w: World, g: Any, ia: int, ib: int, t: int, closeness: float, pids: list[str],
                vis: tuple[str, str] | None, street: dict[str, Any] | None, remote: bool = False) -> ConvExtras:
        """Per-agent texts built only from that agent's own state: what's on their mind, and what they'd say aloud."""
        minds: dict[int, str] = {}
        stances: dict[int, str] = {}
        for me, other in ((ia, ib), (ib, ia)):
            items = self.agenda.top(me, 2, other, t)
            minds[me] = "\n".join(f"- {i.public_hint or i.kind}" + (f": {i.about}" if i.about else "") for i in items)
            if self.opinion is not None:
                lines = []
                for pid in pids:
                    if pid not in self.opinion.catalog or not self.opinion.aware_of(me, pid):
                        continue
                    pub, note = self.opinion.expressed(me, pid, closeness)
                    priv = self.opinion.private_attitude(me, pid)
                    lines.append(f"{self.product_name_of(pid)}: privately {priv:+.1f}, aloud I'd say {pub:+.1f}."
                                 + (f" ({note})" if note else ""))
                stances[me] = "\n".join(lines)
        visible = ""
        if vis:
            visible = f"the {self.product_name_of(vis[0])} hoarding is right there" + (f": “{vis[1]}”" if vis[1] else "")
        watched = ia in self.watched or ib in self.watched
        if remote:
            cap = 3                                      # a text exchange is short
        elif street:
            cap = 3 if street["kind"] == "quick" else 8
        else:
            cap = 6
        return ConvExtras(minds=minds, stances=stances, visible="" if remote else visible,
                          turn_by_turn=(bool(g.product) or watched) and not remote,
                          max_msgs=None if g.kind == "stranger" else cap)

    def _participant(self, w: World, aid: int) -> Participant:
        prof = w.profiles[aid]
        a = w.agents[aid]
        now = f"{simtime.fmt(w.t)}; {a.activity} at {w._pname(a.place_id) or 'home'}; mood {a.mood:.2f}"
        return Participant(aid, prof.name.split()[0], prof.persona.speaking_style, now)

    async def _apply(self, w: World, bus: EventBus, t: int) -> None:
        for key, res in await self.queue.collect(t):
            if key.startswith("refl:"):
                aid = int(key.split(":")[1])
                if res is not None:
                    payload, cost = res
                    ev = bus.new("reflection", t, aid, payload)
                    self._background(asyncio.to_thread(self.store.set, f"agents/{aid}/thoughts", ev.event_id, {
                        "t": t, "label": simtime.fmt(t), "kind": "reflection", "agent_id": aid,
                        "trigger": {"channel": "reflection"}, "text": payload["text"], "product_id": None,
                        "attitude_delta": None}))
                    self.gov.record(cost, "P3")
                    self.stats["cost_usd"] += cost
                    self.stats["reflections"] += 1
                    await self._texts(bus, [("reflection", aid, None, payload["text"], t)])
                continue
            self._emit(w, bus, res, t, self._pclass.pop(key, "P4"))
            self.sessions.close(key)

    def _emit(self, w: World, bus: EventBus, out: Outcome, t: int, pclass: str) -> None:
        """Emit an outcome's events, texts, live items and working-memory notes."""
        texts: list[tuple[str, int, str | None, str, int]] = []
        emitted: list[Event] = []
        for spec in out.events:
            ev = bus.new(spec["kind"], t, spec["agent_id"], spec["payload"], other_id=spec.get("other_id"),
                         session_id=out.session_id, rendered=out.rendered)
            emitted.append(ev)
            p = spec["payload"]
            if spec["kind"] == "message":
                texts.append(("message", ev.agent_id or 0, ev.event_id, p["text"], t))
            elif spec["kind"] == "share_plan":
                texts.append(("share_plan", ev.agent_id or 0, ev.event_id,
                              " | ".join(c["text"] for c in p.get("candidates", [])), t))
            elif spec["kind"] == "debrief":
                texts.append(("debrief", ev.agent_id or 0, ev.event_id, f"{p['reaction']} {p['summary']}", t))
                self.remember(ev.agent_id or 0, p["summary"], int(p.get("importance", 3)), "conversation", t)
                self._apply_heard(ev.agent_id, spec.get("other_id"), p)
                self._apply_intents(ev.agent_id or 0, p, t)
                self._note_requirements(ev.agent_id, spec.get("other_id"), p)
            elif spec["kind"] == "interaction":
                for x in (spec["agent_id"], spec.get("other_id")):
                    if x is not None:
                        self.remember(x, f"Chatted briefly about {p['topic']}.", 2, "conversation", t)
                if spec.get("other_id") is not None:
                    self._wom_exchange(bus, spec["agent_id"], spec["other_id"], t)
        self._background(asyncio.to_thread(self._persist, out, emitted, t))
        if out.messages:
            first = out.messages[0]
            w.live_evts.append({"k": "bubble", "session_id": out.session_id, "a": first.speaker, "b": first.listener,
                                "text": first.text, "n": len(out.messages)})
            for i, message in enumerate(out.messages[1:], 1):
                self._speech.append((t + i * 2, {"k": "bubble", "session_id": out.session_id,
                    "a": message.speaker, "b": message.listener, "text": message.text,
                    "seq": i, "n": len(out.messages)}))
            w.counters["chats_rendered_today"] = w.counters.get("chats_rendered_today", 0) + 1
        # every talk counts (written chats and brief "interaction" ones), not just model-written dialogue
        w.counters["conversations_today"] += 1
        w.counters["conversations_total"] = w.counters.get("conversations_total", 0) + 1
        self.stats["rendered" if out.rendered else "unrendered"] += 1
        if out.cost_usd:
            self.gov.record(out.cost_usd, pclass)
            self.stats["cost_usd"] += out.cost_usd
        if texts:
            self._background(self._texts(bus, texts, out.session_id))

    def _wom_exchange(self, bus: EventBus, ia: int, ib: int, t: int) -> None:
        """A chat nobody wrote: each side still brings up their strongest unheard item (rules, no model)."""
        rel = self.rel.get((min(ia, ib), max(ia, ib)))
        closeness = float((rel or {}).get("closeness", 0.1))
        seed = int(getattr(self.opinion, "seed", 0))
        for teller, listener in ((ia, ib), (ib, ia)):
            told = tell(self.agenda, self.opinion, teller, listener, closeness, t, name_of=self.name_of,
                        product_name=self.product_name_of, seed=seed)
            if told is None:
                continue
            bus.new("wom", t, listener, {"teller": teller, "kind": told.kind, "product_id": told.product_id,
                                         "attrs": told.attrs, "hint": told.hint}, other_id=teller,
                    product_id=told.product_id, rendered=False)
            if told.kind == "survey_invite" and self.survey_hook is not None:     # a friend mentioned the paid session
                self.survey_hook(listener, teller, closeness, told.about)
            self.remember(listener, told.memory, 3, "conversation", t, tag=told.hint or None)
            self._background(asyncio.to_thread(self._wom_memory, listener, teller, told, t))

    def _wom_memory(self, listener: int, teller: int, told: Any, t: int) -> None:
        """Runs in a worker thread: the listener's own episodic memory of what they heard, and (for a product they had
        not heard of) first-heard on their belief."""
        ms = MemoryStore(listener, self.store)
        ms.add_many([MemoryEntry(
            mid=f"wom-{t}-{teller}-{listener}", agent_id=listener, t=t, kind="conversation", text=told.memory,
            importance=3 if told.product_id else 2, source={"channel": "word_of_mouth", "person_id": teller},
            entities=[self.name_of(teller)], event_refs=[])])
        if told.product_id:
            asyncio.run(self._first_heard(ms, listener, teller, told.product_id, t))

    @staticmethod
    async def _first_heard(ms: MemoryStore, listener: int, teller: int, pid: str, t: int) -> None:
        prev = await ms.beliefs([f"product:{pid}"])
        if not prev or prev[0].awareness == "unaware":
            await ms.update_belief(f"product:{pid}", {
                "awareness": "heard", "stage": "aware", "t": t, "sources_seen": {"word_of_mouth": 1},
                "first_heard": {"channel": "word_of_mouth", "t": t, "person_id": teller}},
                cause_event_id=f"wom-{t}-{teller}-{listener}")

    def _note_requirements(self, listener: int | None, teller: int | None, payload: dict[str, Any]) -> None:
        """If I am buying a phone for the person I just talked to and they SAID what they want, my errand now knows."""
        if self.errands is None or listener is None or teller is None:
            return
        attrs = attrs_in(" ".join(str(x) for x in payload.get("requirements") or []))
        if attrs and self.errands.note_requirements(listener, teller, attrs) is not None:
            for it in self.agenda.items.get(listener, []):          # no need to keep asking
                if it.kind == "errand_question" and it.target_id == teller:
                    it.weight = 0.0

    def _apply_intents(self, aid: int, payload: dict[str, Any], t: int) -> None:
        """What the person decided in a debrief becomes agenda items and nudges commerce (rules on their own words)."""
        for raw in payload.get("intents") or []:
            low = str(raw).lower()
            if any(k in low for k in ("tell ", "share", "message ", "text ", "call ", "let ", "mention")):
                target = next((o for (a, b) in self.rel if aid in (a, b) for o in [b if a == aid else a]
                               if self.name_of(o).lower() in low), None)
                self.agenda.add(aid, "wants_to_tell", t, hint="something to share", target_id=target,
                                about=str(raw)[:80])
            if any(k in low for k in ("store", "shop", "visit", "try", "check it")) and self.intent_hook:
                self.intent_hook(aid, "visit")
            if any(k in low for k in ("research", "look up", "read", "review", "compare")) and self.intent_hook:
                self.intent_hook(aid, "research")

    def _apply_heard(self, listener: int | None, teller: int | None, payload: dict[str, Any]) -> None:
        """What the other person said aloud about a product becomes word-of-mouth evidence, weighted by closeness.
        Applied here (at the deterministic apply time), never inside the model task."""
        if self.opinion is None or self.catalog_fn is None or listener is None:
            return
        catalog = self.catalog_fn()
        rel = self.rel.get((min(listener, teller), max(listener, teller))) if teller is not None else None
        closeness = float((rel or {}).get("closeness", 0.1))
        for c in payload.get("heard_claims") or []:
            subj = canonical(str(c.get("subject", "")), catalog)
            if not subj or not subj.startswith("product:"):
                continue
            strength = max(0.0, min(1.0, float(c.get("strength", 0.5))))
            value = 0.5 + 0.4 * strength if c.get("direction") == "+" else 0.5 - 0.4 * strength
            self.opinion.evidence(listener, subj.split(":", 1)[1], {str(c.get("attribute")): value},
                                  "word_of_mouth", closeness=closeness, strength=0.5 + 0.5 * strength)
        for d in payload.get("belief_deltas") or []:
            subj = canonical(str(d.get("subject", "")), catalog)
            if subj and subj.startswith("product:"):
                pid = subj.split(":", 1)[1]
                self.opinion.evidence(listener, pid, [], "word_of_mouth", closeness=closeness)   # now I know of it
                self.opinion.add_reaction(listener, pid, float(d.get("attitude_delta") or 0.0))

    def _background(self, coro: Awaitable[Any]) -> None:
        """Fire-and-forget with a strong reference (best-effort side writes)."""
        fut = asyncio.ensure_future(coro)
        self._bg.add(fut)
        fut.add_done_callback(self._bg.discard)

    def _persist(self, out: Outcome, events: list[Event], t: int) -> None:
        """Firestore read models for the profile: `conversations/{sid}` and `agents/{id}/thoughts/{eid}`."""
        conv = next((e for e in events if e.kind in ("conversation", "interaction")), None)
        if conv is None:
            return
        private: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.kind in ("share_plan", "debrief") and e.agent_id is not None:
                private.setdefault(str(e.agent_id), {})[e.kind] = e.payload
        msgs = [{"seq": e.payload["seq"], "speaker": e.payload["speaker"], "listener": e.payload["listener"],
                 "text": e.payload["text"], "t": e.t, "event_id": e.event_id} for e in events if e.kind == "message"]
        participants = sorted({x for x in (conv.agent_id, conv.other_id) if x is not None})
        summary = conv.payload if conv.kind == "conversation" else {
            "session_id": out.session_id, "participants": participants, "kind": conv.payload.get("conv_kind"),
            "t_start": t, "t_end": t + out.minutes, "topics": [conv.payload.get("topic")], "n_messages": 0,
            "rendered": False}
        self.store.set("conversations", out.session_id, {"session_id": out.session_id, "participants": participants,
                                                         "t": t, "conversation": summary, "messages": msgs,
                                                         "private": private})
        for me in participants:
            other = next((x for x in participants if x != me), None)
            self.store.set(f"agents/{me}/conversations", out.session_id, {
                "session_id": out.session_id, "with": other, "kind": summary.get("kind"), "t": t,
                "label": simtime.fmt(t), "topics": summary.get("topics") or [], "n_messages": summary.get("n_messages", 0),
                "rendered": bool(summary.get("rendered")), "first_line": msgs[0]["text"] if msgs else ""})
        for e in events:
            if e.kind != "debrief" or e.agent_id is None:
                continue
            deltas = e.payload.get("belief_deltas") or []
            prod = next((d["subject"].split(":", 1)[1] for d in deltas if d["subject"].startswith("product:")), None)
            self.store.set(f"agents/{e.agent_id}/thoughts", e.event_id, {
                "t": e.t, "label": simtime.fmt(e.t), "kind": "debrief", "agent_id": e.agent_id,
                "trigger": {"channel": "conversation", "session_id": out.session_id},
                "text": e.payload.get("reaction", ""), "product_id": prod,
                "attitude_delta": round(sum(float(d["attitude_delta"]) for d in deltas), 2) if deltas else None})

    async def _texts(self, bus: EventBus, rows: list[tuple[str, int, str | None, str, int]],
                     session_id: str | None = None) -> None:
        """`texts` rows with 768-d embeddings (M-01)."""
        vecs: list[list[float] | None] = [None] * len(rows)
        if self.embed_texts:
            try:
                vecs = list(await embed_cached(self.llm, [r[3][:2000] for r in rows]))
            except Exception:  # noqa: BLE001 — embeddings are best effort; the text row is still written
                log.warning("text embedding failed", exc_info=True)
        for (kind, aid, eid, text, t), v in zip(rows, vecs, strict=True):
            bus.emit_text({"text_id": f"{eid or kind}:{aid}:{t}", "event_id": eid, "t": t, "day": simtime.day_of(t),
                           "kind": kind, "agent_id": aid, "product_id": None, "session_id": session_id,
                           "private": kind != "message", "text": text, "embedding": v or []})

    def _nightly(self, w: World, bus: EventBus, t: int) -> None:
        """03:00: reflect for agents with day importance ≥ 12 (governor P3), then roll working memory."""
        for aid in sorted(self.wm):
            eps = self.wm[aid]
            if day_importance(eps) >= THRESHOLD and self.gov.allow("P3", 0.0011):
                self.queue.submit(f"refl:{aid}", self._reflect_call(aid, list(eps), t), t, REFLECT_DELAY,
                                  lambda: None)
        self.wm = {}
        self.agenda.nightly(t)

    def _reflect_call(self, aid: int, eps: list[dict[str, Any]], t: int) -> Callable[[], Awaitable[Any]]:
        """Bound reflection coroutine factory."""
        return lambda: reflect(aid, eps, t, store=self.store, llm=self.llm)

    # ------------------------------------------------------------------ checkpoint
    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form (open sessions, working memory, cool-downs, governor)."""
        return {"sessions": self.sessions.to_dict(), "wm": {str(k): v for k, v in self.wm.items()},
                "last_met": [[a, b, t] for (a, b), t in self.tracker.last_met.items()], "governor": self.gov.to_dict(),
                "agenda": self.agenda.to_dict(), "stats": self.stats}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict (in-flight conversations are dropped; their sessions expire)."""
        self.sessions = SessionRegistry.from_dict(d.get("sessions") or {})
        self.wm = {int(k): v for k, v in (d.get("wm") or {}).items()}
        self.agenda.load(d.get("agenda") or {})
        self.tracker.last_met = {(a, b): t for a, b, t in d.get("last_met", [])}
        self.gov.load(d.get("governor") or {})
        self.stats.update(d.get("stats") or {})
