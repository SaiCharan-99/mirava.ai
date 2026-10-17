"""EventBus (E-04): deterministic event ids, batching to DuckDB (local) or Pub/Sub (cloud), running hash."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from shared import time as simtime
from shared.schemas.events import PRIVATE_KINDS, Event, make_event_id
from shared.settings import Settings, get_settings

log = logging.getLogger("engine.events")


class Sink(Protocol):
    """Where event batches go."""

    def write(self, events: list[dict], texts: list[dict]) -> None: ...


class NullSink:
    """Discards everything (tests)."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.texts: list[dict] = []

    def write(self, events: list[dict], texts: list[dict]) -> None:
        """Keep rows in memory."""
        self.events.extend(events)
        self.texts.extend(texts)


class DuckDBSink:
    """Local analytics: DuckDB tables `events` / `texts` (idempotent on primary key)."""

    def __init__(self, settings: Settings | None = None) -> None:
        from shared.bq import DuckDBShim

        s = settings or get_settings()
        self.db = DuckDBShim(s.duckdb_path, s.bq_dataset)

    def write(self, events: list[dict], texts: list[dict]) -> None:
        """Insert rows."""
        self.db.insert("events", events)
        if texts:
            self.db.insert("texts", texts)


class PubSubSink:
    """Cloud: publish JSON rows to `world-events` / `world-texts` (BigQuery subscriptions write the tables)."""

    def __init__(self, settings: Settings | None = None) -> None:
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        s = settings or get_settings()
        batch = pubsub_v1.types.BatchSettings(max_messages=500, max_latency=0.5)
        self.pub = pubsub_v1.PublisherClient(batch_settings=batch)
        self.t_events = self.pub.topic_path(s.gcp_project_id, s.pubsub_topic_events)
        self.t_texts = self.pub.topic_path(s.gcp_project_id, s.pubsub_topic_texts)

    def write(self, events: list[dict], texts: list[dict]) -> None:
        """Publish and wait for the batch to be accepted."""
        futs = [self.pub.publish(self.t_events, json.dumps(_bq_row(e)).encode()) for e in events]
        futs += [self.pub.publish(self.t_texts, json.dumps(t).encode()) for t in texts]
        for f in futs:
            f.result(timeout=60)


def _bq_row(e: dict) -> dict:
    """Row shape for the BigQuery subscription (JSON payload as a string, ISO timestamp)."""
    out = dict(e)
    out["payload"] = e["payload"] if isinstance(e["payload"], str) else json.dumps(e["payload"])
    t_real = e["t_real"]
    out["t_real"] = t_real.isoformat() if isinstance(t_real, datetime) else t_real
    return out


def make_sink(settings: Settings | None = None) -> Sink:
    """Pub/Sub when EVENT_SINK=pubsub, else DuckDB."""
    s = settings or get_settings()
    return PubSubSink(s) if s.event_sink == "pubsub" else DuckDBSink(s)


class EventBus:
    """Collects events for the current tick; ids are `{kind}:{t}:{agent}:{seq}` and replay-safe."""

    def __init__(self, sink: Sink, *, suppress_until_t: int = -1) -> None:
        self.sink = sink
        self.suppress_until_t = suppress_until_t
        self._buf: list[dict] = []
        self._texts: list[dict] = []
        self._seq: dict[tuple[str, int, int | None], int] = {}
        self._seq_t = -1
        self.hash = hashlib.sha256()
        self.count = 0
        self.listeners: list[Callable[[Event], None]] = []
        self.last_flushed_t = -1

    def new(self, kind: str, t: int, agent_id: int | None, payload: dict[str, Any], **kw: Any) -> Event:
        """Build an Event with the next deterministic sequence number and emit it."""
        if t != self._seq_t:
            self._seq.clear()
            self._seq_t = t
        key = (kind, t, agent_id)
        seq = self._seq.get(key, 0)
        self._seq[key] = seq + 1
        ev = Event(event_id=make_event_id(kind, t, agent_id, seq), t=t, day=simtime.day_of(t),
                   t_real=datetime.now(UTC), kind=kind, agent_id=agent_id, payload=payload,
                   private=kind in PRIVATE_KINDS, **kw)
        self.emit(ev)
        return ev

    def emit(self, event: Event) -> None:
        """Queue one event (dropped if it was already published before a restart)."""
        body = event.model_dump(exclude={"t_real"}, mode="json")
        self.hash.update(json.dumps(body, sort_keys=True).encode())
        self.count += 1
        if event.t <= self.suppress_until_t:
            return
        row = event.model_dump()
        self._buf.append(row)
        for fn in self.listeners:
            fn(event)

    def emit_text(self, text_row: dict) -> None:
        """Queue one `texts` row."""
        if int(text_row.get("t", 0)) > self.suppress_until_t:
            self._texts.append(text_row)

    @property
    def pending(self) -> int:
        """Rows waiting to be flushed."""
        return len(self._buf) + len(self._texts)

    def flush_sync(self, upto_t: int | None = None) -> int:
        """Write buffered rows to the sink; returns rows written."""
        rows, texts = self._buf, self._texts
        self._buf, self._texts = [], []
        if rows or texts:
            self.sink.write(rows, texts)
        if upto_t is not None:
            self.last_flushed_t = max(self.last_flushed_t, upto_t)
        return len(rows) + len(texts)

    async def flush(self, upto_t: int | None = None) -> int:
        """Async flush (runs the blocking sink in a thread)."""
        rows, texts = self._buf, self._texts
        self._buf, self._texts = [], []
        if rows or texts:
            await asyncio.to_thread(self.sink.write, rows, texts)
        if upto_t is not None:
            self.last_flushed_t = max(self.last_flushed_t, upto_t)
        return len(rows) + len(texts)

    def digest(self) -> str:
        """Hex digest of every event emitted so far (determinism checks; excludes t_real)."""
        return self.hash.copy().hexdigest()
