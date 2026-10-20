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
from engine.survey import outreach, recruit
from engine.survey.outreach import MIN_LEAD
from engine.survey.session import Budget, Person, TableRunner, bucket, key
from engine.world import World
from insights.likely_buyers import age_band
from mind.decision import DecisionAdapter
from mind.memory import MemoryStore, embed_cached
from mind.opinion import attrs_in
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
        self._now = 0                                # sim minute of the current tick (for hooks called between ticks)
        self._seed = 0
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
        """Bus listener: arrivals at the venue (check-in, or turned away when late) and flyers seen in stores."""
        a = self.active
        if a is None or ev.kind != "arrive" or ev.agent_id is None:
            return
        place, aid = ev.payload.get("place_id"), ev.agent_id
        if place == self.venue:
            p = a["participants"].get(aid)
            if p is None:
                return
            if p["rsvp"] == "accepted" and p.get("arrived_t") is None:
                p["arrived_t"] = ev.t
                a["dirty"] = True
                a["dirty_outreach"] = True
            elif p["rsvp"] == "no_show" and not p.get("no_show") and not p.get("turned_away") \
                    and a["status"] in ("in_session", "finishing"):
                p["turned_away"] = True                              # arrived after it began
                a.setdefault("late", []).append(aid)
            return
        if a["status"] == "recruiting" and "store_flyer" in a["s"].channels and self.commerce is not None \
                and place in self.commerce.store_by_place and aid in a["pool_set"] and aid not in a["decided"]:
            if float(stream(self._seed, "flyer", a["id"], aid).random()) < 0.5:
                a["queue"].append((ev.t, aid, "store_flyer"))

    # ------------------------------------------------------------------ tick
    async def tick(self, w: World, bus: EventBus) -> None:
        """Advance the active survey's state machine."""
        t = w.t
        self._now, self._seed = t, w.seed
        if self.active is None and self.queue:
            sid = self.queue.pop(0)
            doc = await asyncio.to_thread(self.store.get, "surveys", sid)
            if doc is not None and doc.get("status") not in ("cancelled", "completed"):
                self._start(w, bus, doc)
        a = self.active
        if a is None:
            return
        st = a["status"]
        if st in ("recruiting", "gathering"):
            self._inject(w, a)
            self._turn_away_late(w, bus, a)
        if st == "recruiting":
            self._outreach_tick(w, bus, a, t)
        elif st == "gathering":
            arrived = sum(1 for p in a["participants"].values() if p["rsvp"] == "accepted" and p.get("arrived_t"))
            exp = sum(1 for p in a["participants"].values() if p["rsvp"] == "accepted")
            if a.pop("dirty", False) or t % 5 == 0:
                w.live_evts.append({"k": "survey", "survey_id": a["id"], "status": "gathering", "venue": self.venue,
                                    "arrived": arrived, "expected": exp, "name": self.venue_name, **self._xy(w)})
                self._persist(a, {"outreach": self._outreach_doc(a)})
            if exp == 0 and t >= a["start_t"]:
                self._finish(w, bus, a, empty=True)
            elif exp and (arrived >= math.ceil(exp * float(self.cfg["timings"]["gather_share"]))
                          or t >= a["start_t"] + int(self.cfg["timings"]["gather_timeout"])):
                if t >= a["start_t"] or arrived >= exp:
                    self._begin(w, bus, a)
        elif st == "in_session":
            self._turn_away_late(w, bus, a)
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

    # ------------------------------------------------------------------ recruiting (outreach → decision → commitment)
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
        explicit = bool(s.start_at_t and s.start_at_t >= t + MIN_LEAD)
        start = int(s.start_at_t) if explicit and s.start_at_t else ((t + lead + rnd - 1) // rnd) * rnd
        m = simtime.minute_of_day(start)
        if not explicit and (m < 9 * 60 or m > 20 * 60):  # default slots run 09:00–20:00; a chosen time is honoured
            day = simtime.day_of(start) + (1 if m > 20 * 60 else 0)
            start = (day - 1) * 1440 + 10 * 60
        ev = bus.new("survey_created", t, None, {"survey_id": s.survey_id, "title": s.title, "mode": s.mode,
                                                 "n_questions": len(s.questions), "cohort": s.cohort_filter,
                                                 "wave": s.wave, "panel_id": s.panel_id,
                                                 "parent_survey_id": s.parent_survey_id, "product_id": s.product_id,
                                                 "product_ids": s.product_ids, "channels": s.channels,
                                                 "incentive": s.incentive.model_dump() if s.incentive else None,
                                                 "start_at_t": start, "max_participants": s.max_participants},
                     product_id=s.product_id)
        a: dict[str, Any] = {
            "id": s.survey_id, "s": s, "doc": doc, "status": "recruiting", "start_t": start, "pool": pool,
            "pool_set": set(pool), "participants": {}, "tables": [], "created_event": ev.event_id, "queue": [],
            "decided": set(), "wom_closeness": {}, "seen_by_channel": {}, "accepted_by_channel": {}, "wave": 1,
            "close_t": start - outreach.CLOSE_BEFORE, "second_wave_t": t + (start - t) // 2 if start - t >= 60 else None,
            "budget": Budget(left=max(0.0, float(self.gov.cfg["interactive_cap_usd"]) - self.gov.interactive_today))}
        self.active = a
        self._now, self._seed = t, w.seed
        n_panel = len(pool) if panel else min(len(pool), 3 * s.max_participants)
        if "panel" in s.channels or panel:
            self._schedule_panel(w, a, t, n_panel)
        self._post_community(w, bus, a, t)
        self._persist(a, {"status": "recruiting", "eligible": len(pool), "start_at_t": start,
                          "start_label": simtime.fmt(start), "venue": self.venue, "venue_name": self.venue_name,
                          "outreach": self._outreach_doc(a)})
        w.live_evts.append({"k": "survey", "survey_id": s.survey_id, "status": "recruiting", "venue": self.venue,
                            "arrived": 0, "expected": 0, "name": self.venue_name, **self._xy(w)})

    def _schedule_panel(self, w: World, a: dict[str, Any], t: int, n: int) -> None:
        """The agency messages a stratified sample; each person reads it at their own next phone session."""
        s: Survey = a["s"]
        ages = {aid: w.profiles[aid].age for aid in a["pool"]}
        for aid in outreach.sample_panel(a["pool"], n, ages, w.seed, f"{s.survey_id}-w{a['wave']}", a["decided"] | {x[1] for x in a["queue"]}):
            rng = stream(w.seed, "glance", s.survey_id, a["wave"], aid)
            if w.agents[aid].activity != "sleep" and float(rng.random()) < outreach.GLANCE_P:
                seen = t + 1 + int(rng.integers(0, 4))                   # a notification glanced at within minutes
            else:
                seen = outreach.next_session_start(w.profiles[aid].media.feed_sessions, t)
            a["queue"].append((seen, aid, "panel"))
        a["dirty_outreach"] = True

    def _post_community(self, w: World, bus: EventBus, a: dict[str, Any], t: int) -> None:
        """A recruitment thread on the forum: members read it at their next community session (some never do)."""
        s: Survey = a["s"]
        media = getattr(self.commerce, "media", None) if self.commerce is not None else None
        if "community" not in s.channels or media is None:
            return
        author = media.news_desk
        if author is None:
            author = next((p.agent_id for p in w.profiles if p.special_role == "reviewer"), None)
        if author is None:
            return
        reward = self._incentive_text(s)
        media._new_thread(w, bus, int(author), "r/BangaloreTech", f"Paid {'focus group' if s.mode == 'focus_group' else 'survey'}: {s.title}",
                          f"At the {self.venue_name}, {simtime.fmt(a['start_t'])}. {reward}", None)
        for aid in a["pool"]:
            if not w.profiles[aid].media.community or float(stream(w.seed, "community_see", s.survey_id, aid).random()) >= 0.6:
                continue
            a["queue"].append((outreach.next_session_start(w.profiles[aid].media.feed_sessions, t, app="community"),
                               aid, "community"))
        a["dirty_outreach"] = True

    @staticmethod
    def _incentive_text(s: Survey) -> str:
        inc = s.incentive
        bits = ([f"₹{inc.cash_inr} for your time"] if inc and inc.cash_inr else []) + [g.label for g in (inc.goodies if inc else [])]
        return ("You get " + " and ".join(bits) + ".") if bits else "No payment, just your opinion."

    def on_invite_told(self, listener: int, teller: int, closeness: float, survey_id: str) -> None:
        """A friend brought the survey up in conversation: the listener hears about it now, trusting the friend."""
        a = self.active
        if a is None or a["id"] != survey_id or a["status"] != "recruiting" or "word_of_mouth" not in a["s"].channels:
            return
        if listener in a["pool_set"] and listener not in a["decided"]:
            a["wom_closeness"][listener] = closeness
            a["queue"].append((self._now + 1, listener, "word_of_mouth"))

    def _outreach_tick(self, w: World, bus: EventBus, a: dict[str, Any], t: int) -> None:
        due = sorted(x for x in a["queue"] if x[0] <= t)
        if due:
            a["queue"] = [x for x in a["queue"] if x[0] > t]
            for _seen, aid, ch in due:
                self._decide(w, bus, a, aid, ch, t)
        s: Survey = a["s"]
        target = s.max_participants
        if a["second_wave_t"] is not None and t >= a["second_wave_t"]:       # too few yes's halfway: send a reminder wave
            a["second_wave_t"] = None
            accepted = sum(1 for p in a["participants"].values() if p["rsvp"] == "accepted")
            if accepted < 0.7 * target and ("panel" in s.channels or a["doc"].get("panel_agent_ids")):
                a["wave"] += 1
                self._schedule_panel(w, a, t, min(len(a["pool"]), 2 * (target - accepted) + 5))
                bus.new("survey_outreach", t, None, {"survey_id": s.survey_id, "channel": "panel", "wave": a["wave"],
                                                     "reminder": True}, product_id=s.product_id)
        accepted = sum(1 for p in a["participants"].values() if p["rsvp"] == "accepted")
        full = accepted >= math.ceil(target * 1.1) and not a["queue"]
        if t >= a["close_t"] or full:
            self._close_recruiting(w, bus, a, t)
        elif a.pop("dirty_outreach", False) or t % 5 == 0:
            self._persist(a, {"outreach": self._outreach_doc(a)})

    def _free_at_start(self, w: World, aid: int, a: dict[str, Any]) -> float:
        ag = w.agents[aid]
        if ag.plan_day != simtime.day_of(a["start_t"]):
            return 0.7                                               # their plan for that day does not exist yet
        m = simtime.minute_of_day(a["start_t"])
        blk = next((b for b in ag.plan if b["s"] <= m < b["e"]), None)
        return 1.0 if blk is None or blk["act"] in ("home", "cafe", "park", "shop", "eat", "roam") else 0.25

    def _decide(self, w: World, bus: EventBus, a: dict[str, Any], aid: int, channel: str, t: int) -> None:
        """One person has just heard about the session: do they come? (rules; the reason is built from what mattered)"""
        if aid in a["decided"]:
            return
        s: Survey = a["s"]
        a["decided"].add(aid)
        a["seen_by_channel"][channel] = a["seen_by_channel"].get(channel, 0) + 1
        a["dirty_outreach"] = True
        prof, ag = w.profiles[aid], w.agents[aid]
        bus.new("survey_invite", t, aid, {"survey_id": s.survey_id, "channel": channel}, product_id=s.product_id)
        venue = w.wm.place_by_id.get(self.venue)
        x, y = w.position(ag, float(t))[:2]
        dist = math.dist((x, y), venue.entrances[0]) if venue else 1500.0
        eta = outreach.eta_minutes(dist, prof.commute_mode)
        pairs = [self.commerce.pairs.get(f"{aid}|{pid}") for pid in s.product_ids] if self.commerce else []
        interest_v = max([interest(pr) for pr in pairs if pr is not None], default=0.3)
        inc = s.incentive
        assert inc is not None
        b5 = prof.persona.big5
        value = outreach.incentive_value(inc, prof.money.monthly_income_inr, list(prof.persona.interests),
                                         float(b5.get("E", 0.5)), any(pr is not None and pr.stage != "unaware" for pr in pairs))
        free = self._free_at_start(w, aid, a)
        fatigue = t - self.history.get(aid, -10**9) < int(self.cfg["fatigue_days"]) * 1440
        closeness = float(a["wom_closeness"].get(aid, 0.0))
        p = outreach.attend_propensity(interest=interest_v, free=free, extraversion=float(b5.get("E", 0.5)),
                                       openness=float(b5.get("O", 0.5)), incentive=value, channel=channel,
                                       closeness=closeness, dist_m=dist, fatigue=fatigue,
                                       job_high=job_dependence(prof.occupation) == "high")
        rng = stream(w.seed, "attend", s.survey_id, aid)
        yes = float(rng.random()) < p
        if t + eta > a["start_t"] + outreach.LATE_OK:
            yes, why = False, "I saw it too late to get there in time."
        elif not yes:
            why = ("It's too far for what it is." if dist > 2000 else "I'm busy then." if free < 0.5
                   else "I've done enough of these lately." if fatigue else "Not really my thing.")
        else:
            why = " ".join(x for x in (
                "The reward is welcome." if value > 0.35 else "", "I'm curious about it." if interest_v > 0.5 else "",
                "I'm free then." if free >= 1.0 else "", "A friend told me about it." if channel == "word_of_mouth" else "") if x) \
                or "Sounds fine, I'll go."
        accepted_n = sum(1 for q in a["participants"].values() if q["rsvp"] == "accepted")
        waitlisted = sum(1 for q in a["participants"].values() if q["rsvp"] == "waitlist")
        cap = math.ceil(s.max_participants * 1.1)
        status = "declined"
        if yes:
            status = "accepted" if accepted_n < cap else ("waitlist" if waitlisted < math.ceil(s.max_participants * 0.25) else "declined")
            if status == "declined":
                why = "The seats were already taken."
        rec: dict[str, Any] = {"agent_id": aid, "rsvp": status, "rsvp_reason": why, "arrived_t": None,
                               "no_show": False, "channel": channel, "seen_t": t, "eta": eta}
        if status == "accepted":
            c = float(b5.get("C", 0.5))
            buffer = outreach.leave_buffer(c, rng)
            trouble = self.commerce is not None and t - self.commerce.life_t.get(aid, -10**9) <= 1440
            rec["leave_t"] = max(t, a["start_t"] - eta - buffer)
            rec["no_show"] = float(rng.random()) < outreach.no_show_probability(float(self.cfg["no_show_p"]), c, trouble, dist)
            a["accepted_by_channel"][channel] = a["accepted_by_channel"].get(channel, 0) + 1
            if self.social is not None and "word_of_mouth" in s.channels:     # they will tell people about it
                self.social.agenda.add(aid, "survey_invite", t, hint="paid survey", about=s.survey_id,
                                       weight=min(0.9, 0.3 + 0.6 * value))
        a["participants"][aid] = rec
        bus.new("survey_rsvp", t, aid, {"survey_id": s.survey_id, "rsvp": "accept" if yes else "decline",
                                        "status": status, "reason": why, "channel": channel,
                                        "propensity": round(p, 3), "eta_min": eta}, product_id=s.product_id)

    def _close_recruiting(self, w: World, bus: EventBus, a: dict[str, Any], t: int) -> None:
        """Sign-ups close five minutes before the start (or when the seats are full): everyone left is gathering."""
        s: Survey = a["s"]
        a["queue"] = []
        a["status"] = "gathering"
        counts = {k: sum(1 for p in a["participants"].values() if p["rsvp"] == k) for k in ("accepted", "waitlist", "declined")}
        self._persist(a, {"status": "gathering", "accepted": counts["accepted"], "waitlist": counts["waitlist"],
                          "invited": len(a["decided"]), "outreach": self._outreach_doc(a)})
        self.frames.append({"type": "survey", "survey_id": s.survey_id, "phase": "gathering", "question_id": None,
                            "tables": []})
        if counts["accepted"] == 0:
            a["start_t"] = min(a["start_t"], t)

    def _outreach_doc(self, a: dict[str, Any]) -> dict[str, Any]:
        """The funnel for the room page: reached → accepted → on the way → checked in, by channel."""
        parts = a["participants"].values()
        return {"reached": len(a["decided"]), "seen_by_channel": dict(a["seen_by_channel"]),
                "accepted": sum(1 for p in parts if p["rsvp"] in ("accepted", "attended")),
                "accepted_by_channel": dict(a["accepted_by_channel"]),
                "declined": sum(1 for p in parts if p["rsvp"] == "declined"),
                "waitlist": sum(1 for p in parts if p["rsvp"] == "waitlist"),
                "on_the_way": sum(1 for p in parts if p.get("injected")),
                "checked_in": sum(1 for p in parts if p.get("arrived_t")),
                "turned_away": sum(1 for p in parts if p.get("turned_away")), "wave": a["wave"],
                "channels": list(a["s"].channels), "pending": len(a["queue"])}

    def _turn_away_late(self, w: World, bus: EventBus, a: dict[str, Any]) -> None:
        """People who reach the venue after the session has started are politely turned away."""
        for aid in a.pop("late", []):
            bus.new("survey_turned_away", w.t, aid, {"survey_id": a["id"]}, product_id=a["s"].product_id)

    def _inject(self, w: World, a: dict[str, Any]) -> None:
        """Planner: a 'survey' block at the venue from each accepter's own leave time (they travel on the road graph)."""
        per = int(self.cfg["timings"]["per_question_focus" if a["s"].mode == "focus_group" else "per_question_survey"])
        for aid, p in a["participants"].items():
            if p["rsvp"] != "accepted" or p.get("injected") or p.get("no_show"):
                continue
            ag = w.agents[aid]
            leave = int(p["leave_t"])
            if ag.plan_day != simtime.day_of(leave):
                continue
            s0 = simtime.minute_of_day(leave)
            dur = max(0, a["start_t"] - leave) + len(a["s"].questions) * per + 30
            ag.plan = insert_block(ag.plan, max(0, s0), min(1440, s0 + dur), "survey", self.venue)
            p["injected"] = True
            a["dirty_outreach"] = True
            w.live_evts.append({"k": "survey_trip", "a": aid, "survey_id": a["id"]})

    # ------------------------------------------------------------------ in session
    def _stance(self, aid: int, s: Survey) -> float:
        """Mean attitude of this person to the survey's products (0 when it has none)."""
        if not s.product_ids or self.commerce is None:
            return 0.0
        op = getattr(self.commerce, "opinion", None)
        vals = [float(op.attitude(aid, pid)) if op is not None else
                float(self.commerce.pairs[f"{aid}|{pid}"].attitude) if f"{aid}|{pid}" in self.commerce.pairs else 0.0
                for pid in s.product_ids]
        return sum(vals) / len(vals)

    def _begin(self, w: World, bus: EventBus, a: dict[str, Any]) -> None:
        s: Survey = a["s"]
        t = w.t
        here = {aid for aid, p in a["participants"].items() if p["rsvp"] == "accepted" and p.get("arrived_t")}
        for aid, p in a["participants"].items():
            if p["rsvp"] == "accepted":
                p["rsvp"] = "attended" if aid in here else "no_show"
                if aid in here:
                    self.history[aid] = t
        # tables are made from the people who actually turned up (a check-in desk seats them), not from the sign-up list
        stance = {aid: self._stance(aid, s) for aid in here}
        tables = recruit.seat(sorted(here), s.table_size, w.profiles, stance, w.seed, s.survey_id) if here else []
        sessions = self.social.sessions if self.social is not None else None
        a["tables"] = []
        for i, seats in enumerate(tables):
            tid = f"T{i + 1}"
            sid = sessions.open(seats, "focus_group", t=t, timeout=24 * 60) if sessions else None
            sid = sid or f"fg-{s.survey_id}-{tid}"
            a["tables"].append({"table_id": tid, "survey_id": s.survey_id, "session_id": sid, "seats": seats,
                                "present": seats, "moderator_id": f"moderator-{tid}"})
            for k, aid in enumerate(seats):
                a["participants"][aid].update({"table_id": tid, "seat": k})
                bus.new("survey_checkin", t, aid, {"survey_id": s.survey_id, "table_id": tid, "seat": k},
                        product_id=s.product_id)
        names = [self.commerce.media.live[pid].p.name for pid in s.product_ids
                 if self.commerce and self.commerce.media and pid in self.commerce.media.live]
        product_name = " / ".join(names)
        runners = []
        for tb in a["tables"]:
            seats = tb["seats"]
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
        self._persist(a, {"status": "in_session", "session_t": t, "attended": len(here), "tables": a["tables"],
                          "outreach": self._outreach_doc(a)})
        self.frames.append({"type": "survey", "survey_id": s.survey_id, "phase": "question", "question_id":
                            s.questions[0].question_id, "tables": [{"table_id": x["table"]["table_id"],
                                                                    "seats": x["table"]["present"]} for x in runners]})
        w.live_evts.append({"k": "survey", "survey_id": s.survey_id, "status": "in_session", "venue": self.venue,
                            "arrived": len(here), "expected": len(here), "name": self.venue_name, **self._xy(w)})

    def _person(self, w: World, aid: int, s: Survey, product_name: str) -> Person:
        prof = w.profiles[aid]
        ph = w.phones[aid]
        prs = [self.commerce.pairs.get(f"{aid}|{pid}") for pid in s.product_ids] if self.commerce else []
        prs = [p for p in prs if p is not None]
        exp = None
        if any(p.stage == "purchased" for p in prs):
            exp = "purchased"
        elif any(p.inquired for p in prs):
            exp = "store_visit"
        op = getattr(self.commerce, "opinion", None) if self.commerce is not None else None
        briefs = op.brief_many(aid, s.product_ids) if op is not None else ""
        mem = [e["text"] for e in sorted(self.social.wm.get(aid, []), key=lambda e: (-e["importance"], -e["t"]))[:6]] \
            if self.social is not None else []
        age = phone_age_years(ph, w.t) if "bought_t" in ph else 0.0
        return Person(agent_id=aid, name=prof.name.split()[0], age=prof.age, occupation=prof.occupation,
                      income_band=prof.income_band, big5={str(k): float(v) for k, v in prof.persona.big5.items()}, style=prof.persona.speaking_style,
                      card=prof.persona_card, phone=f"{ph.get('brand')} {ph.get('tier')}, {age:.1f} years, "
                                                     f"{ph.get('condition')}",
                      attitude=self._stance(aid, s), experience=exp, memories=mem, briefs=briefs)

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
                self._survey_evidence(p.agent_id, s)
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

    def _survey_evidence(self, aid: int, s: Survey) -> None:
        """Discussing the products at a table teaches a little about what the questions covered (credibility 0.5)."""
        op = getattr(self.commerce, "opinion", None) if self.commerce is not None else None
        if op is None or not s.product_ids:
            return
        covered = attrs_in(" ".join(f"{q.text} {' '.join(q.options or [])}" for q in s.questions)) or ["brand"]
        for pid in s.product_ids:
            op.evidence(aid, pid, covered, "focus_group", strength=0.8)

    async def _debrief(self, aid: int, text: str, imp: int, t: int, s: Survey, mine: list[Any]) -> None:
        try:
            ms = MemoryStore(aid, self.store, None)
            await ms.add(MemoryEntry(mid=f"survey-{s.survey_id}-{aid}", agent_id=aid, t=t, kind="conversation",
                                     text=text[:400], importance=imp,
                                     source={"channel": "focus_group", "survey_id": s.survey_id,
                                             "product_id": s.product_id}, entities=[self.venue_name], event_refs=[]))
            op = getattr(self.commerce, "opinion", None) if self.commerce is not None else None
            if op is None and s.product_id and mine:        # without the opinion engine: the old small nudge
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
        self._background(asyncio.to_thread(self._profile_docs, a, t))
        if not empty:
            self._pay_incentives(w, bus, a, t)
        self._release(w, bus, a)
        self._persist(a, {"status": "completed", "completed_t": t, "counts": counts, "actual_usd": cost,
                          "summaries": summaries, "discussion_skipped": skipped,
                          "participants": list(a["participants"].values())})
        w.live_evts.append({"k": "survey", "survey_id": s.survey_id, "status": "completed", "venue": self.venue,
                            "arrived": counts["attended"], "expected": counts["attended"], "name": self.venue_name,
                            **self._xy(w)})
        self.active = None

    def _pay_incentives(self, w: World, bus: EventBus, a: dict[str, Any], t: int) -> None:
        """Cash goes into savings, goodies into memory; people who got something talk about it (word of mouth)."""
        s: Survey = a["s"]
        inc = s.incentive
        if inc is None:
            return
        labels = [g.label for g in inc.goodies]
        got = ([f"₹{inc.cash_inr}"] if inc.cash_inr else []) + labels
        for aid, p in a["participants"].items():
            if p["rsvp"] != "attended":
                continue
            bus.new("incentive_paid", t, aid, {"survey_id": s.survey_id, "cash_inr": inc.cash_inr, "goodies": labels},
                    product_id=s.product_id)
            if inc.cash_inr and self.commerce is not None:
                self.commerce.spent[aid] = self.commerce.spent.get(aid, 0) - inc.cash_inr     # savings go up
            text = (f"I took part in a {'focus group' if s.mode == 'focus_group' else 'survey'} at the {self.venue_name}"
                    + (f" and got {' and '.join(got)}." if got else "."))
            self._background(MemoryStore(aid, self.store, None).add(MemoryEntry(
                mid=f"incentive-{s.survey_id}-{aid}", agent_id=aid, t=t, kind="observation", text=text[:300], importance=4,
                source={"channel": "survey", "survey_id": s.survey_id}, entities=[self.venue_name], event_refs=[])))
            if self.social is not None and got:
                self.social.agenda.add(aid, "got_goodies", t, hint="survey goodies", about=text[:80], weight=0.6)

    def _profile_docs(self, a: dict[str, Any], t: int) -> None:
        """Profile read models: each table's transcript in `conversations/{session}` with every agent's OWN private
        survey items under private[agent]; plus `agents/{id}/conversations/{session}` rows (kind focus_group)."""
        s: Survey = a["s"]
        for x in a.get("runners", []):
            r: TableRunner = x["runner"]
            sid = x["table"]["session_id"]
            msgs = [{"seq": it["payload"]["seq"], "speaker": it["payload"]["speaker"], "listener": it["payload"]["listener"],
                     "text": it["payload"]["text"], "question_id": it["payload"]["question_id"], "t": t}
                    for it in r.items if it["kind"] == "message"]
            private: dict[str, dict[str, Any]] = {}
            for it in r.items:
                if it["agent_id"] is not None and it["kind"].startswith("survey_"):
                    private.setdefault(str(it["agent_id"]), {}).setdefault("survey_items", []).append(
                        {"kind": it["kind"], "payload": it["payload"]})
            parts = [p.agent_id for p in r.people]
            conv = {"session_id": sid, "participants": parts, "kind": "focus_group", "t_start": a.get("session_t", t),
                    "t_end": t, "topics": [s.title], "product_mentions": [s.product_id] if s.product_id else [],
                    "n_messages": len(msgs), "rendered": True, "model": None, "survey_id": s.survey_id}
            self.store.set("conversations", sid, {"session_id": sid, "participants": parts, "t": t, "conversation": conv,
                                                  "messages": msgs, "private": private, "survey_id": s.survey_id})
            for aid in parts:
                self.store.set(f"agents/{aid}/conversations", sid, {
                    "session_id": sid, "with": None, "kind": "focus_group", "t": t, "label": simtime.fmt(t),
                    "topics": [s.title], "n_messages": len(msgs), "rendered": True, "survey_id": s.survey_id,
                    "first_line": msgs[0]["text"] if msgs else ""})

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

    def _xy(self, w: World) -> dict[str, float]:
        """Venue entrance in metres (for the World pin)."""
        pl = w.wm.place_by_id.get(self.venue)
        return {"x": round(pl.entrances[0][0], 1), "y": round(pl.entrances[0][1], 1)} if pl else {}

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
