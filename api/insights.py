"""Insights API (I-01 … I-08, INTERFACES §5): Ask (SSE), dashboards, polls, interviews. Reads only; polls go to the engine."""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from agents.insights_assistant import Assistant
from insights.likely_buyers import age_band, segments
from insights.polls import estimate_usd, poll_id
from insights.tools import Ledger, Runner, Tools, default_runner
from media.screen import get_screener
from shared import time as simtime
from shared.llm import get_llm
from shared.store import DocStore, get_store

log = logging.getLogger(__name__)


class LoggedRoute(APIRoute):
    """Route that logs the traceback of any unexpected error before FastAPI turns it into a 500."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the default handler with `log.exception` for non-HTTP errors."""
        handler = super().get_route_handler()

        async def logged(request: Request) -> Response:
            try:
                return await handler(request)
            except HTTPException:
                raise
            except Exception:
                log.exception("insights route failed: %s %s", request.method, request.url.path)
                raise
        return logged


router = APIRouter(prefix="/api", route_class=LoggedRoute)
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
    """Active products (live + ready) — the only ones Insights shows or tells the assistant about."""
    from shared.products import active_products

    return active_products(store())


def _live() -> list[dict[str, Any]]:
    return [p for p in _products() if p.get("status") == "live" and p.get("launched_at_t") is not None]


def _active_ids() -> set[str]:
    return {p["product_id"] for p in _products()}


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


PING_S = 5.0


@router.post("/insights/ask")
async def ask(body: AskIn) -> StreamingResponse:
    """Server-sent events: {"step"} items, then exactly one {"answer": AskAnswer}; `: ping` comments keep it alive."""
    t = _now_t()
    tools = Tools(runner(), Ledger(), llm=get_llm(), store=store(), engine=None,
                  embed=_embedder())
    a = Assistant(tools, get_llm(), products=_products(), window=f"Day 1 → {simtime.fmt(t)}")
    a.known_ids = {str(x) for p in store().list("products", 200) for x in (p.get("product_id"), p.get("name")) if x}

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for chunk in sse_with_pings(a.ask(body.question), PING_S):
                yield chunk
            if body.session_id:
                store().set("insight_sessions", body.session_id, {"t": t, "question": body.question}, True)
        except Exception:
            log.exception("insights ask stream failed: %r", body.question[:200])
            raise

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def sse_with_pings(items: AsyncIterator[dict[str, Any]], every: float) -> AsyncIterator[bytes]:
    """SSE `data:` lines for each item, with a `: ping` comment whenever nothing arrived for `every` seconds."""
    import asyncio

    q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for it in items:
                await q.put(it)
        finally:
            await q.put(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                it = await asyncio.wait_for(q.get(), every)
            except TimeoutError:
                yield b": ping\n\n"
                continue
            if it is None:
                break
            yield f"data: {json.dumps(it, default=str, ensure_ascii=False)}\n\n".encode()
    finally:
        task.cancel()


def _embedder() -> Any:
    llm = get_llm()

    def embed(texts: list[str]) -> list[list[float]]:
        import asyncio

        return asyncio.run(asyncio.wait_for(llm.embed(texts), 5)) if not _in_loop() else _sync_embed(llm, texts)
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
        return ex.submit(lambda: asyncio.run(asyncio.wait_for(llm.embed(texts), 5))).result()


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
    fun = cumulative_funnel([p["product_id"] for p in live], n)
    ready = [p["name"] for p in _products() if p.get("status") == "ready"]
    ymax = max([60, *[v for s in series for v in s["v"] if v is not None]])
    return {"kpis": kpis[:4], "labels": [f"D{d}" for d in win], "series": series, "events": events,
            "ymax": int((ymax + 9) // 10 * 10), "funnel": {"cols": [p["name"] for p in live], "rows": fun},
            "note": f"{', '.join(ready)} is ready to launch — its line will start at launch." if ready else ""}


FUNNEL_ROWS = ["Reached (saw an ad or heard of it)", "Aware", "Interested (curious or further)",
               "Visited a store or bought", "Bought"]


def funnel_sets(pids: list[str]) -> dict[str, list[set[int]]]:
    """Per product, the agents who reached at least each funnel step (each set contains the next one)."""
    ph = ", ".join(f"'{p}'" for p in pids if p.replace("-", "").replace("_", "").isalnum()) or "''"
    expo = _q(f"SELECT DISTINCT product_id, agent_id FROM v_exposures WHERE product_id IN ({ph})")
    bel = _q(f"SELECT product_id, agent_id, stage FROM beliefs_latest WHERE product_id IN ({ph})")
    inq = _q(f"SELECT DISTINCT product_id, agent_id FROM v_inquiries WHERE product_id IN ({ph})")
    buy = _q(f"SELECT DISTINCT option AS product_id, agent_id FROM v_purchases WHERE option IN ({ph})")
    deeper = set(CURIOUS_PLUS)
    out: dict[str, list[set[int]]] = {}
    for pid in pids:
        def ids(rows: list[dict[str, Any]], pid: str = pid) -> set[int]:
            return {int(r["agent_id"]) for r in rows if r["product_id"] == pid and r["agent_id"] is not None}

        bought = ids(buy)
        visited = ids(inq) | bought
        interested = {int(r["agent_id"]) for r in bel if r["product_id"] == pid and r["stage"] in deeper} | visited
        aware = {int(r["agent_id"]) for r in bel if r["product_id"] == pid and r["stage"] != "unaware"} | interested
        out[pid] = [ids(expo) | aware, aware, interested, visited, bought]
    return out


def cumulative_funnel(pids: list[str], n_agents: int) -> list[list[Any]]:
    """Funnel rows "label, then per product: count with % of the step above" (never increases going down)."""
    sets = funnel_sets(pids)
    rows: list[list[Any]] = []
    for i, label in enumerate(FUNNEL_ROWS):
        row: list[Any] = [label]
        for pid in pids:
            k = len(sets[pid][i])
            base = len(sets[pid][i - 1]) if i else n_agents
            row.append({"n": k, "pct": _pct(k, base)})
        rows.append(row)
    return rows


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


SAID_VS_THOUGHT_SQL = (
    "SELECT e.session_id, e.agent_id, e.product_id, JSON_VALUE(e.payload, '$.thought') AS thought, m.text AS said, e.t "
    "FROM events e JOIN v_messages m ON m.session_id = e.session_id AND m.speaker = e.agent_id AND m.t >= e.t "
    "WHERE e.kind = 'store_thought' AND JSON_VALUE(e.payload, '$.thought') IS NOT NULL "
    "QUALIFY ROW_NUMBER() OVER (PARTITION BY e.event_id ORDER BY m.t, m.seq) = 1 "
    "ORDER BY e.t DESC LIMIT 40")


def said_vs_thought(limit: int = 4) -> list[list[str]]:
    """Store visits: a private thought next to the next thing the same person said out loud (active products)."""
    names = {p["product_id"]: p["name"] for p in _products()}
    out = []
    for r in _q(SAID_VS_THOUGHT_SQL):
        if r["product_id"] and r["product_id"] not in names:
            continue
        out.append([names.get(r["product_id"], "phone"), f"“{str(r['said'])[:80]}”", f"“{str(r['thought'])[:90]}”",
                    "private thought vs what they said"])
        if len(out) >= limit:
            break
    return out


@router.get("/insights/conversations")
def conversations() -> dict[str, Any]:
    """Topics, said vs privately thought, reviewers, community threads (I-06). Each section fails on its own:
    whatever worked is returned, with the failed section names in `errors`."""
    out: dict[str, Any] = {"topics": [], "topics_note": "", "gap": [], "reviewers": [], "threads": [], "errors": []}
    names = {p["product_id"]: p["name"] for p in _products()}

    def section(name: str, fn: Any) -> None:
        try:
            out.update(fn())
        except Exception:  # noqa: BLE001 — one broken query must not blank the tab
            log.exception("insights conversations: section %s failed", name)
            out["errors"].append(name)

    def topics() -> dict[str, Any]:
        rows = _q("SELECT first_topic AS topic, COUNT(*) AS n FROM v_inquiries WHERE first_topic IS NOT NULL "
                  "GROUP BY first_topic ORDER BY n DESC LIMIT 5")
        chats = _q("SELECT COUNT(*) AS n FROM v_messages WHERE conv_kind IN ('social','store')")
        tot = sum(int(x["n"]) for x in rows)
        cols = ["#22c55e", "#f5b041", "#60a5fa", "#8b5cf6", "#94a3b8"]
        return {"topics": [[str(x["topic"]).capitalize(), round(_pct(int(x["n"]), tot)), cols[i]]
                           for i, x in enumerate(rows)],
                "topics_note": f"Share of store questions by topic · {int(chats[0]['n']) if chats else 0} messages logged"}

    def reviewers() -> dict[str, Any]:
        rev = _q("SELECT r.reviewer, r.product_id, r.private_opinion, r.title, r.rating, a.name FROM v_reviews r "
                 "LEFT JOIN agents_latest a ON a.agent_id = r.reviewer WHERE r.title IS NOT NULL "
                 "ORDER BY r.t_published DESC LIMIT 12")
        return {"reviewers": [[x.get("name") or f"#{x['reviewer']}", names[x["product_id"]],
                               f"“{str(x['private_opinion'])[:120]}”", f"“{x['title']}” {float(x['rating'] or 0):.1f}/10"]
                              for x in rev if x["product_id"] in names][:3]}

    def threads() -> dict[str, Any]:
        th = _q("SELECT p.thread_id, p.forum, p.title, p.upvotes, a.name, "
                "(SELECT COUNT(*) FROM v_posts c WHERE c.kind = 'comment' AND c.thread_id = p.thread_id) AS comments "
                "FROM v_posts p LEFT JOIN agents_latest a ON a.agent_id = p.author WHERE p.kind = 'thread' "
                "ORDER BY p.upvotes DESC, p.t DESC LIMIT 3")
        return {"threads": [[x["forum"], x["title"], x.get("name") or "",
                             f"{int(x['comments'])} comments · {int(x['upvotes'])} ▲", x["thread_id"]] for x in th]}

    def kpis() -> dict[str, Any]:
        day = simtime.day_of(_now_t())
        rows = _q("SELECT day, COUNT(*) AS n, SUM(CASE WHEN ARRAY_LENGTH(product_mentions) > 0 THEN 1 ELSE 0 END) AS prod "
                  "FROM v_conversations GROUP BY day")
        today = next((r for r in rows if int(r["day"]) == day), {"n": 0, "prod": 0})
        total = sum(int(r["n"]) for r in rows)
        kept = _q("SELECT COUNT(DISTINCT session_id) AS n FROM events WHERE kind = 'share_plan' AND day = @d "
                  "AND CAST(JSON_VALUE(payload, '$.withheld_count') AS INT64) > 0", {"d": day})
        rendered = _q("SELECT COUNT(*) AS n FROM v_conversations WHERE rendered AND day = @d", {"d": day})
        ids = sorted(names)
        ph = ", ".join(f"'{x}'" for x in ids) or "''"
        wom = _q(f"SELECT COUNT(DISTINCT agent_id) AS n FROM (SELECT agent_id FROM v_first_heard WHERE channel = "
                 f"'friend_chat' AND product_id IN ({ph}) UNION ALL SELECT agent_id FROM events WHERE kind = 'wom' "
                 f"AND product_id IN ({ph}))")
        n_today, n_r = int(today["n"] or 0), int(rendered[0]["n"]) if rendered else 0
        return {"kpis": [["Conversations today", f"{n_today:,}", f"{total:,} since Day 1"],
                         ["About our products", f"{round(_pct(int(today['prod'] or 0), n_today))}%",
                          f"{int(today['prod'] or 0)} of {n_today} today"],
                         ["Kept something private", f"{round(_pct(int(kept[0]['n']) if kept else 0, n_r))}%",
                          f"of {n_r} written-out chats today"],
                         ["Word of mouth", f"{int(wom[0]['n']) if wom else 0} people",
                          "heard about a product from someone they know"]]}

    section("kpis", kpis)
    section("topics", topics)
    section("said_vs_thought", lambda: {"gap": said_vs_thought()})
    section("reviewers", reviewers)
    section("threads", threads)
    return out


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
            log.error("insights poll: engine command failed for %s: %r", pid, res)
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


CONV_KINDS = {"friends": ("social",), "strangers": ("stranger",), "store": ("store",), "focus": ("focus_group",)}
PAGE = 30


@router.get("/insights/conversations/list")
def conversation_list(product: str = "", kind: str = "", q: str = "", page: int = 1) -> dict[str, Any]:
    """Conversation cards, newest first, 30 per page: who, when, where, first line, product, topic, sentiment."""
    from world.map import get_map

    names = {p["product_id"]: p["name"] for p in _products()}
    where, params = ["e.kind IN ('conversation', 'interaction')"], {}
    kinds = CONV_KINDS.get(kind)
    if kinds:
        where.append("COALESCE(JSON_VALUE(e.payload, '$.kind'), JSON_VALUE(e.payload, '$.conv_kind')) IN (" +
                     ", ".join(f"'{k}'" for k in kinds) + ")")
    if product and product in names:
        where.append("(e.product_id = @p OR TO_JSON_STRING(JSON_QUERY(e.payload, '$.product_mentions')) LIKE @pl)")
        params.update({"p": product, "pl": f'%"{product}"%'})
    if q.strip():
        where.append("e.session_id IN (SELECT session_id FROM v_messages WHERE LOWER(text) LIKE @q)")
        params["q"] = f"%{q.strip().lower()[:80]}%"
    off = max(0, page - 1) * PAGE
    rows = _q("SELECT e.session_id, e.kind AS ev_kind, e.agent_id, e.other_id, e.t, e.payload FROM events e WHERE "
              + " AND ".join(where) + " QUALIFY ROW_NUMBER() OVER (PARTITION BY e.session_id ORDER BY e.t) = 1 "
              f"ORDER BY e.t DESC LIMIT {PAGE + 1} OFFSET {off}", params or None)
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    sids = [r["session_id"] for r in rows if r["session_id"]]
    first: dict[str, str] = {}
    mood: dict[str, float] = {}
    if sids:
        ph = ", ".join(f"'{x}'" for x in sids if str(x).replace("-", "").replace(":", "").replace("_", "").isalnum())
        if ph:
            first = {r["session_id"]: r["text"] for r in _q(f"SELECT session_id, text FROM v_messages WHERE session_id "
                                                            f"IN ({ph}) AND seq = 0")}
            for r in _q(f"SELECT session_id, payload FROM events WHERE kind = 'debrief' AND session_id IN ({ph})"):
                pl = r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"] or "{}")
                mood[r["session_id"]] = mood.get(r["session_id"], 0.0) + sum(float(d.get("attitude_delta", 0))
                                                                             for d in pl.get("belief_deltas") or [])
    who = {int(d["agent_id"]): d.get("row", {}) for d in store().list("agents", 5000)}
    places = get_map().place_by_id
    out = []
    for r in rows:
        pl = r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"] or "{}")
        ck = pl.get("kind") or pl.get("conv_kind") or "social"
        prods = [x for x in (pl.get("product_mentions") or []) if x in names]
        place = places.get(pl.get("place_id") or "")
        a, b = r["agent_id"], r["other_id"]
        out.append({"session_id": r["session_id"], "t": int(r["t"]), "label": simtime.fmt(int(r["t"])), "kind": ck,
                    "rendered": r["ev_kind"] == "conversation",
                    "a": {"agent_id": a, "name": (who.get(int(a)) or {}).get("name") if a is not None else None},
                    "b": {"agent_id": b, "name": (who.get(int(b)) or {}).get("name") if b is not None else None},
                    "place": ("Home" if place.kind == "home" else place.name) if place else pl.get("place") or "",
                    "first_line": first.get(r["session_id"]) or "",
                    "products": [{"id": x, "name": names[x]} for x in prods],
                    "topic": (pl.get("topics") or [pl.get("topic")] or [""])[0],
                    "sentiment": (None if r["session_id"] not in mood else
                                  "positive" if mood[r["session_id"]] > 0.02 else
                                  "negative" if mood[r["session_id"]] < -0.02 else "neutral")})
    return {"rows": out, "page": page, "more": more}


@router.get("/insights/conversations/{session_id}")
def conversation_detail(session_id: str) -> dict[str, Any]:
    """One conversation for the analyst: both people's private prep (what they meant to share and what they kept
    back), what they said, and what each one remembers. Private parts are flagged so the UI shows them as PRIVATE."""
    from world.map import get_map

    doc = store().get("conversations", session_id)
    if doc is None:
        raise HTTPException(404, "unknown conversation")
    who = {int(d["agent_id"]): d.get("row", {}) for d in store().list("agents", 5000)}
    parts = [int(x) for x in doc.get("participants", [])]
    conv = doc.get("conversation") or {}
    place = get_map().place_by_id.get(conv.get("place_id") or "")
    names = {p["product_id"]: p["name"] for p in _products()}
    people = []
    for aid in parts:
        mine = (doc.get("private") or {}).get(str(aid), {})
        plan = mine.get("share_plan") or {}
        shared = set(plan.get("points_to_share") or [])
        kept = [c["text"] for c in plan.get("candidates") or [] if c.get("text") not in shared
                and c.get("tag") in ("sensitive", "personal", "opinion")][:3]
        deb = mine.get("debrief") or {}
        row = who.get(aid, {})
        people.append({"agent_id": aid, "name": row.get("name"), "age": row.get("age"), "occupation": row.get("occupation"),
                       "plan": {"opening": plan.get("opening"), "share": list(shared)[:3], "kept": kept,
                                "withheld_count": plan.get("withheld_count", len(kept)), "private": True} if plan else None,
                       "memory": {"text": deb.get("summary") or deb.get("reaction"), "importance": deb.get("importance"),
                                  "private": True} if deb else None,
                       "store_thoughts": [{"text": x.get("thought"), "private": True} for x in mine.get("store_thoughts") or []][:4]})
    prods = [x for x in conv.get("product_mentions") or [] if x in names]
    return {"session_id": session_id, "kind": conv.get("kind"), "t": doc.get("t"), "label": simtime.fmt(int(doc.get("t") or 0)),
            "place": ("Home" if place.kind == "home" else place.name) if place else "",
            "place_xy": {"x": place.entrances[0][0], "y": place.entrances[0][1]} if place else None,
            "products": [{"id": x, "name": names[x]} for x in prods], "topics": conv.get("topics") or [],
            "people": people, "messages": [{"seq": m["seq"], "speaker": m["speaker"], "text": m["text"]}
                                           for m in doc.get("messages", [])],
            "spread": word_spread(prods[0], parts, int(doc.get("t") or 0)) if prods else None}


def word_spread(pid: str, people: list[int], t: int, hops: int = 4) -> dict[str, Any] | None:
    """The chain of conversations that carried this product to these people: walk back from the conversation to the
    earlier ones where one of them heard about it, a person at a time."""
    rows = _q("SELECT agent_id, other_id, t FROM events WHERE kind IN ('conversation', 'wom') AND t <= @t AND "
              "other_id IS NOT NULL AND (product_id = @p OR TO_JSON_STRING(JSON_QUERY(payload, '$.product_mentions')) LIKE @pl) "
              "ORDER BY t DESC LIMIT 400", {"t": t, "p": pid, "pl": f'%"{pid}"%'})
    best: tuple[list[int], int] = ([], t)
    for start in people[:2]:                               # walk back from whichever of the two heard it first
        rest = [x for x in people[:2] if x != start]
        chain, cur, t_cur, seen = [start, *rest], start, t, set(people)
        for _ in range(hops):
            prev = next((r for r in rows if int(r["t"]) < t_cur and cur in (r["agent_id"], r["other_id"])
                         and ({int(r["agent_id"]), int(r["other_id"])} - seen)), None)
            if prev is None:
                break
            other = ({int(prev["agent_id"]), int(prev["other_id"])} - {cur}).pop()
            chain.insert(0, other)
            seen.add(other)
            cur, t_cur = other, int(prev["t"])
        if len(chain) > len(best[0]):
            best = (chain, t_cur)
    chain, t_cur = best
    if len(chain) <= 2:
        return None
    who = {int(d["agent_id"]): d.get("row", {}).get("name") for d in store().list("agents", 5000)}
    return {"chain": [{"agent_id": a, "name": who.get(a)} for a in chain], "days": round((t - t_cur) / 1440, 1)}


# ---------------------------------------------------------------- interviews

class InterviewIn(BaseModel):
    """Interview turn."""

    agent_id: int
    question: str
    session_id: str | None = None


@router.post("/insights/interview")
async def interview(body: InterviewIn) -> dict[str, Any]:
    """In-character answer grounded only in that agent's memories (I-08); questions screened."""
    from agents.interviewer import fallback, safe_interview

    sc = get_screener().screen(body.question)
    if not sc.ok or "prompt_injection" in sc.flagged:
        raise HTTPException(422, "question refused by screening")
    sid = body.session_id or f"iv-{body.agent_id}"
    try:
        known = store().get("agents", str(body.agent_id)) is not None
        session = store().get("insight_sessions", sid) or {}
    except Exception:
        log.exception("insights interview: store read failed for agent %s", body.agent_id)
        return {**fallback("store"), "session_id": sid}
    if not known:
        raise HTTPException(404, "unknown person")
    raw = session.get("turns") if isinstance(session, dict) and session.get("agent_id") == body.agent_id else None
    hist = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []
    try:
        out = await safe_interview(body.agent_id, sc.text, store=store(), llm=get_llm(), history=hist)
    except Exception:
        log.exception("insights interview: unexpected failure for agent %s", body.agent_id)
        out = fallback("unexpected")
    if not out.get("fallback"):
        try:
            store().set("insight_sessions", sid, {"agent_id": body.agent_id, "turns": [
                *hist, {"role": "me", "text": body.question}, {"role": "ai", "text": out["answer"]}][-12:]}, True)
        except Exception:
            log.exception("insights interview: could not save session %s", sid)
    return {**out, "session_id": sid}


@router.get("/insights/interview/agents")
def interview_agents(q: str = "", agent: int | None = None) -> list[dict[str, Any]]:
    """Agents to interview (search by name or job); `agent` puts that person first."""
    from api.main import list_agents_rows

    rows = list_agents_rows(q=q, page=1, page_size=20)["rows"]
    if agent is not None and all(r["agent_id"] != agent for r in rows):
        rows = [*[r for r in list_agents_rows(page=1, page_size=5000)["rows"] if r["agent_id"] == agent], *rows][:20]
    return [{k: r.get(k) for k in ("agent_id", "name", "age", "occupation", "phone")} for r in rows]


__all__ = ["router", "age_band"]
