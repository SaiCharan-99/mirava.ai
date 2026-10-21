"""Survey Room API (addendum B7). The api stores definitions and reads results; the engine runs surveys (one writer)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from engine.survey import outreach, recruit
from insights.tools import Tools, default_runner
from media.screen import get_screener, wrap
from shared import time as simtime
from shared.llm import FakeGemini, get_llm
from shared.models import MODEL_FLASH
from shared.schemas.survey import (
    ALL_CHANNELS,
    MAX_PARTICIPANTS,
    MAX_PRODUCTS,
    Channel,
    Incentive,
    InterestFilter,
    Question,
    Survey,
    default_goodies,
)
from shared.store import DocStore, get_store

router = APIRouter(prefix="/api")
STAGE_ORDER = ["aware", "curious", "researching", "inquiring", "deciding", "purchased", "postponed"]
ACCEPT_RATE = 0.38             # fallback share of eligible agents who accept and come when the mix can't be read
MAX_OPTIONS = 4


def store() -> DocStore:
    """Firestore (or emulator / memory in tests)."""
    return get_store()


def _engine(cmd: dict) -> dict | None:
    from api.products import _engine_command

    return _engine_command(cmd)


def _engine_state() -> dict:
    from api.main import _engine_get

    return _engine_get("/state") or {}


def remaining_interactive() -> float:
    """Interactive budget left today (engine governor)."""
    st = _engine_state().get("interactive") or {}
    return round(float(st.get("cap_usd", 5.0)) - float(st.get("used_usd", 0.0)), 4)


class SurveyIn(BaseModel):
    """POST /surveys body."""

    title: str = Field(min_length=3, max_length=120)
    mode: Literal["focus_group", "survey"] = "focus_group"
    product_id: str | None = None
    topic: str = ""
    questions: list[dict[str, Any]]
    cohort_filter: str | None = None
    interest_filter: InterestFilter | None = None
    max_participants: int = Field(40, ge=1, le=MAX_PARTICIPANTS)
    table_size: int = Field(8, ge=6, le=10)
    start_at_t: int | None = None
    product_ids: list[str] = Field(default_factory=list, max_length=MAX_PRODUCTS)
    incentive: Incentive | None = None            # goodies only: any cash sent is ignored
    channels: list[Channel] = Field(default_factory=lambda: list(ALL_CHANNELS))


def _questions(raw: list[dict[str, Any]]) -> list[Question]:
    qs = []
    for i, q in enumerate(raw[:10]):
        q = {**q, "question_id": q.get("question_id") or f"q{i + 1}"}
        qs.append(Question.model_validate(q))
    for i, q in enumerate(qs):                             # the builder allows 2–4 options (older surveys may have more)
        if q.type in ("single", "multi") and len(q.options or []) > MAX_OPTIONS:
            raise HTTPException(422, f"Question {i + 1} has more than {MAX_OPTIONS} options")
    if not qs:
        raise HTTPException(422, "add at least one question")
    if len(raw) > 10:
        raise HTTPException(422, "at most 10 questions")
    return qs


def _eligible(cohort: str | None, interest: InterestFilter | None) -> int:
    """Eligible count from the views (same filter language as the cohort tool)."""
    r = default_runner()
    t = Tools(r)
    if cohort and cohort.strip():
        ids = set(t.cohort(cohort)["agent_ids"])
    else:
        rows, _ = r.run("SELECT agent_id FROM agents_latest", None, trusted=True)
        ids = {int(x["agent_id"]) for x in rows}
    rows, _ = r.run("SELECT agent_id FROM agents_latest WHERE special_role != 'none'", None, trusted=True)
    ids -= {int(x["agent_id"]) for x in rows}
    if interest and interest.product_id:
        lo = STAGE_ORDER.index(interest.min_stage) if interest.min_stage in STAGE_ORDER else 0
        ok = STAGE_ORDER[lo:]
        rows, _ = r.run("SELECT agent_id, stage FROM beliefs_latest WHERE product_id = @p", {"p": interest.product_id},
                        trusted=True)
        ids &= {int(x["agent_id"]) for x in rows if x["stage"] in ok}
    return len(ids)


def lint_rules(qs: list[Question]) -> list[dict[str, str]]:
    """Offline survey-question lint (Flash in the cloud adds more)."""
    out = []
    for q in qs:
        tl = q.text.lower()
        if re.search(r"\b(don't you|wouldn't you|isn't it|amazing|best|obviously|surely)\b", tl):
            out.append({"question_id": q.question_id, "kind": "leading", "fix": "Use neutral wording."})
        if " and " in tl and tl.count("?") <= 1 and q.type != "open" and re.search(r"\b(and|&)\b.*\?", tl):
            out.append({"question_id": q.question_id, "kind": "double_barrelled", "fix": "Ask one thing per question."})
        opts = [o.strip().lower() for o in (q.options or [])]
        if len(set(opts)) != len(opts):
            out.append({"question_id": q.question_id, "kind": "overlapping_options", "fix": "Remove duplicate options."})
        nums = [[int(x) for x in re.findall(r"\d+", o.replace(",", ""))] for o in opts]
        rngs = [(n[0], n[-1]) for n in nums if len(n) >= 2]
        for i in range(len(rngs)):
            for j in range(i + 1, len(rngs)):
                if rngs[i][0] < rngs[j][1] and rngs[j][0] < rngs[i][1]:
                    out.append({"question_id": q.question_id, "kind": "overlapping_options",
                                "fix": "Make number ranges non-overlapping."})
    return out


class LintWarning(BaseModel):
    """One lint warning."""

    question_id: str
    kind: Literal["leading", "double_barrelled", "loaded", "overlapping_options", "unclear", "too_long"]
    fix: str


class LintOut(BaseModel):
    """Lint output."""

    warnings: list[LintWarning] = Field(default_factory=list)


async def lint(qs: list[Question]) -> list[dict[str, str]]:
    """Rules + Flash (warns, never blocks)."""
    out = lint_rules(qs)
    llm = get_llm()
    if isinstance(llm, FakeGemini):
        return out
    try:
        pr = (open(__import__("pathlib").Path(__file__).resolve().parents[1] / "shared" / "prompts" / "survey_lint.md",
                   encoding="utf-8").read().replace("{questions}", wrap(json.dumps([q.model_dump() for q in qs]),
                                                                       "questions")))
        res = await llm.generate(MODEL_FLASH, pr, LintOut, purpose="survey_lint", reasoning="low", max_tokens=400,
                                 priority_class="interactive")
        seen = {(w["question_id"], w["kind"]) for w in out}
        out += [w.model_dump() for w in res.data.warnings if (w.question_id, w.kind) not in seen]
    except Exception:  # noqa: BLE001 — lint is advisory
        pass
    return out


def expected_attendance(eligible: int, max_participants: int, channels: list[str], inc: Incentive) -> int:
    """Who actually turns up: the share who hear about it (channels) × the average chance a person from this
    population says yes (income-aware: the same reward means more to people with less) × not flaking."""
    if eligible <= 0:
        return 0
    from population.config import load

    try:
        rows, _ = default_runner().run("SELECT income_band, COUNT(*) AS n FROM agents_latest GROUP BY 1", None, trusted=True)
        mix = {str(r["income_band"]): float(r["n"]) for r in rows}
    except Exception:  # noqa: BLE001 — fall back to an even mix
        mix = {}
    ranges = load("markets/indiranagar")["income_ranges"]
    mix = {b: mix.get(b, 1.0) for b in ranges}
    total = sum(mix.values())
    rate = 0.0
    for band, n in mix.items():
        lo, hi = ranges[band]
        value = outreach.incentive_value(inc, int((lo + hi) / 2), [], 0.5)
        rate += n / total * outreach.attend_propensity(interest=0.3, free=0.6, extraversion=0.5, openness=0.5,
                                                       incentive=value, channel="panel", closeness=0.0, dist_m=1200,
                                                       fatigue=False, job_high=False)
    reach = outreach.reach_share(channels, max_participants, eligible)
    n = int(round(eligible * reach * rate * (1 - 0.06)))
    return max(1, min(max_participants, n))


def _invalid_question(e: ValidationError, raw: list[dict[str, Any]]) -> str:
    """Friendly message for a bad question ("Question 3 needs text")."""
    err = e.errors()[0]
    n = next((i + 1 for i, q in enumerate(raw) if not str(q.get("text", "")).strip()), None)
    if n is not None and "text" in [str(x) for x in err.get("loc", ())]:
        return f"Question {n} needs text"
    return f"invalid question: {err['msg']}"


def _plan(body: SurveyIn) -> tuple[Survey, int, int, dict[str, Any], list[Question]]:
    """Validate and size a survey (no writes, no model calls): (survey, eligible, expected attendance, estimate, qs)."""
    sc = get_screener().screen(body.title + " " + body.topic + " " + " ".join(str(q.get("text", "")) for q in body.questions))
    if not sc.ok:
        raise HTTPException(422, "refused by screening (political content)")
    try:
        qs = _questions(body.questions)
    except ValidationError as e:
        raise HTTPException(422, _invalid_question(e, body.questions)) from e
    try:
        eligible = _eligible(body.cohort_filter, body.interest_filter)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"bad audience filter: {str(e)[:160]}") from e
    inc = Incentive(cash_inr=0, goodies=body.incentive.goodies if body.incentive else default_goodies(),
                    note=body.incentive.note if body.incentive else "")
    expected = expected_attendance(eligible, body.max_participants, list(body.channels), inc)
    sid = "sv-" + hashlib.sha256(json.dumps([body.model_dump(mode="json"), _engine_state().get("t", 0)]).encode()
                                 ).hexdigest()[:8]
    s = Survey(survey_id=sid, title=body.title, mode=body.mode, product_id=body.product_id, topic=body.topic,
               questions=qs, cohort_filter=body.cohort_filter, interest_filter=body.interest_filter,
               max_participants=body.max_participants, table_size=body.table_size, incentive=inc, channels=list(body.channels), product_ids=list(body.product_ids),
               start_at_t=body.start_at_t)
    est = recruit.estimate(s, expected or 1)
    s.estimate_usd = est["usd"]
    return s, eligible, expected, est, qs


@router.post("/surveys/estimate")
def estimate_survey(body: SurveyIn) -> dict[str, Any]:
    """Size and cost a draft while the form is being edited: NO store write, NO model call (rule lint only)."""
    s, eligible, expected, est, qs = _plan(body)
    msg = "No agents match this audience — widen the filters." if eligible == 0 else None
    reach = int(round(eligible * outreach.reach_share(list(body.channels), body.max_participants, eligible)))
    return {"eligible": eligible, "reach": reach, "expected_attendance": expected,
            "tables": max(1, math.ceil((expected or 1) / s.table_size)),
            "estimate_usd": est["usd"], "estimate": est, "remaining_interactive_usd": remaining_interactive(),
            "lint": lint_rules(qs), "message": msg}


@router.post("/surveys")
async def create_survey(body: SurveyIn) -> dict[str, Any]:
    """Create the survey doc (called on Launch only) → eligible count, expected attendance, tables, estimate, lint.
    Rule lint only: the model lint belongs to the "Check questions" button, so Launch never waits on a model call."""
    s, eligible, expected, est, qs = _plan(body)
    sid = s.survey_id
    warnings = lint_rules(qs)
    doc = {**s.model_dump(mode="json"), "created_t": int(_engine_state().get("t") or 0), "eligible": eligible,
           "expected_attendance": expected,
           "tables_n": max(1, math.ceil((expected or 1) / s.table_size)), "estimate": est, "lint": warnings}
    store().set("surveys", sid, doc)
    msg = "No agents match this audience — widen the filters." if eligible == 0 else None
    return {"survey_id": sid, "eligible": eligible, "expected_attendance": expected, "tables": doc["tables_n"],
            "estimate_usd": est["usd"], "estimate": est, "remaining_interactive_usd": remaining_interactive(),
            "lint": warnings, "message": msg}


@router.post("/surveys/lint")
async def lint_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Question lint (warnings only)."""
    try:
        qs = _questions(body.get("questions") or [])
    except (ValidationError, HTTPException) as e:
        return {"warnings": [{"question_id": "", "kind": "unclear", "fix": str(getattr(e, "detail", e))[:160]}]}
    return {"warnings": await lint(qs)}


@router.post("/surveys/{sid}/launch")
def launch_survey(sid: str) -> dict[str, Any]:
    """Recruiting starts (refused when the estimate exceeds the remaining interactive budget, or nobody is eligible)."""
    doc = store().get("surveys", sid)
    if doc is None:
        raise HTTPException(404, "unknown survey")
    if doc.get("status") not in ("draft", None):
        raise HTTPException(409, f"survey is {doc.get('status')}")
    if int(doc.get("eligible", 0)) == 0 and not doc.get("panel_agent_ids"):
        raise HTTPException(422, "no eligible agents for this audience")
    left = remaining_interactive()
    if float(doc.get("estimate_usd", 0)) > left:
        raise HTTPException(402, f"estimate ${doc['estimate_usd']:.2f} exceeds the remaining interactive budget "
                                 f"${left:.2f}; try fewer participants, fewer questions or survey mode")
    res = _engine({"type": "survey_launch", "survey_id": sid})
    if res is None or not res.get("ok"):
        raise HTTPException(503, "world-engine unreachable")
    store().set("surveys", sid, {"status": "recruiting"}, True)
    return {"survey_id": sid, "status": "recruiting", "queued": bool(res.get("queued"))}


@router.post("/surveys/{sid}/cancel")
def cancel_survey(sid: str) -> dict[str, Any]:
    """Cancel; participants are released by the engine."""
    if store().get("surveys", sid) is None:
        raise HTTPException(404, "unknown survey")
    _engine({"type": "survey_cancel", "survey_id": sid})
    store().set("surveys", sid, {"status": "cancelled"}, True)
    return {"survey_id": sid, "status": "cancelled"}


@router.post("/surveys/{sid}/rerun")
def rerun_survey(sid: str) -> dict[str, Any]:
    """Wave n+1 with the same questions; re-invites the same panel (attendance decided again)."""
    doc = store().get("surveys", sid)
    if doc is None:
        raise HTTPException(404, "unknown survey")
    panel = [p["agent_id"] for p in doc.get("participants", []) if p.get("rsvp") == "attended"]
    if not panel:
        raise HTTPException(422, "the survey has no attended participants yet")
    wave = int(doc.get("wave", 1)) + 1
    nid = f"{doc.get('panel_id') or sid}-w{wave}"
    new = {k: v for k, v in doc.items() if k in Survey.model_fields}
    new.update({"survey_id": nid, "wave": wave, "panel_id": doc.get("panel_id") or sid, "parent_survey_id": sid,
                "status": "draft", "start_at_t": None, "actual_usd": 0.0, "max_participants": min(MAX_PARTICIPANTS,
                                                                                                len(panel))})
    s = Survey.model_validate(new)
    est = recruit.estimate(s, max(1, int(len(panel) * 0.8)))
    store().set("surveys", nid, {**s.model_dump(mode="json"), "estimate_usd": est["usd"], "estimate": est,
                                 "eligible": len(panel), "expected_attendance": int(len(panel) * 0.8),
                                 "panel_agent_ids": panel})
    store().set("surveys", sid, {"panel_saved": True}, True)
    return {"survey_id": nid, "wave": wave, "panel": len(panel), "estimate_usd": est["usd"]}


def timer(start_at_t: int | None, st: dict[str, Any] | None = None) -> dict[str, Any]:
    """One clock for every viewer: seconds to start from the world clock and its real rate (slowed → adjusts)."""
    st = st if st is not None else _engine_state()
    now = int(st.get("t") or 0)
    rate = float((st.get("scale") or {}).get("sim_min_per_real_s") or 0.4)
    if st.get("slowed"):
        rate = rate                      # the engine already reports its current (slowed) rate
    secs = None if start_at_t is None else round(max(0.0, (int(start_at_t) - now) / max(1e-6, rate)), 1)
    return {"now_t": now, "sim_min_per_real_s": rate, "seconds_to_start": secs,
            "start_label": simtime.fmt(int(start_at_t)) if start_at_t is not None else None}


def _counts_from_doc(doc: dict[str, Any]) -> dict[str, int]:
    """Funnel counts from the persisted outreach doc (when the engine is not reachable)."""
    o = doc.get("outreach") or {}
    return {"invited": int(o.get("reached", 0)) + int(o.get("pending", 0)), "replied": int(o.get("reached", 0)),
            "accepted": int(o.get("accepted", 0)), "waitlist": int(o.get("waitlist", 0)),
            "walking": max(0, int(o.get("on_the_way", 0)) - int(o.get("checked_in", 0))),
            "arrived": int(o.get("checked_in", 0))}


@router.get("/surveys/config")
def survey_config() -> dict[str, Any]:
    """Builder limits and timings (lead time in sim minutes)."""
    c = recruit.cfg()
    return {"lead_min": int(c["timings"]["lead_min"]), "slot_round": int(c["timings"]["slot_round"]),
            "max_participants": MAX_PARTICIPANTS, "max_questions": int(c["max_questions"]),
            "venue": c["venue"]["name"], "default_goodies": [g.model_dump() for g in default_goodies()]}


@router.get("/surveys/active")
def active_survey() -> dict[str, Any] | None:
    """The one survey that is recruiting, gathering or in session (or just finished), for the global banner."""
    st = _engine_state()
    sv = st.get("surveys") or {}
    if sv.get("active"):
        doc = store().get("surveys", str(sv["active"])) or {}
        return {"survey_id": sv["active"], "title": sv.get("title") or doc.get("title"), "mode": sv.get("mode"),
                "status": sv.get("status"), "start_at_t": sv.get("start_at_t"), "counts": sv.get("counts") or {},
                "q_index": sv.get("q_index", -1), "n_questions": sv.get("n_questions"), "viewers": sv.get("viewers", 0),
                **timer(sv.get("start_at_t"), st)}
    last = sv.get("last_done")
    if last and int(st.get("t") or 0) - int(last.get("t", 0)) <= 180:      # finished in the last 3 sim hours
        return {"survey_id": last["survey_id"], "title": last.get("title"), "status": "completed",
                "attended": last.get("attended"), **timer(None, st)}
    if not st:                                    # engine unreachable: fall back to Firestore
        for d in store().list("surveys", 200):
            if d.get("status") in ("recruiting", "gathering", "in_session", "finishing"):
                return {"survey_id": d["survey_id"], "title": d.get("title"), "mode": d.get("mode"),
                        "status": d["status"], "start_at_t": d.get("start_at_t"), "counts": _counts_from_doc(d),
                        **timer(d.get("start_at_t"), st)}
    return None


@router.get("/surveys/{sid}/live-state")
def live_state(sid: str, table: str | None = None, include_private: int = 0) -> dict[str, Any]:
    """The room right now, from the engine's memory (no analytics lag). 404 when it isn't running."""
    from api.main import _engine_get

    q = f"?private={1 if include_private else 0}" + (f"&table={table}" if table else "")
    st = _engine_get(f"/surveys/{sid}/live-state{q}")
    if st is None:
        raise HTTPException(404, "not running")
    return {**st, **timer(st.get("start_at_t"), {"t": st.get("now_t"), "scale": {"sim_min_per_real_s":
                                                                                   st.get("sim_min_per_real_s")}})}


@router.get("/surveys")
def list_surveys() -> list[dict[str, Any]]:
    """All surveys, newest first (sessions list)."""
    from shared.products import active_products

    names = {p["product_id"]: p["name"] for p in active_products(store(), include_ended=True, include_drafts=True)}
    rows = store().list("surveys", 200)
    out = []
    for d in rows:
        r = {k: d.get(k) for k in ("survey_id", "title", "mode", "status", "wave", "panel_id", "product_id",
                                   "product_ids", "start_at_t", "start_label", "estimate_usd", "actual_usd", "eligible",
                                   "completed_t", "created_t", "max_participants")}
        r["n_attended"] = (d.get("counts") or {}).get("attended")
        r["product_name"] = " / ".join(names[p] for p in (d.get("product_ids") or ([d["product_id"]] if d.get("product_id")
                                                                                   else [])) if p in names) or None
        out.append(r)
    return sorted(out, key=lambda r: (int(r.get("start_at_t") or r.get("created_t") or 0), r["survey_id"]), reverse=True)


def results(sid: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Per question: distribution before (first private answer) and after (final ballot), prestance → final shift,
    by age band, influence types, scale values, quotes; plus who-moved-whom edges and said-vs-answered pairs."""
    from insights import survey_report as rep
    from insights.likely_buyers import age_band

    r = default_runner()
    p = {"s": sid}
    ans, _ = r.run("SELECT a.*, g.age, g.income_band, g.name FROM v_survey_answers a LEFT JOIN agents_latest g "
                   "ON g.agent_id = a.agent_id WHERE a.survey_id = @s", p, trusted=True)
    try:
        msgs, _ = r.run("SELECT message_id, speaker_id, question_id, text, t, seq FROM v_survey_messages "
                        "WHERE survey_id = @s ORDER BY t, seq", p, trusted=True)
    except Exception:  # noqa: BLE001 — results still work without the transcript
        msgs = []
    speaker_of = {str(m["message_id"]): (int(m["speaker_id"]) if m["speaker_id"] is not None else "moderator")
                  for m in msgs}
    said: dict[tuple[int, str], str] = {}
    for m in msgs:                                         # the last thing each person said on each question
        if m["speaker_id"] is not None:
            said[(int(m["speaker_id"]), str(m["question_id"]))] = str(m["text"])
    out = []
    for q in doc.get("questions", []):
        rows = [a for a in ans if a["question_id"] == q["question_id"]]
        dist: dict[str, int] = {}
        pre_dist: dict[str, int] = {}
        shift: dict[str, dict[str, int]] = {}
        seg: dict[str, dict[str, int]] = {}
        for a in rows:
            v = str(a["answer"]) if q["type"] != "open" else "answered"
            dist[v] = dist.get(v, 0) + 1
            if a.get("prestance") not in (None, "None"):
                pre = str(a["prestance"]) if q["type"] != "open" else "answered"
                pre_dist[pre] = pre_dist.get(pre, 0) + 1
                shift.setdefault(pre, {})[v] = shift.setdefault(pre, {}).get(v, 0) + 1
            band = age_band(int(a.get("age") or 0))
            seg.setdefault(band, {})[v] = seg.setdefault(band, {}).get(v, 0) + 1
        quotes = [{"agent_id": a["agent_id"], "name": a.get("name"), "text": a["reason"], "tag": a["influence_type"],
                   "private": False, "answer": a["answer"], "changed": a["changed_from_prestance"],
                   "prestance": a.get("prestance")}
                  for a in sorted(rows, key=lambda a: (not a["changed_from_prestance"], a["agent_id"]))[:8]]
        item: dict[str, Any] = {
            "question_id": q["question_id"], "text": q["text"], "type": q["type"], "options": q.get("options"),
            "scale": q.get("scale"), "distribution": dist, "pre_distribution": pre_dist, "shift": shift,
            "by_segment": seg, "quotes": quotes, "influence": rep.influence_counts(rows),
            "changed": sum(1 for a in rows if a["changed_from_prestance"]), "n": len(rows),
            "satisficed": sum(1 for a in rows if a["effort"] == "satisficed"),
            "gap": sum(1 for a in rows if a["public_private_gap"])}
        if q["type"] == "scale":
            item["values_after"] = [float(a["answer_value"]) for a in rows if a.get("answer_value") is not None]
            item["values_before"] = [float(a["prestance"]) for a in rows
                                     if str(a.get("prestance")).replace(".", "", 1).lstrip("-").isdigit()]
        if q["type"] == "open":
            item["texts"] = [{"agent_id": a["agent_id"], "name": a.get("name"), "text": str(a["answer"])}
                             for a in rows if a.get("answer")]
        out.append(item)
    n = len({a["agent_id"] for a in ans})
    changed = sum(1 for a in ans if a["changed_from_prestance"])
    return {"questions": out, "n_attended": n, "changed_share": round(changed / max(1, len(ans)), 3),
            "changed_people": len({a["agent_id"] for a in ans if a["changed_from_prestance"]}),
            "gap_people": len({a["agent_id"] for a in ans if a["public_private_gap"]}),
            "edges": rep.edges(ans, speaker_of), "gap_pairs": rep.gap_pairs(ans, said),
            "seats": {str(a["agent_id"]): a.get("table_id") for a in ans},
            "summaries": doc.get("summaries") or {},
            "participation_effect": "Taking part is itself an experience: each participant now remembers the session, "
                                    "which can shift later answers (participation effect).",
            "notes": (["Budget ran out: some discussion turns were skipped (ballots all completed)."]
                      if doc.get("discussion_skipped") else [])}


async def report_extras(sid: str, doc: dict[str, Any], res: dict[str, Any]) -> None:
    """Themes for open questions and three headline findings: computed once after completion, stored on the doc."""
    from insights import survey_report as rep

    cached: dict[str, Any] = dict(doc.get("report") or {})
    if cached.get("findings") is None:
        llm = get_llm()
        th = {q["question_id"]: await rep.themes(q.get("texts") or [], llm) for q in res["questions"] if q["type"] == "open"}
        cached = {"themes": th, "findings": await rep.findings(res, llm)}
        store().set("surveys", sid, {"report": cached}, True)
    res["findings"] = cached["findings"]
    for q in res["questions"]:
        if q["type"] == "open":
            q["themes"] = dict(cached.get("themes") or {}).get(q["question_id"], [])


@router.get("/surveys/{sid}")
async def get_survey(sid: str, include_private: int = 0) -> dict[str, Any]:
    """Definition, status, participants (reasons only with include_private=1, labelled), tables, results."""
    doc = store().get("surveys", sid)
    if doc is None:
        raise HTTPException(404, "unknown survey")
    parts = doc.get("participants", [])
    if not include_private:
        parts = [{k: v for k, v in p.items() if k != "rsvp_reason"} for p in parts]
    else:
        parts = [{**p, "rsvp_reason_label": "private"} for p in parts]
    import asyncio

    est = await asyncio.to_thread(_engine_state)
    st = est.get("surveys") or {}
    live = st if st.get("active") == sid else None
    out = {**{k: v for k, v in doc.items() if k != "participants"}, "participants": parts, "live": live,
           **timer(live.get("start_at_t") if live else doc.get("start_at_t"), est),
           "counts": (live or {}).get("counts") or _counts_from_doc(doc)}
    if live:
        out["status"] = live.get("status", out.get("status"))
    if doc.get("status") in ("completed", "in_session", "balloting", "finishing"):
        try:
            out["results"] = await asyncio.to_thread(results, sid, doc)
            if doc.get("status") == "completed":
                await report_extras(sid, doc, out["results"])
        except Exception as e:  # noqa: BLE001
            out["results_error"] = str(e)[:200]
    if doc.get("parent_survey_id") or doc.get("panel_saved"):
        try:
            out["waves"] = waves(sid)
        except Exception:  # noqa: BLE001
            out["waves"] = None
    return out


@router.get("/surveys/{sid}/transcript")
def transcript(sid: str, table: str | None = Query(None)) -> list[dict[str, Any]]:
    """Public messages, ordered."""
    p: dict[str, Any] = {"s": sid}
    tf = ""
    if table:
        tf = " AND table_id = @tb"
        p["tb"] = table
    rows, _ = default_runner().run(f"SELECT * FROM v_survey_messages WHERE survey_id = @s{tf} ORDER BY t, table_id, seq",
                                   p, trusted=True)
    return rows


@router.get("/surveys/{sid}/agents/{aid}")
def agent_detail(sid: str, aid: int) -> dict[str, Any]:
    """That agent's prestance, thoughts, decisions, heard buffer and answers (private items labelled)."""
    rows, _ = default_runner().run(
        "SELECT kind, t, payload FROM events WHERE agent_id = @a AND kind IN ('survey_rsvp','survey_prestance',"
        "'survey_thought','survey_decision','survey_heard','survey_answer') AND JSON_VALUE(payload, '$.survey_id') = @s "
        "ORDER BY t", {"a": aid, "s": sid}, trusted=True)
    out: dict[str, Any] = {"agent_id": aid, "survey_id": sid, "items": []}
    for r in rows:
        pl = r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])
        out["items"].append({"kind": r["kind"], "t": r["t"], "private": r["kind"] != "survey_answer", "payload": pl})
    return out


def waves(sid: str) -> dict[str, Any]:
    """Wave comparison for the panel: distribution per wave and per-agent change table (+ why it changed)."""
    r = default_runner()
    rows, _ = r.run("SELECT * FROM v_survey_waves WHERE panel_id = (SELECT COALESCE(panel_id, survey_id) FROM v_surveys "
                    "WHERE survey_id = @s LIMIT 1) ORDER BY wave, question_id, agent_id", {"s": sid}, trusted=True)
    by: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    dist: dict[str, dict[int, dict[str, int]]] = {}
    for x in rows:
        by.setdefault((x["question_id"], int(x["agent_id"])), {})[int(x["wave"])] = x
        dist.setdefault(x["question_id"], {}).setdefault(int(x["wave"]), {})
        dist[x["question_id"]][int(x["wave"])][str(x["answer"])] = dist[x["question_id"]][int(x["wave"])].get(
            str(x["answer"]), 0) + 1
    changes = []
    for (qid, aid), ws in sorted(by.items()):
        ks = sorted(ws)
        for a, b in zip(ks, ks[1:], strict=False):
            if str(ws[a]["answer"]) != str(ws[b]["answer"]):
                changes.append({"question_id": qid, "agent_id": aid, "from_wave": a, "to_wave": b,
                                "from": ws[a]["answer"], "to": ws[b]["answer"], "t0": ws[a]["t"], "t1": ws[b]["t"],
                                "why": (store().get("survey_why", f"{sid}-{qid}-{aid}-{b}") or {}).get("why"),
                                "why_event_ids": (store().get("survey_why", f"{sid}-{qid}-{aid}-{b}") or {}).get("event_ids", [])})
    return {"distribution": dist, "changes": changes}


@router.post("/surveys/{sid}/explain")
async def explain_changes(sid: str) -> dict[str, Any]:
    """'Why it changed': Flash explains each changed answer ONLY from that agent's own events between the waves."""
    from pydantic import BaseModel as BM

    class Why(BM):
        why: str
        event_ids: list[str] = Field(default_factory=list)

    w = waves(sid)
    r = default_runner()
    llm = get_llm()
    done = 0
    for c in w["changes"][:40]:
        evs, _ = r.run("SELECT event_id, kind, t, payload FROM events WHERE agent_id = @a AND t > @t0 AND t < @t1 AND kind IN "
                       "('thought','exposure','conversation','inquiry','purchase','life_event','debrief','store_thought') "
                       "AND (kind != 'exposure' OR JSON_VALUE(payload, '$.outcome') IN ('notice','partial','full')) "
                       "ORDER BY t LIMIT 40", {"a": c["agent_id"], "t0": c["t0"], "t1": c["t1"]}, trusted=True)
        ids = {e["event_id"] for e in evs}
        if isinstance(llm, FakeGemini) or not evs:
            why = {"why": ("Between the waves: " + ", ".join(f"{e['kind']} ({e['event_id']})" for e in evs[:3]))
                   if evs else "no clear cause in their own events", "event_ids": [e["event_id"] for e in evs[:3]]}
        else:
            lines = "\n".join(f"[{e['event_id']}] {e['kind']}: {str(e['payload'])[:160]}" for e in evs)
            pr = (open(__import__("pathlib").Path(__file__).resolve().parents[1] / "shared" / "prompts" / "survey_why.md",
                       encoding="utf-8").read().replace("{question}", c["question_id"]).replace("{w1}", str(c["from_wave"]))
                  .replace("{w2}", str(c["to_wave"])).replace("{a1}", str(c["from"])).replace("{a2}", str(c["to"]))
                  .replace("{events}", wrap(lines, "events")))
            res = await llm.generate(MODEL_FLASH, pr, Why, purpose="survey_why", reasoning="low", max_tokens=160,
                                     priority_class="interactive")
            why = {"why": res.data.why[:300], "event_ids": [e for e in res.data.event_ids if e in ids]}
        store().set("survey_why", f"{sid}-{c['question_id']}-{c['agent_id']}-{c['to_wave']}", why)
        done += 1
    return {"explained": done}
