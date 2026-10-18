"""Insights API (I-01 … I-08, INTERFACES §5): Ask (SSE), dashboards, polls, interviews. Reads only; polls go to the engine."""

from __future__ import annotations

import json
import statistics
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.insights_assistant import Assistant
from insights.likely_buyers import age_band, segments
from insights.polls import estimate_usd, poll_id
from insights.tools import Ledger, Runner, Tools, default_runner
from media.screen import get_screener
from shared import time as simtime
from shared.llm import get_llm
from shared.store import DocStore, get_store

router = APIRouter(prefix="/api")
OOH = ("hoarding", "bus_shelter", "metro_panel")
SOURCE_GROUPS = [("Hoardings", OOH), ("Reels", ("reel",)), ("Reviewers", ("review",)), ("Community", ("community",)),
                 ("Word of mouth", ("friend_chat",)), ("Newspaper", ("newspaper",)), ("Store", ("store_display",))]
SOURCE_COLS = ["#f97316", "#2dd4bf", "#ec4899", "#a78bfa", "#60a5fa", "#94a3b8", "#f5b041"]
CURIOUS_PLUS = ("curious", "researching", "inquiring", "deciding", "purchased")
FACE = {0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW"}


def store() -> DocStore:
    """Firestore (or emulator / memory in tests)."""
    return get_store()


def runner() -> Runner:
    """Analytics runner (BigQuery as the analyst, or the engine's DuckDB locally)."""
    return default_runner()


def _engine_command(cmd: dict) -> dict | None:
    from api.products import _engine_command as send

    return send(cmd)


def _products() -> list[dict[str, Any]]:
    return sorted([p for p in store().list("products", 200)], key=lambda p: p.get("launched_at_t") or 10**12)


def _live() -> list[dict[str, Any]]:
    return [p for p in _products() if p.get("status") == "live" and p.get("launched_at_t") is not None]


def _q(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    rows, _ = runner().run(sql, params, trusted=True)
    return rows


def _now_t() -> int:
    from api.main import _now_t as now

    return now()


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


def _face(deg: float | None) -> str:
    if deg is None:
        return "—"
    return FACE.get(int(round(float(deg) / 45) * 45) % 360, f"{deg:.0f}°")


def _n_agents() -> int:
    rows = _q("SELECT COUNT(*) AS n FROM agents_latest WHERE special_role = 'none' OR special_role IS NULL")
    return int(rows[0]["n"]) if rows else 1000


# ---------------------------------------------------------------- Ask (SSE)

class AskIn(BaseModel):
    """Ask request."""

    question: str
    session_id: str | None = None


@router.post("/insights/ask")
async def ask(body: AskIn) -> StreamingResponse:
    """Server-sent events: {"step"} items, then {"answer": AskAnswer}."""
    t = _now_t()
    tools = Tools(runner(), Ledger(), llm=get_llm(), store=store(), engine=None,
                  embed=_embedder())
    prods = _products()
    a = Assistant(tools, get_llm(), products=prods, window=f"Day 1 → {simtime.fmt(t)}")

    async def gen() -> AsyncIterator[bytes]:
        async for item in a.ask(body.question):
            yield f"data: {json.dumps(item, default=str, ensure_ascii=False)}\n\n".encode()
        if body.session_id:
            store().set("insight_sessions", body.session_id, {"t": t, "question": body.question}, True)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _embedder() -> Any:
    llm = get_llm()

    def embed(texts: list[str]) -> list[list[float]]:
        import asyncio

        return asyncio.run(llm.embed(texts)) if not _in_loop() else _sync_embed(llm, texts)
    return embed


def _in_loop() -> bool:
    import asyncio

    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _sync_embed(llm: Any, texts: list[str]) -> list[list[float]]:
    """Run an async embed from inside a running loop (thread hop)."""
    import asyncio
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(llm.embed(texts))).result()


# ---------------------------------------------------------------- dashboards

@router.get("/insights/overview")
def overview() -> dict[str, Any]:
    """KPIs, awareness / curious+ lines with launch markers, funnel today (I-02)."""
    live = _live()
    n = _n_agents()
    rows = _q("SELECT day, product_id, aware, positive, considering, inquiries, purchases FROM v_funnel_daily")
    days = sorted({int(r["day"]) for r in rows}) or [simtime.day_of(_now_t())]
    win = days[-14:]
    by = {(r["product_id"], int(r["day"])): r for r in rows}
    series, events, kpis = [], [], []
    for p in live:
        pid, col = p["product_id"], p.get("color", "#22c55e")
        ld = simtime.day_of(int(p["launched_at_t"]))
        aw = [(_pct(by[(pid, d)]["aware"], n) if (pid, d) in by and d >= ld else None) for d in win]
        cp = [(_pct(by[(pid, d)]["considering"], n) if (pid, d) in by and d >= ld else None) for d in win]
        series += [{"n": f"{p['name']} aware", "v": aw, "c": col}, {"n": f"{p['name']} curious+", "v": cp, "c": col,
                                                                    "dash": "4 3"}]
        if ld in win:
            events.append({"i": win.index(ld), "t": f"{p['name']} launch", "c": col})
        last = by.get((pid, win[-1]), {})
        prev = by.get((pid, win[-2]), {}) if len(win) > 1 else {}
        tot_inq = sum(int(r["inquiries"]) for r in rows if r["product_id"] == pid)
        tot_buy = sum(int(r["purchases"]) for r in rows if r["product_id"] == pid)
        d_aw = _pct(last.get("aware", 0), n) - _pct(prev.get("aware", 0), n)
        kpis += [[f"{p['name']} · aware", f"{_pct(last.get('aware', 0), n):.0f}%",
                  f"{d_aw:+.0f} pts today" if prev else f"live {win[-1] - ld + 1} days"],
                 [f"{p['name']} · curious+", f"{_pct(last.get('considering', 0), n):.0f}%",
                  f"{tot_inq} store inquiries · {tot_buy} bought"]]
    stages = _q("SELECT product_id, stage, COUNT(*) AS n FROM beliefs_latest WHERE product_id IS NOT NULL "
                "GROUP BY product_id, stage")
    expo = _q("SELECT product_id, COUNT(DISTINCT agent_id) AS n FROM v_exposures WHERE product_id IS NOT NULL "
              "GROUP BY product_id")
    inq = _q("SELECT product_id, COUNT(DISTINCT agent_id) AS n FROM v_inquiries GROUP BY product_id")
    buy = _q("SELECT option AS product_id, COUNT(*) AS n FROM v_purchases GROUP BY option")
    st = {(r["product_id"], r["stage"]): int(r["n"]) for r in stages}

    def g(rs: list[dict], pid: str) -> int:
        return int(next((r["n"] for r in rs if r["product_id"] == pid), 0))

    fun = [["Exposed (any channel)", *[g(expo, p["product_id"]) for p in live]],
           ["Aware", *[sum(v for (q, s), v in st.items() if q == p["product_id"] and s != "unaware") for p in live]],
           ["Curious", *[st.get((p["product_id"], "curious"), 0) for p in live]],
           ["Researching", *[st.get((p["product_id"], "researching"), 0) for p in live]],
           ["Inquired in store", *[g(inq, p["product_id"]) for p in live]],
           ["Purchased", *[g(buy, p["product_id"]) for p in live]]]
    ready = [p["name"] for p in _products() if p.get("status") == "ready"]
    ymax = max([60, *[v for s in series for v in s["v"] if v is not None]])
    return {"kpis": kpis[:4], "labels": [f"D{d}" for d in win], "series": series, "events": events,
            "ymax": int((ymax + 9) // 10 * 10), "funnel": {"cols": [p["name"] for p in live], "rows": fun},
            "note": f"{', '.join(ready)} is ready to launch — its line will start at launch." if ready else ""}


@router.get("/insights/sources")
def sources() -> dict[str, Any]:
    """First-heard stacks per product and top paths to a store inquiry (I-03)."""
    rows = _q("SELECT product_id, channel, COUNT(*) AS n FROM v_first_heard GROUP BY product_id, channel")
    stacks = []
    for p in _live():
        pid = p["product_id"]
        tot = sum(int(r["n"]) for r in rows if r["product_id"] == pid)
        parts = [round(_pct(sum(int(r["n"]) for r in rows if r["product_id"] == pid and r["channel"] in chans), tot))
                 for _, chans in SOURCE_GROUPS]
        if tot and sum(parts) != 100:
            i = max(range(len(parts)), key=lambda k: parts[k])
            parts[i] += 100 - sum(parts)
        stacks.append({"label": f"{p['name']} · {tot} aware", "parts": parts, "product_id": pid, "aware": tot})
    paths = _q("SELECT path, COUNT(*) AS n FROM v_paths WHERE inquiry_t IS NOT NULL GROUP BY path ORDER BY n DESC "
               "LIMIT 5")
    mins = [int(r["m"]) for r in _q("SELECT minutes_to_inquiry AS m FROM v_paths WHERE inquiry_t IS NOT NULL")
            if r["m"] is not None]
    pretty = {"hoarding": "Hoarding", "bus_shelter": "Bus shelter", "metro_panel": "Metro panel", "reel": "Reel",
              "review": "Reviewer", "community": "Community thread", "friend_chat": "Friend chat",
              "newspaper": "Newspaper", "store_display": "Store display", "store": "store", "purchase": "purchase"}
    top = [[" → ".join(pretty.get(s, s) for s in str(r["path"]).split(" > ")), int(r["n"])] for r in paths]
    med = statistics.median(mins) / 1440 if mins else None
    return {"labels": [g[0] for g in SOURCE_GROUPS], "cols": SOURCE_COLS, "stacks": stacks, "paths": top,
            "note": f"median {med:.1f} sim days from first exposure to inquiry." if med is not None else
                    "No store inquiries yet."}


@router.get("/insights/hoardings")
def hoardings(days: int = 7) -> dict[str, Any]:
    """Site leaderboard, facing comparison, hour heat, notice themes (I-04); numbers equal v_site_daily."""
    from world.map import get_map

    t = _now_t()
    d0 = max(1, simtime.day_of(t) - days + 1)
    rows = _q("SELECT site_id, facing, product_id, SUM(ots) AS ots, SUM(glances) AS glances, SUM(notices) AS notices, "
              "SUM(thoughts) AS thoughts, AVG(sentiment) AS sentiment, COUNT(DISTINCT day) AS ndays FROM v_site_daily "
              "WHERE day >= @d0 GROUP BY site_id, facing, product_id", {"d0": d0})
    sites = {s.site_id: s for s in get_map().sites}
    names = {p["product_id"]: p for p in _products()}
    out = []
    for r in rows:
        ots = int(r["ots"] or 0)
        if ots < 5:
            continue
        s = sites.get(r["site_id"])
        pid = r["product_id"] if r["product_id"] in names else "—"
        out.append([r["site_id"], _face(r["facing"]), s.area_label if s else "", pid,
                    round(ots / max(1, int(r["ndays"] or 1))), round(_pct(int(r["glances"] or 0), ots)),
                    round(_pct(int(r["notices"] or 0), ots), 1), int(r["thoughts"] or 0) if pid != "—" else "—",
                    f"{float(r['sentiment']):+.2f}" if r["sentiment"] is not None and pid != "—" else "—"])
    out.sort(key=lambda x: -x[6])
    best = out[0] if out else None
    facing = None
    for sid in {r[0] for r in out}:
        fs = [r for r in out if r[0] == sid]
        if len(fs) >= 2:
            hi, lo = max(fs, key=lambda r: r[6]), min(fs, key=lambda r: r[6])
            if lo[6] > 0 and (facing is None or hi[6] / lo[6] > facing["ratio"]):
                facing = {"site_id": sid, "hi": hi[1], "lo": lo[1], "ratio": round(hi[6] / lo[6], 1)}
    hours = _q("SELECT hour, lit, COUNT(*) AS ots, SUM(CASE WHEN noticed THEN 1 ELSE 0 END) AS notices "
               "FROM v_exposures WHERE channel IN ('hoarding','bus_shelter','metro_panel') AND day >= @d0 "
               "GROUP BY hour, lit", {"d0": d0})
    buckets = [(6, 9), (9, 12), (12, 15), (15, 18), (18, 21), (21, 24)]
    heat = []
    for lit in (True, False):
        row = []
        for a, b in buckets:
            o = sum(int(h["ots"]) for h in hours if bool(h["lit"]) == lit and a <= int(h["hour"]) < b)
            nn = sum(int(h["notices"]) for h in hours if bool(h["lit"]) == lit and a <= int(h["hour"]) < b)
            row.append(round(_pct(nn, o), 1))
        heat.append(row)
    best_b = max(range(len(buckets)), key=lambda i: heat[0][i] + heat[1][i]) if hours else 4
    th = _q("SELECT text, product_id FROM v_thoughts WHERE site_id IS NOT NULL AND rendered AND day >= @d0 "
            "ORDER BY t DESC LIMIT 200", {"d0": d0})
    per_prod: dict[str, int] = {}
    for x in th:
        per_prod[x["product_id"]] = per_prod.get(x["product_id"], 0) + 1
    themes, seen = [], set()
    for x in th:
        if x["product_id"] in seen:
            continue
        seen.add(x["product_id"])
        themes.append([x["text"], per_prod[x["product_id"]] - 1])
    kpis = [["Best site", f"{best[0]} · faces {best[1]}" if best else "—",
             f"{best[6]}% notice rate · {best[7]} thoughts this week" if best else "no hoarding data yet"],
            ["Facing matters", f"{facing['ratio']}× notice" if facing else "—",
             f"same board: {facing['hi']} face vs {facing['lo']} face" if facing else "no two-sided board yet"],
            ["Best hour", f"{buckets[best_b][0]:02d}:00–{buckets[best_b][1]:02d}:00",
             "lit boards vs unlit, notice rate by hour"]]
    return {"kpis": kpis, "rows": out[:10], "all_rows": out, "facing": facing,
            "heat": {"rows": ["Lit boards", "Unlit boards"], "cols": [f"{a}–{b}" for a, b in buckets], "vals": heat},
            "themes": themes[:3], "sites": [{"site_id": s.site_id, "x": s.x, "y": s.y} for s in sites.values()]}


@router.get("/insights/hoardings/{site_id}/thoughts")
def site_thoughts(site_id: str) -> list[dict[str, Any]]:
    """Sample private thoughts at one site (rows are clickable, I-04)."""
    return _q("SELECT agent_id, t, text, product_id FROM v_thoughts WHERE site_id = @s AND rendered ORDER BY t DESC "
              "LIMIT 8", {"s": site_id})


@router.get("/insights/segments")
def segments_tab(product: str = "") -> dict[str, Any]:
    """Likely-buyer heat (age × income) and lifestyles for one product (I-05)."""
    live = _live()
    p = next((x for x in live if x["product_id"] == product), live[0] if live else None)
    if p is None:
        return {"products": [], "heat": None, "lifestyles": []}
    r = runner()
    rows = segments(r, p["product_id"], ["age_band", "income_band"], int(p["price_inr"]))
    ages = ["18–24", "25–34", "35–44", "45–59", "60+"]
    incs = ["<25k", "25-50k", "50k-1L", "1-2L", ">2L"]
    cell = {(x["age_band"], x["income_band"]): x for x in rows}
    vals = [[round(100 * cell[(a, i)]["likely_share"]) if (a, i) in cell else 0 for i in incs] for a in ages]
    ns = [[cell[(a, i)]["n"] if (a, i) in cell else 0 for i in incs] for a in ages]
    life = segments(r, p["product_id"], ["lifestyle"], int(p["price_inr"]))
    why = _q("SELECT text FROM v_thoughts WHERE product_id = @p AND rendered AND attitude_delta > 0 "
             "ORDER BY attitude_delta DESC LIMIT 4", {"p": p["product_id"]})
    lifestyles = [[str(x["lifestyle"]).replace("_", " ").capitalize(), f"n = {x['n']} · {x['aware']} aware",
                   (why[k]["text"][:90] if k < len(why) else x["top_stage"]), f"{round(100 * x['likely_share'])}%"]
                  for k, x in enumerate(sorted(life, key=lambda x: -x["likely_share"])[:4])]
    return {"products": [{"id": x["product_id"], "name": x["name"]} for x in live], "product": p["product_id"],
            "heat": {"rows": ages, "cols": ["< ₹25k", "₹25–50k", "₹50k–1L", "₹1–2L", "> ₹2L"], "vals": vals, "n": ns},
            "lifestyles": lifestyles}


@router.get("/insights/conversations")
def conversations() -> dict[str, Any]:
    """Topics, said vs privately thought, reviewers private vs published, community threads (I-06)."""
    topics = _q("SELECT first_topic AS topic, COUNT(*) AS n FROM v_inquiries WHERE first_topic IS NOT NULL "
                "GROUP BY first_topic ORDER BY n DESC LIMIT 5")
    chats = _q("SELECT COUNT(*) AS n FROM v_messages WHERE conv_kind IN ('social','store')")
    tot = sum(int(x["n"]) for x in topics)
    cols = ["#22c55e", "#f5b041", "#60a5fa", "#8b5cf6", "#94a3b8"]
    tl = [[str(x["topic"]).capitalize(), round(_pct(int(x["n"]), tot)), cols[i]] for i, x in enumerate(topics)]
    gap = []
    r = runner()
    try:
        priv = r.texts("kind = 'store_thought'", {})[:400]
    except Exception:  # noqa: BLE001
        priv = []
    said = _q("SELECT session_id, speaker, text FROM v_messages WHERE conv_kind = 'store' ORDER BY t, seq LIMIT 2000")
    names = {p["product_id"]: p["name"] for p in _products()}
    for pt in priv:
        s = next((m for m in said if m["session_id"] == pt["session_id"] and int(m["speaker"]) == int(pt["agent_id"])),
                 None)
        if s is None:
            continue
        gap.append([names.get(pt["product_id"], pt["product_id"] or "phone"), f"“{s['text'][:80]}”",
                    f"“{pt['text'][:90]}”", "private thought vs what they said"])
        if len(gap) >= 4:
            break
    rev = _q("SELECT r.reviewer, r.product_id, r.private_opinion, r.title, r.rating, a.name FROM v_reviews r "
             "LEFT JOIN agents_latest a ON a.agent_id = r.reviewer WHERE r.title IS NOT NULL ORDER BY r.t_published DESC "
             "LIMIT 3")
    reviewers = [[x.get("name") or f"#{x['reviewer']}", names.get(x["product_id"], x["product_id"]),
                  f"“{str(x['private_opinion'])[:120]}”", f"“{x['title']}” {float(x['rating'] or 0):.1f}/10"] for x in rev]
    th = _q("SELECT p.thread_id, p.forum, p.title, p.upvotes, a.name, "
            "(SELECT COUNT(*) FROM v_posts c WHERE c.kind = 'comment' AND c.thread_id = p.thread_id) AS comments "
            "FROM v_posts p LEFT JOIN agents_latest a ON a.agent_id = p.author WHERE p.kind = 'thread' "
            "ORDER BY p.upvotes DESC, p.t DESC LIMIT 3")
    threads = [[x["forum"], x["title"], x.get("name") or "", f"{int(x['comments'])} comments · {int(x['upvotes'])} ▲",
                x["thread_id"]] for x in th]
    return {"topics": tl, "topics_note": f"Share of store questions by topic · {int(chats[0]['n']) if chats else 0} "
                                         "messages logged", "gap": gap, "reviewers": reviewers, "threads": threads}


# ---------------------------------------------------------------- polls

class PollIn(BaseModel):
    """Poll request (`confirm` false → estimate only)."""

    question: str
    options: list[str]
    cohort: str | None = None
    confirm: bool = False


@router.post("/insights/poll")
def create_poll(body: PollIn) -> dict[str, Any]:
    """Estimate first; with confirm=true the engine runs it against the interactive budget (I-07)."""
    sc = get_screener().screen(body.question + " " + " ".join(body.options))
    if not sc.ok:
        raise HTTPException(422, "question refused by screening")
    opts = [o.strip() for o in body.options if o.strip()][:8]
    if len(opts) < 2:
        raise HTTPException(422, "at least 2 options")
    ids = None
    if body.cohort:
        tools = Tools(runner())
        ids = tools.cohort(body.cohort)["agent_ids"]
    n = len(ids) if ids is not None else _n_agents()
    pid = poll_id(body.question, opts, ids)
    out = {"poll_id": pid, "estimate_usd": estimate_usd(n), "n": n, "seconds_est": max(10, n // 16)}
    if body.confirm:
        res = _engine_command({"type": "poll", "poll_id": pid, "question": body.question, "options": opts,
                               "agent_ids": ids})
        if res is None or not res.get("ok"):
            raise HTTPException(503, "world-engine unreachable")
        out["started"] = True
    return out


@router.get("/insights/poll/{pid}")
def get_poll(pid: str) -> dict[str, Any]:
    """Poll status / result (+ heat by phone age)."""
    doc = store().get("polls", pid)
    if doc is None:
        raise HTTPException(404, "unknown poll")
    if doc.get("status") == "done" and "by_phone_age" not in doc:
        ans = _q("SELECT e.agent_id, JSON_VALUE(e.payload, '$.option') AS option, a.phone_age_years FROM events e "
                 "JOIN agents_latest a ON a.agent_id = e.agent_id WHERE e.kind = 'poll_answer' "
                 "AND JSON_VALUE(e.payload, '$.poll_id') = @p", {"p": pid})
        bands = [("< 2 yrs", 0, 2), ("2–5 yrs", 2, 5), ("> 5 yrs", 5, 99)]
        heat = []
        for _, lo, hi in bands:
            grp = [x for x in ans if lo <= float(x["phone_age_years"] or 0) < hi]
            heat.append([round(_pct(sum(1 for x in grp if x["option"] == o), len(grp))) for o in doc["options"]])
        doc["by_phone_age"] = {"rows": [b[0] for b in bands], "cols": doc["options"], "vals": heat}
    return doc


@router.get("/insights/polls")
def list_polls() -> list[dict[str, Any]]:
    """Recent polls, newest first."""
    return sorted(store().list("polls", 50), key=lambda d: -int(d.get("t", 0)))


# ---------------------------------------------------------------- interviews

class InterviewIn(BaseModel):
    """Interview turn."""

    agent_id: int
    question: str
    session_id: str | None = None


@router.post("/insights/interview")
async def interview(body: InterviewIn) -> dict[str, Any]:
    """In-character answer grounded only in that agent's memories (I-08); questions screened."""
    from agents.interviewer import interview as run

    sc = get_screener().screen(body.question)
    if not sc.ok or "prompt_injection" in sc.flagged:
        raise HTTPException(422, "question refused by screening")
    sid = body.session_id or f"iv-{body.agent_id}"
    hist = (store().get("insight_sessions", sid) or {}).get("turns", [])
    out = await run(body.agent_id, sc.text, store=store(), llm=get_llm(), history=hist)
    store().set("insight_sessions", sid, {"agent_id": body.agent_id, "turns": [
        *hist, {"role": "me", "text": body.question}, {"role": "ai", "text": out["answer"]}][-12:]}, True)
    return {**out, "session_id": sid}


@router.get("/insights/interview/agents")
def interview_agents(q: str = "") -> list[dict[str, Any]]:
    """Agents to interview (search by name or job)."""
    from api.main import list_agents

    return list_agents(q=q, page_size=20)["rows"]


__all__ = ["router", "age_band"]
