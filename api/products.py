"""Launch Studio API (L-01 … L-08): products CRUD, content, understanding, audience, auto plan, ready, launch."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agents.understanding import understand
from media.audience import audience_ids, compile_rules
from media.graph import build_graph, embed_nodes
from media.planner import plan_product, write_reasons
from media.screen import get_screener
from media.traffic import build_traffic, load_highlight_days, points_from_commutes, points_from_highlights
from population.genesis import from_fs_profile
from shared import time as simtime
from shared.llm import get_llm
from shared.schemas.product import Creative, Product
from shared.settings import get_settings
from shared.store import DocStore, get_store

router = APIRouter(prefix="/api")
COLL = "products"
COLORS = ["#f97316", "#22c55e", "#8b5cf6", "#ec4899", "#eab308", "#06b6d4"]  # --p1 … --p6 (tokens.css)
_cache: dict[str, tuple[float, Any]] = {}


def store() -> DocStore:
    """Shared document store."""
    return get_store()


def slug(name: str) -> str:
    """Product id from its name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "product"


def _load(pid: str) -> Product:
    doc = store().get(COLL, pid)
    if doc is None:
        raise HTTPException(404, "unknown product")
    return Product.model_validate(doc)


def _save(p: Product) -> Product:
    store().set(COLL, p.product_id, p.model_dump(mode="json"))
    return p


def _profiles() -> list[dict]:
    """All agent profiles (+ meta) from Firestore, cached 60 s."""
    hit = _cache.get("profiles")
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    out = []
    for d in sorted(store().list("agents", limit=5000), key=lambda d: d["agent_id"]):
        if "profile" in d:
            out.append({**from_fs_profile(d["profile"]), "_meta": d.get("meta", {})})
    _cache["profiles"] = (time.time(), out)
    return out


def _now_t() -> int:
    from api.main import _now_t as now

    return now()


class ProductIn(BaseModel):
    """Create/patch body (all optional on patch)."""

    name: str | None = None
    brand: str | None = None
    category: str | None = None
    price_inr: int | None = Field(None, ge=0)
    launch_offer: str | None = None
    features: list[str] | None = None
    claims: list[str] | None = None
    target_personas: list[str] | None = None
    strategy: dict | None = None


class CreativeIn(BaseModel):
    """Text content of one creative (posters' copy, reel transcript + scenes, post, print, display, kit)."""

    kind: str
    title: str
    text: str | None = None
    transcript: str | None = None
    scenes: list[str] = Field(default_factory=list)
    image_uri: str | None = None


class UploadIn(BaseModel):
    """Signed-URL upload request."""

    kind: str
    filename: str


@router.get("/products")
def list_products() -> list[dict]:
    """All products, in creation (colour) order."""
    docs = store().list(COLL, limit=200)
    return sorted(docs, key=lambda d: (COLORS.index(d["color"]) if d.get("color") in COLORS else 99, d["product_id"]))


@router.post("/products")
def create_product(body: ProductIn) -> dict:
    """New draft product; colour = next free of --p1…--p6."""
    if not body.name:
        raise HTTPException(422, "name required")
    pid = slug(body.name)
    existing = store().list(COLL, limit=200)
    if any(d["product_id"] == pid for d in existing):
        raise HTTPException(409, "a product with this name exists")
    used = {d.get("color") for d in existing}
    color = next((c for c in COLORS if c not in used), COLORS[len(existing) % len(COLORS)])
    p = Product(product_id=pid, name=body.name, brand=body.brand or "", category=body.category or "Smartphone",
                price_inr=body.price_inr or 0, launch_offer=body.launch_offer, features=body.features or [],
                claims=body.claims or [], target_personas=body.target_personas or [], audience=[],
                strategy=body.strategy or {"goal": "awareness", "key_message": "", "channels": [], "flight_days": 14,
                                           "intensity": "medium"},
                creatives=[], plan=None, status="draft", color=color)
    return _save(p).model_dump(mode="json")


@router.get("/products/{pid}")
def get_product(pid: str) -> dict:
    """One product."""
    return _load(pid).model_dump(mode="json")


@router.patch("/products/{pid}")
def patch_product(pid: str, body: ProductIn) -> dict:
    """Edit details while draft/ready (live products are frozen)."""
    p = _load(pid)
    if p.status in ("live", "ended"):
        raise HTTPException(409, "live products cannot be edited")
    upd = body.model_dump(exclude_none=True)
    upd.pop("name", None)
    p = p.model_copy(update=upd)
    if "target_personas" in upd:
        p.audience = []
    return _save(p).model_dump(mode="json")


@router.delete("/products/{pid}")
def delete_product(pid: str) -> dict:
    """Delete a draft."""
    p = _load(pid)
    if p.status != "draft":
        raise HTTPException(409, "only drafts can be deleted")
    store().delete(COLL, pid)
    return {"ok": True}


@router.post("/products/{pid}/creatives")
def add_creative(pid: str, body: CreativeIn) -> dict:
    """Add text content; screened (Model Armor) and neutralised before it is ever used in a prompt."""
    p = _load(pid)
    scr = get_screener()
    texts = [body.title, body.text or "", body.transcript or "", *body.scenes]
    results = [scr.screen(t) for t in texts]
    if not all(r.ok for r in results):
        raise HTTPException(422, "content refused: political or election campaigns are not supported")
    cid = f"{pid}-{body.kind}-{len(p.creatives) + 1}"
    c = Creative(creative_id=cid, product_id=pid, kind=body.kind,  # type: ignore[arg-type]
                 title=results[0].text, text=results[1].text or None, transcript=results[2].text or None,
                 scenes=[r.text for r in results[3:]], image_uri=body.image_uri, screened=True)
    p.creatives.append(c)
    _save(p)
    flags = sorted({f for r in results for f in r.flagged})
    return {"creative": c.model_dump(mode="json"), "flagged": flags}


@router.post("/products/{pid}/uploads")
def create_upload(pid: str, body: UploadIn) -> dict:
    """Signed PUT URL for an image (GCS in the cloud, the local API otherwise)."""
    _load(pid)
    s = get_settings()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", body.filename)[-80:]
    cid = f"{pid}-{body.kind}-img-{int(time.time() * 1000) % 10**8}"
    key = f"products/{pid}/{cid}/{safe}"
    if s.env == "cloud" and s.gcs_bucket_uploads:
        import datetime

        import google.auth
        from google.auth.transport.requests import Request as GReq
        from google.cloud import storage  # type: ignore[attr-defined]

        creds, _ = google.auth.default()
        creds.refresh(GReq())
        blob = storage.Client().bucket(s.gcs_bucket_uploads).blob(key)
        url = blob.generate_signed_url(version="v4", expiration=datetime.timedelta(minutes=15), method="PUT",
                                       service_account_email=getattr(creds, "service_account_email", None),
                                       access_token=creds.token)
        return {"upload_url": url, "creative_id": cid, "uri": f"gs://{s.gcs_bucket_uploads}/{key}"}
    return {"upload_url": f"/api/uploads/{key}", "creative_id": cid, "uri": f"local://uploads/{key}"}


@router.put("/uploads/{key:path}")
async def local_upload(key: str, request: Request) -> dict:
    """Local twin of a signed URL (dev only)."""
    if get_settings().env == "cloud":
        raise HTTPException(404, "use the signed URL")
    from shared.files import get_files

    data = await request.body()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    get_files().write("uploads", key, data)
    return {"ok": True}


class AudienceIn(BaseModel):
    """Personas to compile."""

    personas: list[str] | None = None


@router.post("/products/{pid}/audience")
async def compile_audience(pid: str, body: AudienceIn) -> dict:
    """Personas → audience rules with live counts (personas aim, never create agents)."""
    p = _load(pid)
    if body.personas is not None:
        p.target_personas = body.personas
    scr = get_screener()
    personas = [scr.screen(x).text for x in p.target_personas]
    p.audience = await compile_rules(personas, _profiles(), get_llm(), _now_t())
    _save(p)
    return {"audience": [a.model_dump() for a in p.audience],
            "total": len(audience_ids(p.audience, _profiles(), _now_t()))}


@router.post("/products/{pid}/understand")
async def run_understanding(pid: str) -> dict:
    """Understanding → claim risk → StimulusRecords → knowledge graph (+ node embeddings)."""
    p = _load(pid)
    llm = get_llm()
    out = await understand(p, llm)
    by_id = {s.creative_id: s for s in out["stimuli"]}
    for c in p.creatives:
        c.stimulus = by_id.get(c.creative_id)
    p.understanding = out["understanding"]
    p.specs = out["specs"]
    from world.map import get_map

    names = [s.name for s in get_map().stores if p.plan is None or s.store_id in p.plan.stores]
    p.graph = build_graph(p, p.understanding, names)
    _save(p)
    try:
        vecs = await embed_nodes(p.graph, llm)
        store().set("product_graph_vectors", pid, {"vectors": vecs})
    except Exception:  # noqa: BLE001 — embeddings only power later mention links
        pass
    return {"understanding": p.understanding, "creatives": [s.model_dump() for s in out["stimuli"]],
            "graph": p.graph}


def _held_sites(exclude: str) -> set[str]:
    held: set[str] = set()
    for d in store().list(COLL, limit=200):
        if d["product_id"] != exclude and d.get("status") == "live" and d.get("plan"):
            held |= {s["site_id"] for s in d["plan"]["sites"]}
    return held


def _traffic(day: int, profiles: list[dict]) -> Any:
    from population.genesis import genesis_bucket
    from shared.files import get_files
    from world.map import get_map

    key = f"traffic-{day}"
    hit = _cache.get(key)
    if hit:
        return hit[1]
    m = get_map()
    days = load_highlight_days(get_files(), genesis_bucket(get_settings()), day, 7)
    if days:
        tr = build_traffic(m.sites, points_from_highlights(days, [p["agent_id"] for p in profiles]), "highlights")
    else:
        tr = build_traffic(m.sites, points_from_commutes(m, profiles), "commutes")
    _cache[key] = (time.time(), tr)
    return tr


@router.post("/products/{pid}/plan")
async def make_plan(pid: str) -> dict:
    """Auto plan for (product, world day): sites + facing with reasons, reel, newspaper, reviewers, community, stores."""
    from world.map import get_map

    p = _load(pid)
    if p.status in ("live", "ended"):
        raise HTTPException(409, "live products keep their plan")
    profiles = _profiles()
    t = _now_t()
    day = simtime.day_of(t)
    if not p.audience and p.target_personas:
        p.audience = await compile_rules(p.target_personas, profiles, get_llm(), t)
    aud = audience_ids(p.audience, profiles, t)
    reviewers = [{"agent_id": r["agent_id"], "niche": (r["_meta"].get("special") or {}).get("niche", "tech"),
                  "followers": [q["agent_id"] for q in profiles if r["agent_id"] in q["media"].get("follows", [])]}
                 for r in profiles if r.get("special_role") == "reviewer"]
    desk = next((r["agent_id"] for r in profiles if r.get("special_role") == "news_desk"), None)
    m = get_map()
    plan = plan_product(p, day, traffic=_traffic(day, profiles), sites=m.sites, stores=m.stores, audience=aud,
                        reviewers=reviewers, news_desk=desk, held_sites=_held_sites(pid))
    p.plan = await write_reasons(plan, p, m.site_by_id, get_llm())
    if p.graph and p.understanding:
        p.graph = build_graph(p, p.understanding, [s.name for s in m.stores if s.store_id in p.plan.stores])
    _save(p)
    return p.plan.model_dump(mode="json")


@router.post("/products/{pid}/ready")
def mark_ready(pid: str) -> dict:
    """Draft → ready (needs a plan); appears in the World's dock."""
    p = _load(pid)
    if p.status != "draft" and p.status != "ready":
        raise HTTPException(409, f"product is {p.status}")
    if p.plan is None:
        raise HTTPException(409, "generate the plan first")
    p.status = "ready"
    return _save(p).model_dump(mode="json")


def _engine_command(cmd: dict) -> dict | None:
    """POST to world-engine /commands (ID token in the cloud); None when unreachable."""
    s = get_settings()
    headers = {}
    if s.env == "cloud":
        from google.auth.transport import requests as greq
        from google.oauth2 import id_token

        headers["Authorization"] = f"Bearer {id_token.fetch_id_token(greq.Request(), s.engine_url)}"
    try:
        r = httpx.post(f"{s.engine_url}/commands", json=cmd, headers=headers, timeout=5)
        return r.json() if r.status_code == 200 else {"error": r.status_code}
    except httpx.HTTPError:
        return None


@router.post("/products/{pid}/launch")
def launch(pid: str) -> dict:
    """Ready → live via an engine command; the engine stamps launched_at_t at the next tick (one at a time)."""
    p = _load(pid)
    if p.status != "ready":
        raise HTTPException(409, "only ready products can be launched")
    pending = [d for d in store().list(COLL, limit=200) if d.get("status") == "live" and d.get("launched_at_t") is None]
    if pending:
        raise HTTPException(409, "another launch is in progress")
    clash = {s.site_id for s in p.plan.sites} & _held_sites(pid) if p.plan else set()
    if clash:
        raise HTTPException(409, f"sites now held by a live product: {sorted(clash)} — re-plan first")
    res = _engine_command({"type": "launch", "product_id": pid})
    if res is None or "error" in res:
        raise HTTPException(503, "world-engine unreachable")
    p.status = "live"
    return _save(p).model_dump(mode="json")
