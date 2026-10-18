"""Survey Room in the engine (addendum B3–B8, B11): one active survey at a time; recruitment → walking to the venue →
round tables → discussion + private ballots → debrief, summaries, results. The engine is the only writer."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable
from typing import Any

from commerce.consideration import interest
from commerce.need import job_dependence
from engine.events import EventBus
from engine.governor import BudgetGovernor
from engine.planner import insert_block
from engine.rng import stream
from engine.survey import recruit
from engine.survey.session import Budget, Person, TableRunner, bucket, key
from engine.world import World
from insights.likely_buyers import age_band
from mind.decision import DecisionAdapter, DecisionRequest
from mind.memory import MemoryStore, embed_cached
from population.possessions import phone_age_years
from shared import time as simtime
from shared.llm import FakeGemini, LLMClient
from shared.models import MODEL_FLASH
from shared.schemas.memory import MemoryEntry
from shared.schemas.survey import MAX_PARTICIPANTS, Question, Survey
from shared.store import DocStore

log = logging.getLogger("engine.survey")
LIVE_ONLY = {"survey_phase"}
TRAVEL_LEAD = 30            # sim minutes before start_at the 'survey' block begins (agents walk / ride there)


class SurveyRuntime:
    """Runs after the commerce runtime each tick."""

    def __init__(self, store: DocStore, llm: LLMClient, decider: DecisionAdapter, gov: BudgetGovernor, w: World, *,
                 hub: Any = None, commerce: Any = None, social: Any = None, embed_texts: bool = True) -> None:
        self.store, self.llm, self.decider, self.gov = store, llm, decider, gov
        self.hub, self.commerce, self.social = hub, commerce, social
        self.embed_texts = embed_texts
        self.cfg = recruit.cfg()
        self.venue = str(self.cfg["venue"]["place_id"])
        self.venue_name = str(self.cfg["venue"]["name"])
        self.queue: list[str] = []
        self.active: dict[str, Any] | None = None
        self.history: dict[int, int] = {}            # aid → last survey attended t (fatigue)
        self._bg: set[asyncio.Future] = set()
        self.frames: list[dict[str, Any]] = []       # survey frames to push after this tick
        self.offline = isinstance(llm, FakeGemini)

    # ------------------------------------------------------------------ commands
    def launch(self, survey_id: str) -> dict[str, Any]:
        """Queue a survey (one active at a time)."""
        if survey_id in self.queue or (self.active and self.active["id"] == survey_id):
            return {"ok": True, "queued": True}
        self.queue.append(survey_id)
        return {"ok": True, "queued": len(self.queue) > 1 or self.active is not None}

    def cancel(self, survey_id: str, w: World, bus: EventBus) -> dict[str, Any]:
        """Cancel and release participants."""
        if survey_id in self.queue:
            self.queue.remove(survey_id)
        if self.active and self.active["id"] == survey_id:
            self._release(w, bus, self.active, cancelled=True)
            self.active = None
        self._background(asyncio.to_thread(self.store.set, "surveys", survey_id, {"status": "cancelled"}, True))
        return {"ok": True}

    def on_event(self, ev: Any) -> None:
        """Bus listener: arrivals at the venue."""
        a = self.active
        if a is None or ev.kind != "arrive" or ev.payload.get("place_id") != self.venue or ev.agent_id is None:
            return
        p = a["participants"].get(ev.agent_id)
        if p is not None and p["rsvp"] == "accepted" and p.get("arrived_t") is None:
            p["arrived_t"] = ev.t
            a["dirty"] = True

    # ------------------------------------------------------------------ tick
    async def tick(self, w: World, bus: EventBus) -> None:
        """Advance the active survey's state machine."""
        t = w.t
        if self.active is None and self.queue:
            sid = self.queue.pop(0)
            doc = await asyncio.to_thread(self.store.get, "surveys", sid)
            if doc is not None and doc.get("status") not in ("cancelled", "completed"):
                self._start(w, bus, doc)
        a = self.active
        if a is None:
            return
        st = a["status"]
        if st == "recruiting" and a["rsvp_fut"].done():
            self._select(w, bus, a)
        elif st == "gathering":
            self._inject(w, a)
            arrived = sum(1 for p in a["participants"].values() if p["rsvp"] == "accepted" and p.get("arrived_t"))
            exp = sum(1 for p in a["participants"].values() if p["rsvp"] == "accepted")
            if a.pop("dirty", False) or t % 5 == 0:
                w.live_evts.append({"k": "survey", "survey_id": a["id"], "status": "gathering", "venue": self.venue,
                                    "arrived": arrived, "expected": exp, "name": self.venue_name})
            if exp == 0 and t >= a["start_t"]:
                self._finish(w, bus, a, empty=True)
            elif exp and (arrived >= math.ceil(exp * float(self.cfg["timings"]["gather_share"]))
                          or t >= a["start_t"] + int(self.cfg["timings"]["gather_timeout"])):
                if t >= a["start_t"] or arrived >= exp:
                    self._begin(w, bus, a)
        elif st == "in_session":
            self._release_items(w, bus, a, t)
            if a["tables_fut"].done() and all(r["cursor"] >= len(r["runner"].items) for r in a["runners"]):
                if a["tables_fut"].exception() is not None:
                    log.error("survey session failed", exc_info=a["tables_fut"].exception())
                self._after(w, bus, a)
        elif st == "finishing" and a["post_fut"].done():
            self._finish(w, bus, a)
        if self.frames and self.hub is not None:
            frames, self.frames = self.frames, []
            await self.hub.send_survey(a["id"], frames)

    # ------------------------------------------------------------------ recruiting
    def _start(self, w: World, bus: EventBus, doc: dict[str, Any]) -> None:
        s = Survey.model_validate(doc)
        s.max_participants = min(s.max_participants, MAX_PARTICIPANTS)          # hard cap in the engine too
        t = w.t
        rows = recruit.agent_rows(w.profiles, w.phones, t)
        stages = {aid: self.commerce.stages_of(aid) for aid in range(len(w.agents))} if self.commerce else {}
        panel = doc.get("panel_agent_ids")
        try:
            pool = [int(x) for x in panel] if panel else recruit.eligible(rows, s.cohort_filter, stages,
                                                                          s.interest_filter.model_dump() if s.interest_filter else None)
        except Exception as e:  # noqa: BLE001 — bad filter: stop with a clear status
            self._background(asyncio.to_thread(self.store.set, "surveys", s.survey_id,
                                               {"status": "cancelled", "error": str(e)[:200]}, True))
            return
        lead = int(self.cfg["timings"]["lead_min"])
        rnd = int(self.cfg["timings"]["slot_round"])
        start = s.start_at_t if s.start_at_t and s.start_at_t >= t + 30 else ((t + lead + rnd - 1) // rnd) * rnd
        m = simtime.minute_of_day(start)
        if m < 9 * 60 or m > 20 * 60:                     # sessions run 09:00–20:00
            day = simtime.day_of(start) + (1 if m > 20 * 60 else 0)
            start = (day - 1) * 1440 + 10 * 60
        ev = bus.new("survey_created", t, None, {"survey_id": s.survey_id, "title": s.title, "mode": s.mode,
                                                 "n_questions": len(s.questions), "cohort": s.cohort_filter,
                                                 "wave": s.wave, "panel_id": s.panel_id,
                                                 "parent_survey_id": s.parent_survey_id, "product_id": s.product_id,
                                                 "start_at_t": start, "max_participants": s.max_participants},
                     product_id=s.product_id)
        for aid in pool:
            bus.new("survey_invite", t, aid, {"survey_id": s.survey_id}, product_id=s.product_id)
        reqs, hints = [], {}
        venue = w.wm.place_by_id.get(self.venue)
        vx, vy = venue.entrances[0] if venue else (0.0, 0.0)
        for aid in pool:
            prof = w.profiles[aid]
            pr = self.commerce.pairs.get(f"{aid}|{s.product_id}") if (self.commerce and s.product_id) else None
            home = w.wm.place_by_id.get(prof.home_place_id)
            dist = math.dist(home.entrances[0], (vx, vy)) if home else 1500.0
            blk = next((b for b in w.agents[aid].plan if b["s"] <= simtime.minute_of_day(start) < b["e"]), None)
            free = 1.0 if blk is None or blk["act"] in ("home", "cafe", "park", "shop", "eat", "roam") else 0.25
            fat = t - self.history.get(aid, -10**9) < int(self.cfg["fatigue_days"]) * 1440
            p = recruit.rsvp_propensity(prof, interest=interest(pr) if pr else 0.3, free=free, dist_m=dist,
                                        incentive=s.incentive_inr, fatigue=fat, job_dep=job_dependence(prof.occupation))
            hints[aid] = p
            reqs.append(DecisionRequest(agent_id=aid, kind="plan", options=["accept", "decline"], context={
                "persona": prof.persona_card, "invite": f"{s.title} at the {self.venue_name}, {simtime.fmt(start)}, "
                                                         f"₹{s.incentive_inr} incentive, ~{int(dist)} m away",
                "free_time": free, "recently_attended": fat, "interest": round(interest(pr), 2) if pr else 0.3,
                "p_accept_hint": round(p, 2)}))

        async def rsvp() -> list[tuple[int, bool, str]]:
            out = []
            if self.offline:
                for r in reqs:
                    rng = stream(w.seed, "rsvp", s.survey_id, r.agent_id)
                    ok = float(rng.random()) < hints[r.agent_id]
                    out.append((r.agent_id, ok, ("Sounds interesting and I'm free then." if ok else
                                                 "I'm busy then, and it's a bit far.")))
                return out
            res: list[Any] = []
            for i in range(0, len(reqs), int(self.cfg["rsvp_batch"])):
                res += await self.decider.decide_batch(reqs[i:i + int(self.cfg["rsvp_batch"])])
            for r, d in zip(reqs, res, strict=True):
                out.append((r.agent_id, d.choice == "accept", d.reason[:200]))
            return out

        a = {"id": s.survey_id, "s": s, "doc": doc, "status": "recruiting", "start_t": start, "pool": pool,
             "participants": {}, "tables": [], "rsvp_fut": asyncio.ensure_future(rsvp()), "created_event": ev.event_id,
             "budget": Budget(left=max(0.0, float(self.gov.cfg["interactive_cap_usd"]) - self.gov.interactive_today))}
        self.active = a
        self._persist(a, {"status": "recruiting", "eligible": len(pool), "start_at_t": start,
                          "start_label": simtime.fmt(start), "venue": self.venue, "venue_name": self.venue_name})
        w.live_evts.append({"k": "survey", "survey_id": s.survey_id, "status": "recruiting", "venue": self.venue,
                            "arrived": 0, "expected": 0, "name": self.venue_name})

    def _select(self, w: World, bus: EventBus, a: dict[str, Any]) -> None:
        s: Survey = a["s"]
        t = w.t
        try:
            answers = a["rsvp_fut"].result()
        except Exception:  # noqa: BLE001
            answers = []
        busy = self.social.sessions.busy if self.social is not None else (lambda _x: False)
        rng = stream(w.seed, "rsvp_order", s.survey_id)
        order = [answers[int(i)] for i in rng.permutation(len(answers))] if answers else []
        accepted = [aid for aid, ok, _ in order if ok and not busy(aid)]
        chosen, wait = recruit.select(accepted, a["pool"], s.max_participants, w.profiles, w.seed, s.survey_id)
        no_show = {aid for aid in chosen if stream(w.seed, "no_show", s.survey_id, aid).random()
                   < float(self.cfg["no_show_p"])}
        reasons = {aid: r for aid, _, r in answers}
        for aid, ok, reason in answers:
            rs = "accepted" if aid in chosen else ("waitlist" if aid in wait else "declined")
            bus.new("survey_rsvp", t, aid, {"survey_id": s.survey_id, "rsvp": "accept" if ok else "decline",
                                            "status": rs, "reason": reason}, product_id=s.product_id)
            a["participants"][aid] = {"agent_id": aid, "rsvp": rs, "rsvp_reason": reasons.get(aid, ""),
                                      "arrived_t": None, "no_show": aid in no_show}
        stance = {aid: (self.commerce.pairs[f"{aid}|{s.product_id}"].attitude
                        if self.commerce and f"{aid}|{s.product_id}" in self.commerce.pairs else 0.0) for aid in chosen}
        tables = recruit.seat(chosen, s.table_size, w.profiles, stance, w.seed, s.survey_id)
        sessions = self.social.sessions if self.social is not None else None
        a["tables"] = []
        for i, seats in enumerate(tables):
            tid = f"T{i + 1}"
            sid = sessions.open(seats, "focus_group", t=t, timeout=24 * 60) if sessions else None
            sid = sid or f"fg-{s.survey_id}-{tid}"
            a["tables"].append({"table_id": tid, "survey_id": s.survey_id, "session_id": sid, "seats": seats,
                                "moderator_id": f"moderator-{tid}"})
            for k, aid in enumerate(seats):
                a["participants"][aid].update({"table_id": tid, "seat": k})
        a["status"] = "gathering"
        self._persist(a, {"status": "gathering", "accepted": len(chosen), "waitlist": len(wait), "invited": len(answers),
                          "tables": a["tables"]})
        self.frames.append({"type": "survey", "survey_id": s.survey_id, "phase": "gathering", "question_id": None,
                            "tables": [{"table_id": x["table_id"], "seats": x["seats"]} for x in a["tables"]]})
        if not chosen:
            a["start_t"] = t

    def _inject(self, w: World, a: dict[str, Any]) -> None:
        """Planner: activity 'survey' at the venue for accepted agents (they travel on the road graph)."""
        day = simtime.day_of(a["start_t"])
        s0 = simtime.minute_of_day(a["start_t"]) - TRAVEL_LEAD
        dur = TRAVEL_LEAD + len(a["s"].questions) * int(self.cfg["timings"]["per_question_focus" if a["s"].mode ==
                                                                          "focus_group" else "per_question_survey"]) + 30
        for aid, p in a["participants"].items():
            if p["rsvp"] != "accepted" or p.get("injected") or p.get("no_show"):
                continue
            ag = w.agents[aid]
            if ag.plan_day != day:
                continue
            ag.plan = insert_block(ag.plan, max(0, s0), min(1440, s0 + dur), "survey", self.venue)
            p["injected"] = True
            w.live_evts.append({"k": "survey_trip", "a": aid, "survey_id": a["id"]})

    # ------------------------------------------------------------------ in session
    def _begin(self, w: World, bus: EventBus, a: dict[str, Any]) -> None:
        s: Survey = a["s"]
        t = w.t
        here = {aid for aid, p in a["participants"].items() if p["rsvp"] == "accepted" and p.get("arrived_t")}
        for aid, p in a["participants"].items():
            if p["rsvp"] == "accepted":
                p["rsvp"] = "attended" if aid in here else "no_show"
                if aid in here:
                    self.history[aid] = t
        product_name = ""
        if self.commerce and s.product_id and self.commerce.media and s.product_id in self.commerce.media.live:
            product_name = self.commerce.media.live[s.product_id].p.name
        runners = []
        for tb in a["tables"]:
            seats = [x for x in tb["seats"] if x in here]
            tb["present"] = seats
            if not seats:
                continue
            people = [self._person(w, aid, s, product_name) for aid in seats]
            r = TableRunner(s.model_dump(), tb["table_id"], tb["session_id"], people, llm=self.llm,
                            decider=self.decider, cfg=self.cfg, seed=w.seed, budget=a["budget"],
                            product_name=product_name or s.topic)
            runners.append({"runner": r, "cursor": 0, "table": tb})
        a["runners"] = runners
        a["session_t"] = t
        a["status"] = "in_session"

        async def run_all() -> None:
            await asyncio.gather(*(self._prep_memories(x["runner"], s) for x in runners))
            await asyncio.gather(*(x["runner"].run() for x in runners))

        a["tables_fut"] = asyncio.ensure_future(run_all())
        self._persist(a, {"status": "in_session", "session_t": t, "attended": len(here)})
        self.frames.append({"type": "survey", "survey_id": s.survey_id, "phase": "question", "question_id":
                            s.questions[0].question_id, "tables": [{"table_id": x["table"]["table_id"],
                                                                    "seats": x["table"]["present"]} for x in runners]})
        w.live_evts.append({"k": "survey", "survey_id": s.survey_id, "status": "in_session", "venue": self.venue,
                            "arrived": len(here), "expected": len(here), "name": self.venue_name})

    def _person(self, w: World, aid: int, s: Survey, product_name: str) -> Person:
        prof = w.profiles[aid]
        ph = w.phones[aid]
        pr = self.commerce.pairs.get(f"{aid}|{s.product_id}") if (self.commerce and s.product_id) else None
        exp = None
        if pr is not None:
            exp = "purchased" if pr.stage == "purchased" else ("store_visit" if pr.inquired else None)
        mem = [e["text"] for e in sorted(self.social.wm.get(aid, []), key=lambda e: (-e["importance"], -e["t"]))[:6]] \
            if self.social is not None else []
        age = phone_age_years(ph, w.t) if "bought_t" in ph else 0.0
        return Person(agent_id=aid, name=prof.name.split()[0], age=prof.age, occupation=prof.occupation,
                      income_band=prof.income_band, big5=dict(prof.persona.big5), style=prof.persona.speaking_style,
                      card=prof.persona_card, phone=f"{ph.get('brand')} {ph.get('tier')}, {age:.1f} years, "
                                                     f"{ph.get('condition')}",
                      attitude=pr.attitude if pr else 0.0, experience=exp, memories=mem)

    async def _prep_memories(self, r: TableRunner, s: Survey) -> None:
        """Top-6 own memories per participant for the topic (own MemoryStore only)."""
        if self.offline:
            return
        q = f"{r.product} {s.topic} " + " ".join(x.text for x in s.questions)
        for p in r.people:
            try:
                ms = await MemoryStore(p.agent_id, self.store, self.llm).retrieve(q, k=6)
                p.memories = [m.text for m in ms] or p.memories
            except Exception:  # noqa: BLE001
                pass

    def _release_items(self, w: World, bus: EventBus, a: dict[str, Any], t: int) -> None:
        """Emit timeline items that are due (start + dt ≤ now); everything goes through the bus (one writer)."""
        texts = []
        for x in a["runners"]:
            r: TableRunner = x["runner"]
            while x["cursor"] < len(r.items) and a["session_t"] + r.items[x["cursor"]]["dt"] <= t:
                it = r.items[x["cursor"]]
                x["cursor"] += 1
                if it["live"]:
                    self.frames.append({**it["live"], "t": t, **({"tables": [{"table_id": y["table"]["table_id"],
                                                                               "seats": y["table"]["present"]}
                                                                              for y in a["runners"]]}
                                                                 if it["live"].get("type") == "survey" else {})})
                if it["kind"] in LIVE_ONLY:
                    continue
                ev = bus.new(it["kind"], t, it["agent_id"], it["payload"], session_id=it["session_id"],
                             product_id=a["s"].product_id)
                if it["text"]:
                    kind, text, private = it["text"]
                    texts.append((kind, it["agent_id"], ev.event_id, text, private, it["session_id"]))
        if texts:
            self._background(self._texts(bus, texts, t, a["s"].product_id))

    # ------------------------------------------------------------------ after the session
    def _after(self, w: World, bus: EventBus, a: dict[str, Any]) -> None:
        a["status"] = "finishing"
        s: Survey = a["s"]
        t = w.t
        answers = [ans for x in a["runners"] for ans in x["runner"].answers]
        cost = sum(x["runner"].cost for x in a["runners"])
        self.gov.record(cost, "interactive")
        for x in a["runners"]:                                 # debrief: own memory + small belief nudge
            r: TableRunner = x["runner"]
            for p in r.people:
                mine = [y for y in r.answers if y.agent_id == p.agent_id]
                said = r.said.get(p.agent_id, [])
                stuck = r.retained.get(p.agent_id, [])
                stuck_who = ""
                if stuck:
                    sp = next((it["payload"]["speaker"] for it in r.items if it["kind"] == "message"
                               and it["payload"].get("message_id") == stuck[0]), None)
                    stuck_who = f"{r.by_id[int(sp)].name}'s point " if isinstance(sp, int) and sp in r.by_id else ""
                text = (f"I went to a {'focus group' if s.mode == 'focus_group' else 'survey'} at the {self.venue_name} "
                        f"about {r.product or s.topic}. " + (f"I said “{said[0][:80]}”. " if said else "") +
                        (f"{stuck_who}stuck with me. " if stuck_who else "") +
                        (f"I answered {key(mine[0].answer)[:60]}." if mine else ""))
                imp = min(9, 3 + len(said) + (2 if any(m.changed_from_prestance for m in mine) else 0))
                self._background(self._debrief(p.agent_id, text, imp, t, s, mine))
                if self.social is not None:
                    self.social.remember(p.agent_id, text, imp, "conversation", t, tag="focus group")

        async def post() -> dict[str, Any]:
            summaries = {}
            for x in a["runners"]:
                summaries[x["table"]["table_id"]] = await self._summary(x["runner"], s)
            return summaries

        a["post_fut"] = asyncio.ensure_future(post())
        a["answers"] = answers
        a["cost"] = cost
        self.frames.append({"type": "survey", "survey_id": s.survey_id, "phase": "results", "question_id": None,
                            "tables": [{"table_id": x["table"]["table_id"], "seats": x["table"]["present"]}
                                       for x in a["runners"]]})
        for q in s.questions:
            dist: dict[str, int] = {}
            for ans in answers:
                if ans.question_id == q.question_id:
                    k = bucket(q, ans.answer) if q.type == "open" else key(ans.answer)
                    dist[k] = dist.get(k, 0) + 1
            self.frames.append({"type": "survey_result", "survey_id": s.survey_id, "question_id": q.question_id,
                                "distribution": dist})

    async def _debrief(self, aid: int, text: str, imp: int, t: int, s: Survey, mine: list[Any]) -> None:
        try:
            ms = MemoryStore(aid, self.store, None)
            await ms.add(MemoryEntry(mid=f"survey-{s.survey_id}-{aid}", agent_id=aid, t=t, kind="conversation",
                                     text=text[:400], importance=imp,
                                     source={"channel": "focus_group", "survey_id": s.survey_id,
                                             "product_id": s.product_id}, entities=[self.venue_name], event_refs=[]))
            if s.product_id and mine:
                d = 0.05 * (sum(m.confidence for m in mine) / len(mine) - 0.5)
                b = await ms.beliefs([f"product:{s.product_id}"])
                if b:
                    await ms.update_belief(f"product:{s.product_id}", {"attitude": b[0].attitude + d, "t": t},
                                           cause_event_id=f"survey:{s.survey_id}")
        except Exception:  # noqa: BLE001 — read models only
            log.debug("survey debrief write failed", exc_info=True)

    async def _summary(self, r: TableRunner, s: Survey) -> str:
        public = [f"{r._label(it['payload']['speaker'])}: {it['payload']['text']}" for it in r.items
                  if it["kind"] == "message"]
        agg: dict[str, dict[str, int]] = {}
        for ans in r.answers:
            agg.setdefault(ans.question_id, {})
            k = key(ans.answer)[:40]
            agg[ans.question_id][k] = agg[ans.question_id].get(k, 0) + 1
        changed = sum(1 for x in r.answers if x.changed_from_prestance)
        if self.offline or r.budget.left <= 0:
            top = "; ".join(f"{q}: " + ", ".join(f"{k} ×{v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:3])
                            for q, d in agg.items())
            return f"{len(r.people)} participants, {len(public)} public messages. {top}. {changed} answer(s) changed " \
                   "from first impressions."
        from pydantic import BaseModel

        class Sum(BaseModel):
            summary: str

        pr = (open(__import__("pathlib").Path(__file__).resolve().parents[2] / "shared" / "prompts" / "survey_summary.md",
                   encoding="utf-8").read().replace("{public}", "\n".join(public[-60:]))
              .replace("{answers}", f"{agg} · changed from first impressions: {changed}"))
        try:
            res = await self.llm.generate(MODEL_FLASH, pr, Sum, purpose="survey_summary", reasoning="low",
                                          max_tokens=260, priority_class="interactive")
            r.cost += res.usage.cost_usd
            self.gov.record(res.usage.cost_usd, "interactive")
            return res.data.summary[:700]
        except Exception:  # noqa: BLE001
            return f"{len(r.people)} participants, {len(public)} public messages, {changed} changed answers."

    def _finish(self, w: World, bus: EventBus, a: dict[str, Any], empty: bool = False) -> None:
        s: Survey = a["s"]
        t = w.t
        summaries = {} if empty else a["post_fut"].result()
        for tid, text in summaries.items():
            tb = next(x for x in a["tables"] if x["table_id"] == tid)
            ev = bus.new("survey_summary", t, None, {"survey_id": s.survey_id, "table_id": tid, "summary": text},
                         session_id=tb["session_id"], product_id=s.product_id)
            self._background(self._texts(bus, [("survey_summary", None, ev.event_id, text, False, tb["session_id"])],
                                         t, s.product_id))
        answers = a.get("answers", [])
        cost = round(a.get("cost", 0.0) + sum(x["runner"].cost for x in a.get("runners", [])) * 0, 5)
        skipped = any(x["runner"].skipped_discussion for x in a.get("runners", []))
        counts = {"invited": len(a["participants"]),
                  "accepted": sum(1 for p in a["participants"].values() if p["rsvp"] in ("attended", "no_show", "accepted")),
                  "attended": sum(1 for p in a["participants"].values() if p["rsvp"] == "attended"),
                  "answers": len(answers), "changed": sum(1 for x in answers if x.changed_from_prestance)}
        bus.new("survey_completed", t, None, {"survey_id": s.survey_id, "counts": counts, "actual_usd": cost,
                                              "estimate_usd": s.estimate_usd, "discussion_skipped": skipped,
                                              "empty": empty}, product_id=s.product_id)
        self._release(w, bus, a)
        self._persist(a, {"status": "completed", "completed_t": t, "counts": counts, "actual_usd": cost,
                          "summaries": summaries, "discussion_skipped": skipped,
                          "participants": list(a["participants"].values())})
        w.live_evts.append({"k": "survey", "survey_id": s.survey_id, "status": "completed", "venue": self.venue,
                            "arrived": counts["attended"], "expected": counts["attended"], "name": self.venue_name})
        self.active = None

    def _release(self, w: World, bus: EventBus, a: dict[str, Any], cancelled: bool = False) -> None:
        """Close the table sessions; participants resume their routine (survey block ends now)."""
        m = simtime.minute_of_day(w.t)
        for tb in a.get("tables", []):
            if self.social is not None:
                self.social.sessions.close(tb["session_id"])
        for aid in a["participants"]:
            ag = w.agents[aid]
            ag.plan = [({**b, "e": max(b["s"] + 1, m)} if b.get("act") == "survey" and b["s"] <= m < b["e"] else b)
                       for b in ag.plan if not (b.get("act") == "survey" and b["s"] > m)]
        if cancelled:
            bus.new("survey_completed", w.t, None, {"survey_id": a["id"], "counts": {}, "actual_usd": 0.0,
                                                    "cancelled": True})

    # ------------------------------------------------------------------ io
    def _persist(self, a: dict[str, Any], upd: dict[str, Any]) -> None:
        self._background(asyncio.to_thread(self.store.set, "surveys", a["id"], upd, True))

    async def _texts(self, bus: EventBus, rows: list[tuple[str, int | None, str, str, bool, str | None]], t: int,
                     pid: str | None) -> None:
        vecs: list[list[float] | None] = [None] * len(rows)
        if self.embed_texts and rows:
            try:
                vecs = list(await embed_cached(self.llm, [r[3][:2000] for r in rows]))
            except Exception:  # noqa: BLE001
                pass
        for (kind, aid, eid, text, private, sid), v in zip(rows, vecs, strict=True):
            bus.emit_text({"text_id": f"{eid}:{aid}", "event_id": eid, "t": t, "day": simtime.day_of(t), "kind": kind,
                           "agent_id": aid, "product_id": pid, "session_id": sid, "private": private, "text": text,
                           "embedding": v or []})

    def _background(self, coro: Awaitable[Any]) -> None:
        fut = asyncio.ensure_future(coro)
        self._bg.add(fut)
        fut.add_done_callback(self._bg.discard)

    def status(self) -> dict[str, Any]:
        """Engine view for the API (active survey + queue)."""
        a = self.active
        if a is None:
            return {"active": None, "queue": list(self.queue)}
        arrived = sum(1 for p in a["participants"].values() if p.get("arrived_t"))
        return {"active": a["id"], "status": a["status"], "start_at_t": a["start_t"], "arrived": arrived,
                "expected": sum(1 for p in a["participants"].values() if p["rsvp"] in ("accepted", "attended")),
                "queue": list(self.queue), "venue": self.venue}

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint: queue + fatigue (an in-flight survey restarts from its Firestore doc after a restart)."""
        q = list(self.queue)
        if self.active is not None:
            q.insert(0, self.active["id"])
        return {"queue": q, "history": self.history}

    def load(self, d: dict[str, Any]) -> None:
        """Restore."""
        self.queue = list(d.get("queue") or [])
        self.history = {int(k): int(v) for k, v in (d.get("history") or {}).items()}


__all__ = ["SurveyRuntime", "Question", "age_band", "interest"]
