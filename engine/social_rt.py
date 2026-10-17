"""Engine-side social runtime: encounters → gate → sessions → queued conversations, working memory, reflection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from engine.encounters import EncounterTracker, Presence
from engine.events import EventBus
from engine.governor import BudgetGovernor
from engine.tasks import TaskQueue
from engine.world import World
from mind.decision import DecisionAdapter, DecisionRequest, DecisionResult
from mind.memory import embed_cached
from mind.reflect import THRESHOLD, day_importance, reflect
from shared import time as simtime
from shared.llm import LLMClient
from shared.schemas.events import Event
from shared.store import DocStore
from social.conversation import Outcome, Participant, run_conversation, unrendered
from social.gate import Side, gate
from social.sessions import SessionRegistry

log = logging.getLogger("engine.social")
WM_MAX = 20
CONV_DELAY = 6               # sim minutes until a conversation's result is applied
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
                f.set_result(r)
        except Exception as e:  # noqa: BLE001
            for _, f in q:
                f.set_exception(e)


class SocialRuntime:
    """Runs after every World.step(); all results land at deterministic sim times via the TaskQueue."""

    def __init__(self, store: DocStore, llm: LLMClient, decider: DecisionAdapter, governor: BudgetGovernor,
                 relationships: list[dict[str, Any]], *, watched: set[int] | None = None,
                 embed_texts: bool = True) -> None:
        self.store = store
        self.llm = llm
        self.decider = MicroBatcher(decider)
        self.gov = governor
        self.rel: dict[tuple[int, int], dict[str, Any]] = {}
        for r in relationships:
            if r.get("kind") != "follower":
                self.rel[(min(r["a"], r["b"]), max(r["a"], r["b"]))] = r
        self.tracker = EncounterTracker()
        self.sessions = SessionRegistry()
        self.queue = TaskQueue()
        self.wm: dict[int, list[dict[str, Any]]] = {}
        self.watched = watched or set()
        self.embed_texts = embed_texts
        self._pclass: dict[str, str] = {}
        self._bg: set[asyncio.Future] = set()
        self.stats = {"rendered": 0, "unrendered": 0, "reflections": 0, "cost_usd": 0.0}

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
        return Side(aid, list(prof.persona.interests), salient=list(dict.fromkeys(tags))[-3:],
                    free=FREE.get(w.agents[aid].activity, 0.3), watched=aid in self.watched)

    async def tick(self, w: World, bus: EventBus) -> None:
        """Gate new encounters, apply finished conversations/reflections, run the nightly job."""
        t = w.t
        await self._apply(w, bus, t)
        self.sessions.expire(t)
        pairs = self.tracker.update(t, self.presences(w))
        if pairs:
            await asyncio.gather(*(self._encounter(w, bus, a, b, t) for a, b in pairs))
        if simtime.minute_of_day(t) == REFLECT_AT:
            self._nightly(w, bus, t)

    async def _encounter(self, w: World, bus: EventBus, ia: int, ib: int, t: int) -> None:
        self.tracker.met((ia, ib), t)
        pair = (min(ia, ib), max(ia, ib))
        rel = self.rel.get(pair)
        place = w.wm.place_by_id.get(w.agents[ia].place_id or "")
        g = await gate(self.side(w, ia), self.side(w, ib), rel, place.kind if place else None, t, self.decider, self.gov)
        bus.new("gate", t, pair[0], g.payload(), other_id=pair[1], rendered=g.rendered)
        if not g.talk:
            return
        sid = self.sessions.open([ia, ib], g.kind, t=t, timeout=CONV_DELAY + 15)
        if sid is None:
            return
        for x in (ia, ib):
            w.agents[x].talk_until = t + CONV_DELAY
        pa = self._participant(w, ia)
        pb = self._participant(w, ib)
        w.live_evts.append({"k": "talk", "a": ia, "b": ib, "session_id": sid, "topic": g.topics[0] if g.topics else "",
                            "rendered": g.rendered, "place": w._pname(w.agents[ia].place_id)})
        if not g.rendered:
            out = await unrendered(sid, pa, pb, g, t, self.store)
            self._emit(w, bus, out, t, g.priority_class)
            return
        rel_label = REL_LABEL.get((rel or {}).get("kind", ""), "strangers")
        closeness = float((rel or {}).get("closeness", 0.0))
        pname = (place.name if place else "the street") if place and place.kind != "home" else "home"
        fallback_gate = g

        def fallback() -> Outcome:
            return Outcome(sid, rendered=False, minutes=5, events=[{
                "kind": "interaction", "agent_id": ia, "other_id": ib,
                "payload": {"topic": fallback_gate.topics[0] if fallback_gate.topics else "small talk",
                            "minutes": 5, "conv_kind": fallback_gate.kind, "fallback": True}}])

        self.queue.submit(sid, lambda: run_conversation(sid, pa, pb, g, rel_label, closeness, pname, t,
                                                        store=self.store, llm=self.llm, decider=self.decider),
                          t, CONV_DELAY, fallback)
        self._pclass[sid] = g.priority_class

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
            elif spec["kind"] == "interaction":
                for x in (spec["agent_id"], spec.get("other_id")):
                    if x is not None:
                        self.remember(x, f"Chatted briefly about {p['topic']}.", 2, "conversation", t)
        self._background(asyncio.to_thread(self._persist, out, emitted, t))
        if out.messages:
            first = out.messages[0]
            w.live_evts.append({"k": "bubble", "session_id": out.session_id, "a": first.speaker, "b": first.listener,
                                "text": first.text, "n": len(out.messages)})
            w.counters["conversations_today"] += 1
            w.counters["conversations_total"] = w.counters.get("conversations_total", 0) + 1
        self.stats["rendered" if out.rendered else "unrendered"] += 1
        if out.cost_usd:
            self.gov.record(out.cost_usd, pclass)
            self.stats["cost_usd"] += out.cost_usd
        if texts:
            self._background(self._texts(bus, texts, out.session_id))

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
                           "private": kind != "message", "text": text, "embedding": v})

    def _nightly(self, w: World, bus: EventBus, t: int) -> None:
        """03:00: reflect for agents with day importance ≥ 12 (governor P3), then roll working memory."""
        for aid in sorted(self.wm):
            eps = self.wm[aid]
            if day_importance(eps) >= THRESHOLD and self.gov.allow("P3", 0.0011):
                self.queue.submit(f"refl:{aid}", self._reflect_call(aid, list(eps), t), t, REFLECT_DELAY,
                                  lambda: None)
        self.wm = {}

    def _reflect_call(self, aid: int, eps: list[dict[str, Any]], t: int) -> Callable[[], Awaitable[Any]]:
        """Bound reflection coroutine factory."""
        return lambda: reflect(aid, eps, t, store=self.store, llm=self.llm)

    # ------------------------------------------------------------------ checkpoint
    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form (open sessions, working memory, cool-downs, governor)."""
        return {"sessions": self.sessions.to_dict(), "wm": {str(k): v for k, v in self.wm.items()},
                "last_met": [[a, b, t] for (a, b), t in self.tracker.last_met.items()], "governor": self.gov.to_dict(),
                "stats": self.stats}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict (in-flight conversations are dropped; their sessions expire)."""
        self.sessions = SessionRegistry.from_dict(d.get("sessions") or {})
        self.wm = {int(k): v for k, v in (d.get("wm") or {}).items()}
        self.tracker.last_met = {(a, b): t for a, b, t in d.get("last_met", [])}
        self.gov.load(d.get("governor") or {})
        self.stats.update(d.get("stats") or {})
