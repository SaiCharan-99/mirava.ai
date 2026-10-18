"""`/live` WebSocket hub (W-07): hello snapshot, then seg / evt / stats / clock frames (INTERFACES §4.4)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.clock import Clock
    from engine.loop import Engine
    from engine.world import World


def hello(world: World, clock: Clock, budget: dict[str, float]) -> dict[str, Any]:
    """Snapshot for a new viewer."""
    return {"type": "hello", "t": world.t, "scale": {"sim_min_per_real_s": clock.sim_min_per_real_s},
            "slowed": clock.slowed, "agents": world.wire_agents(), "segments": world.wire_segments(),
            "bubbles": [], "products": world.products_live, "sites": world.sites_live, "stats": world.stats(budget)}


def tick_frames(world: World, clock: Clock) -> list[dict[str, Any]]:
    """Frames produced by one tick."""
    out: list[dict[str, Any]] = []
    if world.new_segs:
        out.append({"type": "seg", "items": world.new_segs})
    if world.live_evts:
        out.append({"type": "evt", "items": [_trim(e) for e in world.live_evts]})
    out.append({"type": "clock", "t": world.t, "speed": 0.0 if clock.paused else clock.speed})
    return out


def _trim(e: dict[str, Any]) -> dict[str, Any]:
    """Texts in evt are truncated to 140 characters."""
    return {k: (v[:140] if isinstance(v, str) and k in ("text", "thought") else v) for k, v in e.items()}


class LiveHub:
    """Fan-out to connected viewers; slow viewers are dropped rather than slowing the world."""

    def __init__(self) -> None:
        self.clients: set[Any] = set()

    async def join(self, ws: Any, engine: Engine) -> None:
        """Register a viewer and send hello (if the world is loaded)."""
        self.clients.add(ws)
        if engine.world is not None:
            await ws.send_text(json.dumps(hello(engine.world, engine.clock, engine.budget())))

    def leave(self, ws: Any) -> None:
        """Forget a viewer."""
        self.clients.discard(ws)

    async def send_all(self, frame: dict[str, Any]) -> None:
        """Send one frame to everyone (1 s timeout each)."""
        if not self.clients:
            return
        data = json.dumps(frame, separators=(",", ":"))

        async def one(ws: Any) -> None:
            try:
                await asyncio.wait_for(ws.send_text(data), 1.0)
            except Exception:  # noqa: BLE001 — a broken socket just leaves
                self.leave(ws)

        await asyncio.gather(*(one(ws) for ws in list(self.clients)))

    async def push_tick(self, world: World, clock: Clock) -> None:
        """Frames for the tick just simulated."""
        for f in tick_frames(world, clock):
            await self.send_all(f)

    async def broadcast_hello(self, engine: Engine) -> None:
        """Re-send hello to everyone (after a boot)."""
        if engine.world is not None:
            await self.send_all(hello(engine.world, engine.clock, engine.budget()))
