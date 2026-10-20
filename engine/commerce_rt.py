"""Engine-side buying runtime (S-01 … S-06, T-03): consideration, research, store visits, inquiries, purchases."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable
from typing import Any

from commerce import purchase as buy
from commerce.consideration import STAGES, TERMINAL, Pair, interest, next_stage
from commerce.need import cfg, phone_need
from commerce.stores import assign_staff, is_open, offers, on_shift, stock, stores_cfg
from engine.events import EventBus
from engine.governor import BudgetGovernor
from engine.planner import free_slot, insert_block
from engine.rng import stream
from engine.tasks import TaskQueue
from engine.world import World
from mind.decision import DecisionAdapter
from mind.memory import MemoryStore, embed_cached
from mind.opinion import attrs_in
from shared import time as simtime
from shared.llm import LLMClient
from shared.schemas.events import Event
from shared.schemas.memory import MemoryEntry
from shared.store import DocStore
from shared.subjects import canonical
from social.conversation import Outcome
from social.store_inquiry import Customer, Salesperson, product_facts, run_inquiry

log = logging.getLogger("engine.commerce")
INQUIRY_DELAY = 12        # sim minutes the customer stays in the store while the visit is generated
EST_INQUIRY = 0.005
EST_PURCHASE = 0.0004
WAKE_UP = 7 * 60
PHONE_CATS = {"smartphone", "phone", "phones"}
CURIOUS_PLUS = ("curious", "researching", "inquiring", "deciding", "purchased")


class CommerceRuntime:
    """Runs after the media runtime each tick; one writer (the engine) for all buying state."""

    def __init__(self, store: DocStore, llm: LLMClient, decider: DecisionAdapter, governor: BudgetGovernor, w: World,
                 *, media: Any, social: Any = None, embed_texts: bool = True, opinion: Any = None) -> None:
        self.store, self.llm, self.decider, self.gov = store, llm, decider, governor
        self.opinion = opinion                            # OpinionEngine (None: legacy summed attitudes)
        self._bus: EventBus | None = None
        self._now = 0
        if opinion is not None:
            opinion.money_fn = lambda aid: self.money(w, aid)
        self.media, self.social = media, social
        self.embed_texts = embed_texts
        self.pairs: dict[str, Pair] = {}                  # "aid|pid" → Pair
        self.dirty: dict[str, str] = {}                   # key → cause event id
        self.life_t: dict[int, int] = {}                  # aid → last phone life event t
        self.paid_t: dict[int, int] = {}
        self.spent: dict[int, int] = {}                   # aid → ₹ spent on phones (applied to savings)
        self.visits: dict[int, dict[str, Any]] = {}       # aid → planned visit {pid, store_id, day, s, online}
        self.arrivals: list[tuple[int, str, int]] = []
        self.stock_used: dict[str, int] = {}              # "store|option" → units sold
        self.queue = TaskQueue(concurrency=8, timeout_s=120)
        self._meta: dict[str, dict[str, Any]] = {}
        self._bg: set[asyncio.Future] = set()
        self.stores = list(w.wm.stores)
        self.store_by_id = {s.store_id: s for s in self.stores}
        self.store_by_place = {s.place_id: s for s in self.stores if s.place_id}
        sellers = [p.agent_id for p in w.profiles if p.special_role == "salesperson"]
        self.staff = assign_staff(self.stores, sellers)
        for aid in sellers:                                # genesis assigns stores in the agent meta when present
            sid = (w.metas.get(aid, {}).get("special") or {}).get("store_id")
            if sid in self.staff and aid not in self.staff[sid]:
                for v in self.staff.values():
                    if aid in v:
                        v.remove(aid)
                self.staff[sid].append(aid)
        self.near_store: dict[int, str | None] = {}
        for p in w.profiles:
            self.near_store[p.agent_id] = self._nearest_store(w, p.home_place_id, p.workplace_place_id)
        self.feed_at: dict[int, set[int]] = {}           # minute of day → agents starting a feed session
        for p in w.profiles:
            for fs in p.media.feed_sessions:
                self.feed_at.setdefault(int(fs[0]), set()).add(p.agent_id)
        self.online_first: set[int] = set()
        share = float(cfg()["online_first_share"])
        for p in w.profiles:
            if p.age <= 35 and stream(w.seed, "online_first", p.agent_id).random() < share:
                self.online_first.add(p.agent_id)
        self.stats = {"transitions": 0, "inquiries": 0, "inquiries_unrendered": 0, "purchases": 0,
                      "purchases_baseline": 0, "cost_usd": 0.0}

    # ------------------------------------------------------------------ helpers
    def _nearest_store(self, w: World, *place_ids: str | None) -> str | None:
        best, bd = None, 1e9
        for pid in place_ids:
            pl = w.wm.place_by_id.get(pid or "")
            if pl is None:
                continue
            x, y = pl.entrances[0]
            for s in self.stores:
                if not s.place_id:
                    continue
                sp = w.wm.place_by_id.get(s.place_id)
                if sp is None:
                    continue
                d = math.dist((x, y), sp.entrances[0])
                if d < bd:
                    best, bd = s.store_id, d
        return best if bd <= 1500 else None

    def _products(self) -> dict[str, dict[str, Any]]:
        if self.media is None:
            return {}
        return {pid: lp.p.model_dump() for pid, lp in self.media.live.items()
                if lp.p.category.lower() in PHONE_CATS}

    def pair(self, aid: int, pid: str, t: int) -> Pair:
        """Get or create a pair."""
        k = f"{aid}|{pid}"
        if k not in self.pairs:
            self.pairs[k] = Pair(since_t=t)
        return self.pairs[k]

    def need(self, w: World, aid: int) -> float:
        """Current phone need of one agent."""
        return phone_need(w.phones[aid], w.t, w.profiles[aid].occupation, self.life_t.get(aid))

    def money(self, w: World, aid: int) -> dict[str, Any]:
        """Money profile with phone spending applied."""
        m = w.profiles[aid].money.model_dump()
        m["savings_inr"] = max(0, int(m["savings_inr"]) - self.spent.get(aid, 0))
        return m

    # ------------------------------------------------------------------ bus listener
    def on_event(self, ev: Event) -> None:
        """Update rule features from the events that move beliefs (thoughts, debriefs, reviews, life events)."""
        aid = ev.agent_id
        if aid is None:
            return
        pid = ev.product_id
        p = ev.payload
        if ev.kind == "thought" and pid and not pid.startswith("baseline:"):
            pr = self.pair(aid, pid, ev.t)
            pr.aware = True
            if self.opinion is None:
                pr.attitude = max(-1.0, min(1.0, pr.attitude + float(p.get("attitude_delta") or 0.0)))
            pr.open_questions = list(dict.fromkeys([*(p.get("open_questions") or []), *pr.open_questions]))[:3]
            if p.get("intent_change") in ("research", "visit_store"):
                pr.fit = min(1.0, pr.fit + 0.25)
                pr.boost = min(0.5, pr.boost + 0.25)
            self._touch(aid, pid, ev.event_id)
        elif ev.kind == "exposure" and pid and not pid.startswith("baseline:") and \
                p.get("outcome") in ("notice", "partial", "full"):
            pr = self.pair(aid, pid, ev.t)
            pr.aware = True
            if p.get("channel") == "review":
                pr.review = max(pr.review, float(p.get("rating", 3.5)) / 5)
            self._touch(aid, pid, ev.event_id)
        elif ev.kind == "debrief":
            catalog = {pid: lp.p.name for pid, lp in self.media.live.items()} if self.media is not None else {}
            for d in p.get("belief_deltas") or []:
                subj = canonical(str(d.get("subject", "")), catalog) if catalog else str(d.get("subject", ""))
                if not subj or not subj.startswith("product:"):
                    continue
                q = subj.split(":", 1)[1]
                pr = self.pair(aid, q, ev.t)
                pr.aware = True
                dv = float(d.get("attitude_delta") or 0.0)
                if self.opinion is None:
                    pr.attitude = max(-1.0, min(1.0, pr.attitude + dv))
                if p.get("conv_kind") != "store":
                    pr.social = max(-1.0, min(1.0, pr.social + 2 * dv))
                self._touch(aid, q, ev.event_id)
        elif ev.kind == "wom" and pid and not pid.startswith("baseline:"):
            pr = self.pair(aid, pid, ev.t)
            pr.aware = True
            self._touch(aid, pid, ev.event_id)
        elif ev.kind == "life_event" and p.get("category") == "phone":
            self.life_t[aid] = ev.t
            for k in [k for k in self.pairs if k.startswith(f"{aid}|")]:
                self.dirty[k] = ev.event_id
        elif ev.kind == "payday":
            self.paid_t[aid] = ev.t
        elif ev.kind == "arrive" and p.get("place_id") in self.store_by_place and aid in self.visits:
            self.arrivals.append((aid, str(p["place_id"]), ev.t))

    def boost_intent(self, aid: int, kind: str) -> None:
        """A plan from a debrief ("check it in a store", "read reviews") nudges this person's open considerations."""
        for k, pr in self.pairs.items():
            if k.startswith(f"{aid}|") and pr.stage in ("aware", "curious", "researching"):
                pr.boost = min(0.5, pr.boost + (0.2 if kind == "visit" else 0.1))
                self.dirty.setdefault(k, pr.cause or "")

    def _touch(self, aid: int, pid: str, cause: str) -> None:
        k = f"{aid}|{pid}"
        self.pairs[k].cause = cause
        self.dirty[k] = cause

    # ------------------------------------------------------------------ tick
    async def tick(self, w: World, bus: EventBus) -> None:
        """Apply finished visits/decisions, run transitions, inject visits, start inquiries."""
        t = w.t
        m = simtime.minute_of_day(t)
        self._bus, self._now = bus, t
        await self._apply(w, bus, t)
        products = self._products()
        if m == WAKE_UP:                                   # wake-up planning: every live pair
            for k, pr in self.pairs.items():
                if pr.stage not in TERMINAL and pr.cause:
                    self.dirty.setdefault(k, pr.cause)
        feed_now = self.feed_at.get(m, set())
        for aid in sorted(feed_now):                       # researching agents read reviews / community (S-03)
            for k, pr in self.pairs.items():
                if k.startswith(f"{aid}|") and pr.stage in ("curious", "researching"):
                    pid = k.split("|", 1)[1]
                    if pr.stage == "researching":
                        self._research(w, bus, t, aid, pid, pr)
                    self.dirty.setdefault(k, pr.cause or "")
        if self.dirty:
            for k in sorted(self.dirty):
                cause = self.dirty[k]
                aid_s, pid = k.split("|", 1)
                aid = int(aid_s)
                if pid not in products:
                    continue
                self._evaluate(w, bus, t, aid, pid, self.pairs[k], cause, aid in feed_now)
            self.dirty = {}
        for aid, v in list(self.visits.items()):           # inject planned visits into today's plan
            if v["day"] == simtime.day_of(t) and not v.get("injected") and w.agents[aid].plan_day == v["day"]:
                if v["online"]:
                    v["injected"] = True
                    continue
                st = self.store_by_id[v["store_id"]]
                w.agents[aid].plan = insert_block(w.agents[aid].plan, v["s"], v["s"] + int(cfg()["store_visit"]["minutes"]),
                                                  "shop", st.place_id)
                v["injected"] = True
            if v["online"] and v.get("injected") and t >= v["abs_t"]:
                self._start_inquiry(w, bus, t, aid, None)
            elif v["day"] < simtime.day_of(t):             # missed visit: plan again tomorrow
                pr = self.pairs.get(f"{aid}|{v['pid']}")
                del self.visits[aid]
                if pr is not None and pr.stage == "inquiring":
                    self._plan_visit(w, t, aid, v["pid"], pr)
        for aid, place_id, _at in self.arrivals:
            self._start_inquiry(w, bus, t, aid, place_id)
        self.arrivals = []

    def _sync(self, aid: int, pid: str, pr: Pair, t: int, cause: str) -> None:
        """Attitude and fit come from the opinion engine; mirror material changes into the agent's belief doc."""
        if self.opinion is None:
            return
        att = float(self.opinion.attitude(aid, pid))
        pr.attitude = att
        pr.fit = max(0.0, min(1.0, float(self.opinion.fit(aid, pid)) + pr.boost))
        if pr.mirrored is None or abs(att - pr.mirrored) >= 0.05:
            pr.mirrored = att
            self._background(self._mirror_opinion(aid, pid, att, t, cause))

    async def _mirror_opinion(self, aid: int, pid: str, att: float, t: int, cause: str) -> None:
        """Computed attitude and its reasons → the agent's own belief doc (profile, People, Insights read this)."""
        if self.opinion is None:
            return
        pro, con = self.opinion.reasons(aid, pid)
        bus = self._bus

        def hook(kind: str, payload: dict[str, Any]) -> None:
            if bus is not None:
                bus.new(kind, t, aid, payload)

        try:
            await MemoryStore(aid, self.store, None, hook).update_belief(
                f"product:{pid}", {"attitude": att, "reasons_for": pro, "reasons_against": con, "t": t}, cause)
        except Exception:  # noqa: BLE001 — read model only
            log.debug("opinion mirror failed", exc_info=True)

    def _evaluate(self, w: World, bus: EventBus, t: int, aid: int, pid: str, pr: Pair, cause: str,
                  feed: bool) -> None:
        self._sync(aid, pid, pr, t, cause)
        need = self.need(w, aid)
        opp: set[str] = set()
        if feed:
            opp.add("feed")
        if self.near_store.get(aid) or aid in self.online_first:
            opp.add("store_route")
        if aid in self.online_first:
            opp.add("online")
        if simtime.weekday(t) in ("Sat", "Sun"):
            opp.add("weekend")
        if t - self.paid_t.get(aid, -10**9) <= 3 * 1440:
            opp |= {"payday", "payday_due"}
        if pr.social > 0.25:
            opp.add("friend")
        if t - self.life_t.get(aid, -10**9) <= 3 * 1440:
            opp.add("life_event")
        for _ in range(3):                                 # allow chained moves (aware → curious) in one evaluation
            nxt = next_stage(pr, need, opp, t)
            if nxt is None:
                break
            self._transition(w, bus, t, aid, pid, pr, nxt[0], cause or pr.cause or "", nxt[1], need)
            if nxt[0] in ("inquiring", "deciding", "rejected"):
                break

    def _transition(self, w: World, bus: EventBus, t: int, aid: int, pid: str, pr: Pair, to: str, cause: str,
                    reason: str, need: float) -> Event:
        frm = pr.stage
        pr.stage, pr.since_t = to, t
        ev = bus.new("consideration", t, aid, {"subject": f"product:{pid}", "from": frm, "to": to,
                                               "cause_event_id": cause, "reason": reason, "need": need,
                                               "interest": interest(pr)}, product_id=pid)
        self.stats["transitions"] += 1
        self._background(self._mirror(aid, pid, to, t, ev.event_id))
        if to == "inquiring":
            self._plan_visit(w, t, aid, pid, pr)
        elif to == "deciding":
            self._queue_purchase(w, t, aid, pid, ev.event_id)
        return ev

    async def _mirror(self, aid: int, pid: str, stage: str, t: int, cause: str) -> None:
        """Belief stage in the agent's own Firestore beliefs (profile + People filters)."""
        try:
            await MemoryStore(aid, self.store).update_belief(f"product:{pid}", {"stage": stage, "t": t}, cause)
        except Exception:  # noqa: BLE001 — read model only
            log.debug("belief mirror failed", exc_info=True)

    # ------------------------------------------------------------------ research (S-03)
    def _research(self, w: World, bus: EventBus, t: int, aid: int, pid: str, pr: Pair) -> None:
        """Reads the latest published review (or a community thread) about the product in a feed session."""
        revs = [r for r in (self.media.reviews if self.media else []) if r.get("product_id") == pid
                and r.get("state") == "published"]
        if revs:
            r = revs[-1]
            rating = float(r.get("rating", 3.5))
            ev = bus.new("exposure", t, aid, {"channel": "review", "creative_id": r.get("review_id", ""),
                                              "outcome": "full", "rating": rating, "research": True},
                         product_id=pid)
            pr.review = max(pr.review, rating / 5)
            if self.opinion is not None:
                self._review_evidence(aid, pid, r, rating)
            else:
                pr.attitude = max(-1.0, min(1.0, pr.attitude + 0.08 * (rating - 3.0)))
            pr.cause = ev.event_id
        else:
            ev = bus.new("exposure", t, aid, {"channel": "community", "creative_id": f"thread:{pid}",
                                              "outcome": "partial", "research": True}, product_id=pid)
            pr.cause = ev.event_id
        if pr.open_questions:
            pr.open_questions = pr.open_questions[1:] + pr.open_questions[:1]

    def _review_evidence(self, aid: int, pid: str, review: dict[str, Any], rating: float) -> None:
        """A published review becomes evidence on what its pros and cons talk about (higher rating, kinder numbers)."""
        cat = self.opinion.catalog.get(pid) if self.opinion is not None else None
        if cat is None:
            return
        pros = attrs_in(" ".join(str(x) for x in review.get("pros", [])))
        cons = attrs_in(" ".join(str(x) for x in review.get("cons", [])))
        shift = 0.08 * (rating - 3.0)
        vals = {a: max(0.0, min(1.0, cat["specs"][a] + shift + (0.1 if a in pros else -0.1 if a in cons else 0.0)))
                for a in (set(pros) | set(cons) or {"performance", "display", "battery", "camera"})}
        self.opinion.evidence(aid, pid, vals, "review")

    # ------------------------------------------------------------------ store visits
    def _plan_visit(self, w: World, t: int, aid: int, pid: str, pr: Pair) -> None:
        sv = cfg()["store_visit"]
        prod = self.media.live[pid].p if self.media and pid in self.media.live else None
        stocking = set(prod.plan.stores) if prod is not None and prod.plan else set()
        online = aid in self.online_first or not stocking or self.near_store.get(aid) is None
        store_id = "ST-SHOPKART" if online else (self.near_store[aid] if self.near_store[aid] in stocking
                                                 else sorted(stocking)[0])
        day = simtime.day_of(t)
        m = simtime.minute_of_day(t)
        plan = w.agents[aid].plan
        s = free_slot(plan, max(m + 30, sv["earliest"]), sv["latest"], sv["minutes"]) if plan else None
        if s is None:
            day += 1
            s = sv["earliest"] + int(stream(w.seed, "visit", day, aid).integers(0, 8 * 60))
        s = s - s % 5
        self.visits[aid] = {"pid": pid, "store_id": store_id, "day": day, "s": s, "online": online,
                            "abs_t": (day - 1) * 1440 + s, "agenda": list(pr.open_questions)}

    def _start_inquiry(self, w: World, bus: EventBus, t: int, aid: int, place_id: str | None) -> None:
        v = self.visits.pop(aid, None)
        if v is None:
            return
        st = self.store_by_id[v["store_id"]] if place_id is None else self.store_by_place.get(place_id)
        if st is None:
            return
        pid = v["pid"]
        pr = self.pairs.get(f"{aid}|{pid}")
        if pr is None or pr.stage != "inquiring" or self.media is None or pid not in self.media.live:
            return                                         # product withdrawn (doc deleted) → visit dropped
        m = simtime.minute_of_day(t)
        seller = on_shift(st, self.staff.get(st.store_id, []), m)
        if seller is None or not is_open(st, m):
            self._plan_visit(w, t, aid, pid, pr)
            return
        sessions = self.social.sessions if self.social is not None else None
        sid = sessions.open([aid, seller], "store", t=t, timeout=INQUIRY_DELAY + 30) if sessions else \
            f"store-{t}-{aid}"
        if sid is None:                                    # salesperson busy: wait a few minutes
            self.visits[aid] = {**v, "online": True, "injected": True, "abs_t": t + 5}
            return
        pr.inquired += 1
        if not st.kind == "online":
            w.agents[aid].talk_until = t + INQUIRY_DELAY
        lp = self.media.live[pid]
        products = [x.p.model_dump() for x in self.media.live.values()]
        units = stock(st, products)
        for k2, n in self.stock_used.items():
            s_id, opt = k2.split("|", 1)
            if s_id == st.store_id and opt in units:
                units[opt] = max(0, units[opt] - n)
        sp = w.profiles[seller]
        styles = [str(x) for x in stores_cfg()["salesperson_styles"]]
        sales = Salesperson(seller, sp.name.split()[0], styles[seller % len(styles)], st.store_id, st.name, pid,
                            lp.p.name, product_facts(lp.p.model_dump()), units, offers(st.store_id))
        prof = w.profiles[aid]
        cust = Customer(aid, prof.name.split()[0], prof.persona.speaking_style,
                        f"{simtime.fmt(t)}; at {st.name}", v.get("agenda") or list(pr.open_questions))
        meta = {"aid": aid, "pid": pid, "store_id": st.store_id, "seller": seller, "sid": sid}
        if not self.gov.allow("P0", EST_INQUIRY):
            self._unrendered_inquiry(w, bus, t, meta)
            return
        key = f"inq:{sid}"
        self._meta[key] = meta
        w.live_evts.append({"k": "store_visit", "a": aid, "store_id": st.store_id, "product": pid, "session_id": sid})
        considered = [pid, *[k.split("|", 1)[1] for k, q in self.pairs.items()
                             if k.startswith(f"{aid}|") and k.split("|", 1)[1] != pid and q.stage not in ("unaware", "rejected")]][:3]
        opinions = self.opinion.brief_many(aid, considered) if self.opinion is not None else ""
        self.queue.submit(key, lambda: run_inquiry(sid, cust, sales, t, store=self.store, llm=self.llm,
                                                   decider=self.decider, opinions=opinions), t, INQUIRY_DELAY,
                          lambda: None)

    def _unrendered_inquiry(self, w: World, bus: EventBus, t: int, meta: dict[str, Any]) -> None:
        ev = bus.new("inquiry", t, meta["aid"], {"session_id": meta["sid"], "agent_id": meta["aid"],
                                                 "store_id": meta["store_id"], "product_id": meta["pid"],
                                                 "questions": [], "topics": ["general"], "answered": [],
                                                 "satisfaction": 0.5, "outcome": "think_about_it", "n_messages": 0},
                     product_id=meta["pid"], other_id=meta["seller"], session_id=meta["sid"], rendered=False)
        self.stats["inquiries_unrendered"] += 1
        self._store_evidence(meta["aid"], meta["pid"], [], 0.0)
        self._close(meta["sid"])
        self._after_inquiry(w, bus, t, meta, ev.event_id, 0.0)

    _TOPIC_ATTR = {"battery": "battery", "camera": "camera", "display": "display", "performance": "performance",
                   "price": "price_value"}

    def _store_evidence(self, aid: int, pid: str, topics: list[str], dv: float) -> None:
        """Handling the phone and hearing the answers: strong evidence on the topics discussed (all on a general visit)."""
        if self.opinion is None:
            return
        covered = [self._TOPIC_ATTR[x] for x in topics if x in self._TOPIC_ATTR]
        if covered:
            self.opinion.evidence(aid, pid, covered, "store")
        else:
            self.opinion.evidence(aid, pid, None, "store", strength=0.6)
        self.opinion.add_reaction(aid, pid, dv, clamp_each=0.2)

    def _close(self, sid: str) -> None:
        if self.social is not None:
            self.social.sessions.close(sid)

    def _after_inquiry(self, w: World, bus: EventBus, t: int, meta: dict[str, Any], cause: str, dv: float) -> None:
        pr = self.pairs.get(f"{meta['aid']}|{meta['pid']}")
        if pr is None or pr.stage != "inquiring":
            return
        if self.opinion is not None:                       # hands-on evidence + the visit's reaction are already in
            self._sync(meta["aid"], meta["pid"], pr, t, cause)
        else:
            pr.attitude = max(-1.0, min(1.0, pr.attitude + dv))
        pr.cause = cause
        if pr.attitude <= float(cfg()["stages"]["reject_attitude"]):
            self._transition(w, bus, t, meta["aid"], meta["pid"], pr, "rejected", cause, "store visit put them off",
                             self.need(w, meta["aid"]))
        else:
            self._transition(w, bus, t, meta["aid"], meta["pid"], pr, "deciding", cause, "store inquiry done",
                             self.need(w, meta["aid"]))

    # ------------------------------------------------------------------ purchases
    def _queue_purchase(self, w: World, t: int, aid: int, pid: str, cause: str) -> None:
        products = self._products()
        ints = {q: interest(self.pairs[f"{aid}|{q}"]) for q in products if f"{aid}|{q}" in self.pairs
                and self.pairs[f"{aid}|{q}"].stage not in ("rejected", "unaware")}
        opts = buy.options_for(ints, products, self.money(w, aid), str(w.phones[aid].get("tier", "mid")))
        need = self.need(w, aid)
        life = t - self.life_t.get(aid, -10**9) <= 3 * 1440
        card = w.profiles[aid].persona_card
        allowed = self.gov.allow("P0", EST_PURCHASE)
        key = f"buy:{aid}:{pid}:{t}"
        self._meta[key] = {"aid": aid, "pid": pid, "cause": cause, "need": need, "life": life}
        llm = self.llm if allowed else None
        self.queue.submit(key, lambda: buy.decide(aid, card, need, opts, life, llm=llm), t, 2,
                          lambda: ({"decision": "postpone", "option": None, "method": None, "price_inr": None,
                                    "reason": "timeout", "rule": True}, 0.0))

    def _apply_purchase(self, w: World, bus: EventBus, t: int, meta: dict[str, Any], res: Any) -> None:
        out, cost = res
        if cost:
            self.gov.record(cost, "P0")
            self.stats["cost_usd"] += cost
        aid, pid = meta["aid"], meta["pid"]
        pr = self.pairs.get(f"{aid}|{pid}")
        if pr is None or pr.stage != "deciding":
            return
        if out["decision"] != "buy" or out["option"] is None:
            to = "rejected" if pr.attitude <= float(cfg()["stages"]["reject_attitude"]) else "postponed"
            self._transition(w, bus, t, aid, pid, pr, to, meta["cause"], out["reason"], meta["need"])
            return
        option = str(out["option"])
        products = self._products()
        visit_store = (self._meta.get(f"last_store:{aid}") or {}).get("store_id", "ST-SHOPKART")
        ev = bus.new("purchase", t, aid, {"option": option, "store_id": visit_store, "price_inr": out["price_inr"],
                                          "method": out["method"], "considered": pid, "need": meta["need"],
                                          "life_event": meta["life"], "reason": out["reason"],
                                          "cause_event_id": meta["cause"]},
                     product_id=option if option in products else None)
        self.stats["purchases"] += 1
        if option.startswith("baseline:"):
            self.stats["purchases_baseline"] += 1
        self.stock_used[f"{visit_store}|{option}"] = self.stock_used.get(f"{visit_store}|{option}", 0) + 1
        self.spent[aid] = self.spent.get(aid, 0) + int(out["price_inr"] or 0) if out["method"] == "cash" else \
            self.spent.get(aid, 0)
        old = dict(w.phones[aid])
        brand = products[option]["brand"] if option in products else old.get("brand", "familiar brand")
        label = products[option]["name"] if option in products else option.split(":", 1)[1] + " phone (baseline)"
        w.phones[aid] = {"brand": brand, "tier": buy.tier_of(option, products), "model_label": label, "bought_t": t,
                         "condition": "ok", "battery_health": 1.0, "satisfaction": 0.85,
                         "history": [*old.get("history", []), {"t": t, "event": "purchase", "option": option}]}
        if self.opinion is not None and option in products:  # now I use it: I know it as it is
            self.opinion.evidence(aid, option, None, "own_use")
        self.life_t.pop(aid, None)
        self._transition(w, bus, t, aid, pid, pr, "purchased" if option == pid else "rejected", ev.event_id,
                         f"bought {label}" if option == pid else f"bought {label} instead", meta["need"])
        for k, other in self.pairs.items():                # buying a phone ends other phone considerations
            if k.startswith(f"{aid}|") and k != f"{aid}|{pid}" and other.stage not in TERMINAL:
                q = k.split("|", 1)[1]
                self._transition(w, bus, t, aid, q, other, "purchased" if q == option else "rejected", ev.event_id,
                                 "bought a phone", meta["need"])
        w.live_evts.append({"k": "purchase", "a": aid, "product": option, "method": out["method"]})
        text = f"I bought the {label} for ₹{int(out['price_inr'] or 0):,} ({out['method']}). {out['reason']}"
        self._background(MemoryStore(aid, self.store, None).add(MemoryEntry(
            mid=f"buy-{ev.event_id}", agent_id=aid, t=t, kind="purchase", text=text[:400], importance=7,
            source={"channel": "purchase", "product_id": option, "event_id": ev.event_id}, entities=[label],
            event_refs=[ev.event_id])))
        if self.social is not None:
            self.social.remember(aid, text, 7, "purchase", t, tag=label)
            self.social.agenda.add(aid, "purchase", t, hint="new phone", product_id=option if option in products else None,
                                   about=label)

    # ------------------------------------------------------------------ apply queue
    async def _apply(self, w: World, bus: EventBus, t: int) -> None:
        for key, res in await self.queue.collect(t):
            meta = self._meta.pop(key, None)
            if meta is None:
                continue
            if key.startswith("buy:"):
                self._apply_purchase(w, bus, t, meta, res)
                continue
            self._meta[f"last_store:{meta['aid']}"] = {"store_id": meta["store_id"]}
            if res is None:
                self._unrendered_inquiry(w, bus, t, meta)
                continue
            self._emit_inquiry(w, bus, t, meta, res)

    def _emit_inquiry(self, w: World, bus: EventBus, t: int, meta: dict[str, Any], out: Outcome) -> None:
        emitted: list[Event] = []
        texts: list[tuple[str, int, str, str, bool]] = []
        cause, dv = "", 0.0
        for spec in out.events:
            ev = bus.new(spec["kind"], t, spec["agent_id"], spec["payload"], other_id=spec.get("other_id"),
                         session_id=out.session_id, product_id=meta["pid"])
            emitted.append(ev)
            p = spec["payload"]
            if spec["kind"] == "message":
                texts.append(("message", ev.agent_id or 0, ev.event_id, p["text"], False))
            elif spec["kind"] == "store_thought":
                texts.append(("store_thought", ev.agent_id or 0, ev.event_id, p["thought"], True))
            elif spec["kind"] == "inquiry":
                cause = ev.event_id
            elif spec["kind"] == "debrief":
                dv = float((p.get("belief_deltas") or [{}])[0].get("attitude_delta", 0.0))
                texts.append(("debrief", ev.agent_id or 0, ev.event_id, f"{p['reaction']} {p['summary']}", True))
                if self.social is not None:
                    self.social.remember(meta["aid"], p["summary"], int(p.get("importance", 4)), "inquiry", t,
                                         tag="store visit")
                    self.social.agenda.add(meta["aid"], "store_visit", t, hint="phone shop", product_id=meta["pid"])
        if self.opinion is not None:
            visit_topics: list[str] = next((e.payload["topics"] for e in emitted if e.kind == "inquiry"), [])
            self._store_evidence(meta["aid"], meta["pid"], visit_topics, dv)
        conv = bus.new("conversation", t, meta["aid"], {
            "session_id": out.session_id, "participants": [meta["aid"], meta["seller"]], "place_id":
                self.store_by_id[meta["store_id"]].place_id, "kind": "store", "t_start": t - INQUIRY_DELAY,
            "t_end": t, "topics": next((e.payload["topics"] for e in emitted if e.kind == "inquiry"), []),
            "product_mentions": [meta["pid"]], "n_messages": len(out.messages), "rendered": True,
            "model": "flash-lite"}, other_id=meta["seller"], session_id=out.session_id, product_id=meta["pid"])
        emitted.append(conv)
        self.stats["inquiries"] += 1
        if out.cost_usd:
            self.gov.record(out.cost_usd, "P0")
            self.stats["cost_usd"] += out.cost_usd
        if out.messages:
            first = out.messages[0]
            w.live_evts.append({"k": "bubble", "session_id": out.session_id, "a": first.speaker, "b": first.listener,
                                "text": first.text, "n": len(out.messages), "product": meta["pid"]})
        self._background(asyncio.to_thread(self._persist, out.session_id, meta, emitted, t))
        self._background(self._texts(bus, texts, out.session_id, meta["pid"], t))
        self._close(out.session_id)
        self._after_inquiry(w, bus, t, meta, cause, dv)

    def _persist(self, sid: str, meta: dict[str, Any], events: list[Event], t: int) -> None:
        """Firestore read models: `conversations/{sid}` (store_thoughts private to the customer) + both profiles."""
        aid, seller = meta["aid"], meta["seller"]
        msgs = [{"seq": e.payload["seq"], "speaker": e.payload["speaker"], "listener": e.payload["listener"],
                 "text": e.payload["text"], "t": e.t, "event_id": e.event_id} for e in events if e.kind == "message"]
        conv = next(e for e in events if e.kind == "conversation").payload
        private = {str(aid): {"store_thoughts": [e.payload for e in events if e.kind == "store_thought"],
                              "debrief": next((e.payload for e in events if e.kind == "debrief"), None)},
                   str(seller): {"salesperson_thoughts": [e.payload for e in events
                                                          if e.kind == "salesperson_thought"]}}
        inq = next((e.payload for e in events if e.kind == "inquiry"), {})
        self.store.set("conversations", sid, {"session_id": sid, "participants": [aid, seller], "t": t,
                                              "conversation": conv, "messages": msgs, "private": private,
                                              "inquiry": inq})
        for me, other in ((aid, seller), (seller, aid)):
            self.store.set(f"agents/{me}/conversations", sid, {
                "session_id": sid, "with": other, "kind": "store", "t": t, "label": simtime.fmt(t),
                "topics": conv.get("topics") or [], "n_messages": len(msgs), "rendered": True,
                "first_line": msgs[0]["text"] if msgs else "", "store_id": meta["store_id"],
                "product_id": meta["pid"]})

    async def _texts(self, bus: EventBus, rows: list[tuple[str, int, str, str, bool]], sid: str, pid: str,
                     t: int) -> None:
        vecs: list[list[float] | None] = [None] * len(rows)
        if self.embed_texts and rows:
            try:
                vecs = list(await embed_cached(self.llm, [r[3][:2000] for r in rows]))
            except Exception:  # noqa: BLE001
                log.warning("text embedding failed", exc_info=True)
        for (kind, aid, eid, text, private), v in zip(rows, vecs, strict=True):
            bus.emit_text({"text_id": f"{eid}:{aid}", "event_id": eid, "t": t, "day": simtime.day_of(t),
                           "kind": kind, "agent_id": aid, "product_id": pid, "session_id": sid,
                           "private": private, "text": text, "embedding": v or []})

    def _background(self, coro: Awaitable[Any]) -> None:
        fut = asyncio.ensure_future(coro)
        self._bg.add(fut)
        fut.add_done_callback(self._bg.discard)

    # ------------------------------------------------------------------ views + checkpoint
    def stages_of(self, aid: int) -> dict[str, str]:
        """{product_id: stage} for one agent."""
        return {k.split("|", 1)[1]: p.stage for k, p in self.pairs.items() if k.startswith(f"{aid}|")}

    def funnel(self) -> dict[str, dict[str, int]]:
        """{product_id: {aware, curious_plus, purchased}} over live products (live stats; replaces fixture counts)."""
        valid = set(self._products())
        out: dict[str, dict[str, int]] = {pid: {"aware": 0, "curious_plus": 0, "purchased": 0} for pid in valid}
        for k, p in self.pairs.items():
            pid = k.split("|", 1)[1]
            if pid not in valid or p.stage in ("unaware", "rejected"):
                continue
            row = out[pid]
            row["aware"] += 1
            if p.stage in CURIOUS_PLUS:
                row["curious_plus"] += 1
            if p.stage == "purchased":
                row["purchased"] += 1
        return out

    def prune_products(self, valid: set[str]) -> int:
        """Drop pairs and planned visits for products that no longer exist (deleted in Launch Studio)."""
        dead = [k for k in self.pairs if k.split("|", 1)[1] not in valid]
        for k in dead:
            del self.pairs[k]
            self.dirty.pop(k, None)
        for aid, v in list(self.visits.items()):
            if v.get("pid") not in valid:
                del self.visits[aid]
        return len(dead)

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        return {"pairs": {k: p.to_dict() for k, p in self.pairs.items()}, "life_t": self.life_t,
                "paid_t": self.paid_t, "spent": self.spent, "visits": self.visits, "stock_used": self.stock_used,
                "stats": self.stats}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict."""
        self.pairs = {k: Pair(**v) for k, v in (d.get("pairs") or {}).items()}
        self.life_t = {int(k): int(v) for k, v in (d.get("life_t") or {}).items()}
        self.paid_t = {int(k): int(v) for k, v in (d.get("paid_t") or {}).items()}
        self.spent = {int(k): int(v) for k, v in (d.get("spent") or {}).items()}
        self.visits = {int(k): v for k, v in (d.get("visits") or {}).items()}
        self.stock_used = dict(d.get("stock_used") or {})
        self.stats.update(d.get("stats") or {})

    def seed_from_media(self, t: int) -> None:
        """First boot with phase-5 code: agents already aware of live products start at `aware`."""
        if self.media is None or self.pairs:
            return
        for pid, ids in self.media.aware.items():
            for aid in sorted(ids):
                pr = self.pair(aid, pid, t)
                pr.aware = True
                pr.stage = "aware"
                pr.attitude = float(self.media.attitude.get(f"{aid}|{pid}", 0.0))
                pr.cause = f"seed:{pid}"
                self.dirty[f"{aid}|{pid}"] = pr.cause


__all__ = ["CommerceRuntime", "STAGES"]
