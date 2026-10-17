"""mirava.ai REST API (Cloud Run `mirava-api`). Phase 1: health + world state stub."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared import time as simtime
from shared.settings import get_settings

app = FastAPI(title="mirava.ai api", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")


@app.get("/healthz")
@api.get("/healthz")
def healthz() -> dict:
    """Liveness probe (also reachable through the Hosting rewrite at /api/healthz)."""
    s = get_settings()
    return {"ok": True, "service": "api", "env": s.env, "llm_backend": s.llm_backend}


@api.get("/world/state")
def world_state() -> dict:
    """Placeholder world state until world-engine exists (phase 2)."""
    t = simtime.at(23, 8 + 40 / 60)
    return {"t": t, "day": simtime.day_of(t), "label": simtime.fmt(t), "scale": {"sim_min_per_real_s": 0.4},
            "slowed": False, "status": "not_started", "budget": {"used_usd": 0.0, "cap_usd": get_settings().daily_cap_usd}}


app.include_router(api)
