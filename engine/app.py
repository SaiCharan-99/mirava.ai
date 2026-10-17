"""world-engine FastAPI app: loop in the lifespan, `/live`, `/health(z)`, `/state`, `/stats`, `/commands`."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from engine.events import make_sink
from engine.loop import Engine
from shared.files import get_files
from shared.settings import get_settings
from shared.store import get_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
engine: Engine | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the world loop as a background task; checkpoint and release the lease on shutdown."""
    global engine
    s = get_settings()
    engine = Engine(s, get_store(), get_files(), make_sink(s))
    task = asyncio.create_task(engine.run())
    yield
    await engine.shutdown()
    task.cancel()


app = FastAPI(title="mirava world-engine", lifespan=lifespan)


def _eng() -> Engine:
    if engine is None:
        raise HTTPException(503, "engine starting")
    return engine


@app.get("/health")
@app.get("/healthz")
@app.get("/api/healthz")
def health() -> JSONResponse:
    """200 if a tick happened in the last 120 s, else 500 (watchdog restarts the container)."""
    e = _eng()
    ok = e.healthy()
    return JSONResponse({"ok": ok, "status": e.status, "t": e.world.t if e.world else None}, status_code=200 if ok else 500)


@app.get("/state")
def state() -> dict:
    """World clock, scale, status, budget and engine diagnostics."""
    return _eng().state()


@app.get("/stats")
def stats() -> dict:
    """Live stats frame."""
    e = _eng()
    if e.world is None:
        raise HTTPException(503, "world not loaded")
    return e.world.stats(e.budget())


@app.get("/agents/{agent_id}/state")
def agent_state(agent_id: int) -> dict:
    """Live AgentState of one agent."""
    e = _eng()
    if e.world is None or not 0 <= agent_id < e.world.n:
        raise HTTPException(404, "unknown agent")
    return e.world.agent_state(agent_id).model_dump() | {"phone": e.world.phones[agent_id]}


def _authorised(request: Request) -> bool:
    """Local: open. Cloud: Google ID token from an allowed service account (api)."""
    s = get_settings()
    if s.env == "local":
        return True
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    try:
        from google.auth.transport import requests as greq
        from google.oauth2 import id_token

        info: dict[str, Any] = id_token.verify_oauth2_token(auth[7:], greq.Request(), audience=s.engine_auth_audience)
    except Exception:  # noqa: BLE001 — any verification failure is a 403
        return False
    allowed = {x.strip() for x in s.engine_allowed_callers.split(",") if x.strip()}
    return info.get("email") in allowed


@app.post("/commands")
async def commands(request: Request) -> dict:
    """pause | resume | set_speed (launch/poll/restore in later phases)."""
    if not _authorised(request):
        raise HTTPException(403, "forbidden")
    return _eng().command(await request.json())


@app.websocket("/live")
async def live(ws: WebSocket) -> None:
    """Public read-only stream."""
    await ws.accept()
    e = _eng()
    await e.hub.join(ws, e)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        e.hub.leave(ws)
