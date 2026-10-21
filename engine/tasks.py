"""Async model-work queue (concurrency-limited); completed results apply in stable order without blocking the simulation."""

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
    """Submit coroutines now; collect completed results at or after `t_req + delay` without stopping the clock."""

    def __init__(self, concurrency: int = 32, timeout_s: float = 60.0, queue_wait_s: float | None = None) -> None:
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout_s = timeout_s
        self.queue_wait_s = queue_wait_s          # None: one deadline from submission (queue wait included)
        self.tasks: list[Task] = []

    def submit(self, key: str, make: Callable[[], Awaitable[Any]], t_req: int, delay: int,
               fallback: Callable[[], Any]) -> None:
        """Start the call; its result is eligible from sim minute t_req + delay."""
        async def run() -> Any:
            async with self.sem:
                return await make()

        async def bounded() -> Any:
            if self.queue_wait_s is None:
                try:
                    return await asyncio.wait_for(run(), self.timeout_s)
                except Exception:  # includes queue wait, provider failure and timeout
                    return fallback()
            try:
                # Waiting for a slot has its own (longer) limit: a slow provider must not time out queued work
                # before it even starts — that turned every chat into a fallback when 32 chats shared 4 ICA slots.
                await asyncio.wait_for(self.sem.acquire(), self.queue_wait_s)
            except Exception:  # noqa: BLE001 - backlog too long
                return fallback()
            try:
                return await asyncio.wait_for(make(), self.timeout_s)
            except Exception:  # provider failure or timeout
                return fallback()
            finally:
                self.sem.release()
        self.tasks.append(Task(key, t_req + delay, asyncio.ensure_future(bounded()), fallback))

    async def collect(self, t: int) -> list[tuple[str, Any]]:
        """Results due at or before t, in key order; defers stragglers while submission-time deadlines enforce fallback."""
        due = sorted((x for x in self.tasks if x.apply_t <= t), key=lambda x: (x.apply_t, x.key))
        if not due:
            return []
        # A small shared grace period, never a provider-length wait on the world clock.
        await asyncio.wait([x.fut for x in due], timeout=0.02)
        ready = [x for x in due if x.fut.done()]
        ready_ids = {id(x) for x in ready}
        self.tasks = [x for x in self.tasks if id(x) not in ready_ids]
        out = []
        for x in ready:
            try:
                res = x.fut.result()
            except (Exception, asyncio.CancelledError):
                res = x.fallback()
            out.append((x.key, res))
        return out

    @property
    def pending(self) -> int:
        """Tasks not yet collected."""
        return len(self.tasks)
