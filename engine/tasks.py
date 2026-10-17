"""Async model-work queue (concurrency-limited); results apply at deterministic sim times."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    """One queued model call."""

    key: str
    apply_t: int
    fut: asyncio.Task
    fallback: Callable[[], Any]
    result: Any = field(default=None)


class TaskQueue:
    """Submit coroutines now; collect their results exactly at `t_req + delay` regardless of latency."""

    def __init__(self, concurrency: int = 32, timeout_s: float = 60.0) -> None:
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout_s = timeout_s
        self.tasks: list[Task] = []

    def submit(self, key: str, make: Callable[[], Awaitable[Any]], t_req: int, delay: int,
               fallback: Callable[[], Any]) -> None:
        """Start the call; its result is applied at sim minute t_req + delay."""
        async def run() -> Any:
            async with self.sem:
                return await make()
        self.tasks.append(Task(key, t_req + delay, asyncio.ensure_future(run()), fallback))

    async def collect(self, t: int) -> list[tuple[str, Any]]:
        """Results due at or before t, in key order; waits for stragglers, falls back on timeout or error."""
        due = sorted((x for x in self.tasks if x.apply_t <= t), key=lambda x: (x.apply_t, x.key))
        self.tasks = [x for x in self.tasks if x.apply_t > t]
        out = []
        for x in due:
            try:
                res = await asyncio.wait_for(x.fut, self.timeout_s)
            except Exception:  # noqa: BLE001 — timeouts and model errors use the template fallback
                res = x.fallback()
            out.append((x.key, res))
        return out

    @property
    def pending(self) -> int:
        """Tasks not yet collected."""
        return len(self.tasks)
