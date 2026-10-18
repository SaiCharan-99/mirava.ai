"""mirava.ai REST API (Cloud Run `mirava-api`): world state/stats, agents, watchlist. Reads only; never writes agent state."""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from population.genesis import from_fs_profile
from population.possessions import phone_age_years
from shared import time as simtime
from shared.settings import get_settings
from shared.store import DocStore, get_store

app = FastAPI(title="mirava.ai api", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_store(request: Any, call_next: Any) -> Any:
    """Live data: stop Firebase Hosting's CDN caching API responses (it kept 404s for 10 min)."""
    resp = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


api = APIRouter(prefix="/api")
_cache: dict[str, tuple[float, Any]] = {}
WATCH_DOC = "default"


def store() -> DocStore:
    """Shared document store."""
    return get_store()


def _engine_get(path: str) -> dict | None:
    """GET from world-engine (1.5 s timeout); None when unreachable."""
    s = get_settings()
    headers = {}
    if s.env == "cloud":
        try:
            from google.auth.transport import requests as greq
            from google.oauth2 import id_token

            headers["Authorization"] = f"Bearer {id_token.fetch_id_token(greq.Request(), s.engine_url)}"
        except Exception:  # noqa: BLE001 — public reads work without a token
            pass
    try:
        r = httpx.get(f"{s.engine_url}{path}", timeout=1.5, headers=headers)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def _agents() -> list[dict]:
    """All agent docs (cached 30 s)."""
    hit = _cache.get("agents")
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    docs = sorted(store().list("agents", limit=5000), key=lambda d: d["agent_id"])
    _cache["agents"] = (time.time(), docs)
    return docs


def _now_t() -> int:
    st = _engine_get("/state")
    if st:
        return int(st["t"])
    return int((store().get("world", "state") or {}).get("t", 0))


def _watched() -> set[int]:
    return set((store().get("watchlist", WATCH_DOC) or {}).get("agent_ids", []))


@app.get("/healthz")
@api.get("/healthz")
def healthz() -> dict:
    """Liveness probe (also reachable through the Hosting rewrite at /api/healthz)."""
    s = get_settings()
    return {"ok": True, "service": "api", "env": s.env, "llm_backend": s.llm_backend}


@api.get("/world/state")
def world_state() -> dict:
    """Clock, scale, status and budget (from the engine, else the last `world/state` doc)."""
    st = _engine_get("/state")
    if st:
        return st
    doc = store().get("world", "state") or {}
    t = int(doc.get("t", 0))
    spd = float(doc.get("seconds_per_sim_day", get_settings().world_seconds_per_sim_day))
    return {"t": t, "day": simtime.day_of(t), "label": simtime.fmt(t),
            "scale": {"sim_min_per_real_s": round(1440 / spd * float(doc.get("speed", 1.0)), 4)}, "slowed": False,
            "status": "unreachable" if doc else "not_started",
            "budget": {"used_usd": 0.0, "cap_usd": get_settings().daily_cap_usd}}


@api.get("/world/stats")
def world_stats() -> dict:
    """Stats frame (as in /live)."""
    st = _engine_get("/stats")
    if st:
        return st
    g = store().get("world", "genesis") or {}
    return {"type": "stats", "t": _now_t(), "counts": {"agents": g.get("n", 0), "households": g.get("households", 0),
            "relationships": g.get("relationships", 0), "conversations_today": 0, "conversations_total": 0,
            "thoughts_today": 0, "products_live": 0}, "budget": {"used_usd": 0.0, "cap_usd": 15.0}, "awareness": {}}


def _row(d: dict, t: int, watched: set[int]) -> dict:
    r = d.get("row", {})
    ph = r.get("phone", {})
    return {"agent_id": d["agent_id"], "name": r.get("name"), "age": r.get("age"), "occupation": r.get("occupation"),
            "income_band": r.get("income_band"), "special_role": r.get("special_role", "none"),
            "phone": {"brand": ph.get("brand"), "tier": ph.get("tier"), "condition": ph.get("condition"),
                      "age_years": round(phone_age_years(ph, t), 1) if "bought_t" in ph else None},
            "_age2": round(phone_age_years(ph, t), 2) if "bought_t" in ph else 0.0,
            "stages": r.get("stages") or {}, "need": r.get("need"), "watched": d["agent_id"] in watched,
            "activity": r.get("activity") or (d.get("state") or {}).get("activity")}


@api.get("/agents")
def list_agents(q: str = "", age: str = "", job: str = "", income: str = "", phone_age_gt: float | None = None,
                product: str = "", stage: str = "", watched: int = 0, sort: str = "agent_id",
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000)) -> dict:
    """People directory with filters (U-05)."""
    t = _now_t()
    w = _watched()
    rows = [_row(d, t, w) for d in _agents()]
    phone_old = sum(1 for r in rows if r["_age2"] > 5)
    ql = q.strip().lower()
    if ql:
        rows = [r for r in rows if ql in (r["name"] or "").lower() or ql in (r["occupation"] or "").lower()]
    if age:
        lo, _, hi = age.partition("-")
        rows = [r for r in rows if int(lo or 0) <= r["age"] <= int(hi or 200)]
    if job:
        rows = [r for r in rows if job.lower() in (r["occupation"] or "").lower()]
    if income:
        rows = [r for r in rows if r["income_band"] == income]
    if phone_age_gt is not None:
        rows = [r for r in rows if r["_age2"] > phone_age_gt]
    if watched:
        rows = [r for r in rows if r["watched"]]
    if stage:
        rows = [r for r in rows if (r["stages"].get(product) == stage if product else stage in r["stages"].values())]
    elif product:
        rows = [r for r in rows if product in r["stages"]]
    key = sort.lstrip("-")
    getter = {"phone_age": lambda r: r["_age2"]}.get(key, lambda r: r.get(key) or 0)
    rows.sort(key=getter, reverse=sort.startswith("-"))
    total = len(rows)
    rows = [{k: v for k, v in r.items() if k != "_age2"} for r in rows[(page - 1) * page_size: page * page_size]]
    return {"rows": rows, "total": total, "phone_old_count": phone_old, "watched_count": len(w)}


@api.get("/agents/{agent_id}")
def get_agent(agent_id: int) -> dict:
    """Profile, live state, relationships (with the other person) and beliefs."""
    doc = store().get("agents", str(agent_id))
    if doc is None:
        raise HTTPException(404, "unknown agent")
    live = _engine_get(f"/agents/{agent_id}/state")
    state = live or doc.get("state", {})
    t = int(state.get("t", 0))
    from world.map import get_map

    pl = get_map().place_by_id.get(state.get("place_id") or "")
    state = {**state, "place_name": ("Home" if pl.kind == "home" else pl.name) if pl else None}
    profile = from_fs_profile(doc["profile"])
    meta = doc.get("meta", {})
    ph = dict((live or {}).get("phone") or doc.get("phone") or profile["possessions"]["phone"])
    ph["age_years"] = round(phone_age_years(ph, t), 1)
    profile["possessions"] = {**profile["possessions"], "phone": ph}
    profile["household_size"] = meta.get("household_size")
    wp = profile.get("workplace_place_id")
    if wp:
        place = get_map().place_by_id.get(wp)
        profile["workplace_name"] = place.name if place else None
    elif meta.get("offmap_area"):
        profile["workplace_name"] = meta["offmap_area"]
    by_id = {d["agent_id"]: d.get("row", {}) for d in _agents()}
    rels = [*store().where("relationships", "a", agent_id), *store().where("relationships", "b", agent_id)]
    out_rels = []
    for r in sorted(rels, key=lambda r: -r["closeness"]):
        other = r["b"] if r["a"] == agent_id else r["a"]
        o = by_id.get(other, {})
        out_rels.append({**r, "other": {"agent_id": other, "name": o.get("name"), "age": o.get("age"),
                                        "occupation": o.get("occupation")}})
    beliefs = sorted(store().list(f"agents/{agent_id}/beliefs"), key=lambda b: -int(b.get("updated_t", 0)))
    return {"profile": profile, "state": state, "relationships": out_rels, "beliefs": beliefs,
            "watched": agent_id in _watched()}


def _names() -> dict[int, str]:
    return {d["agent_id"]: (d.get("row") or {}).get("name") or f"#{d['agent_id']}" for d in _agents()}


@api.get("/agents/{agent_id}/thoughts")
def agent_thoughts(agent_id: int, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    """This agent's private thoughts (debrief reactions, reflections; ad thoughts from phase 4), newest first."""
    rows = sorted(store().list(f"agents/{agent_id}/thoughts", limit=2000), key=lambda r: -int(r.get("t", 0)))
    return rows[:limit]


@api.get("/agents/{agent_id}/conversations")
def agent_conversations(agent_id: int, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    """Conversations this agent took part in, newest first (`with` resolved to a name)."""
    names = _names()
    rows = sorted(store().list(f"agents/{agent_id}/conversations", limit=2000), key=lambda r: -int(r.get("t", 0)))
    return [{**r, "with_name": names.get(r.get("with") or -1)} for r in rows[:limit]]


@api.get("/conversations/{session_id}")
def conversation(session_id: str, as_agent: int = Query(...)) -> dict:
    """Transcript + ONLY `as_agent`'s private prep and debrief (the other side's private parts never leave)."""
    doc = store().get("conversations", session_id)
    if doc is None or as_agent not in doc.get("participants", []):
        raise HTTPException(404, "unknown conversation for this agent")
    mine = (doc.get("private") or {}).get(str(as_agent), {})
    names = _names()
    return {"conversation": doc["conversation"], "messages": doc.get("messages", []),
            "share_plan": mine.get("share_plan"), "debrief": mine.get("debrief"),
            "store_thoughts": mine.get("store_thoughts") or [], "inquiry": doc.get("inquiry"),
            "names": {str(p): names.get(p) for p in doc.get("participants", [])}}


@api.get("/agents/{agent_id}/memories")
def agent_memories(agent_id: int, q: str = "", limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    """This agent's episodic memories (no embeddings), newest first; `q` filters by text."""
    rows = [{k: v for k, v in r.items() if k != "embedding"} for r in store().list(f"agents/{agent_id}/memories",
                                                                                   limit=2000)]
    rows = [r for r in rows if r.get("agent_id") == agent_id and (not q or q.lower() in r.get("text", "").lower())]
    return sorted(rows, key=lambda r: (-int(r.get("t", 0)), r.get("mid", "")))[:limit]


@api.get("/world/highlights")
def highlights(day: int = Query(..., ge=1)) -> dict:
    """Highlights JSON for a completed sim day (W-08)."""
    import json

    from population.genesis import genesis_bucket
    from shared.files import get_files

    files, bucket = get_files(), genesis_bucket(get_settings())
    key = f"highlights/day-{day}.json"
    if not files.exists(bucket, key):
        raise HTTPException(404, "no highlights for that day yet")
    return json.loads(files.read(bucket, key))


@api.get("/world/highlights/days")
def highlight_days() -> dict:
    """Completed days with highlights (latest 14)."""
    from population.genesis import genesis_bucket
    from shared.files import get_files

    files, bucket = get_files(), genesis_bucket(get_settings())
    today = simtime.day_of(_now_t())
    return {"days": [d for d in range(max(1, today - 14), today) if files.exists(bucket, f"highlights/day-{d}.json")]}


class Watchlist(BaseModel):
    """Watched agent ids."""

    agent_ids: list[int]


@api.get("/watchlist")
def get_watchlist() -> dict:
    """Current watchlist."""
    return {"agent_ids": sorted(_watched())}


@api.put("/watchlist")
def put_watchlist(body: Watchlist) -> dict:
    """Replace the watchlist (UI state; not agent state)."""
    ids = sorted({i for i in body.agent_ids if 0 <= i < 100000})
    store().set("watchlist", WATCH_DOC, {"agent_ids": ids})
    return {"agent_ids": ids}


app.include_router(api)

from api.products import router as products_router  # noqa: E402

app.include_router(products_router)

from api.insights import router as insights_router  # noqa: E402

app.include_router(insights_router)

from api.surveys import router as surveys_router  # noqa: E402

app.include_router(surveys_router)
