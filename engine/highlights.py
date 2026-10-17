"""Day highlights (W-08): top ~40 moments + 10-minute position samples → `highlights/day-{n}.json`."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from shared import time as simtime
from shared.schemas.events import Event

TOP_N = 40
SAMPLE_EVERY = 10


@dataclass
class HighlightRecorder:
    """Bus listener + sampler; `finish_day` returns the JSON for a completed day."""

    names: dict[int, str]
    moments: list[dict[str, Any]] = field(default_factory=list)
    samples: list[list[list[float]]] = field(default_factory=list)
    day: int = 1

    def score(self, ev: Event) -> float:
        """How highlight-worthy an event is (public events only)."""
        p = ev.payload
        if ev.kind == "conversation":
            return 3.0 + p.get("n_messages", 0) / 4 + 3.0 * bool(p.get("product_mentions"))
        return {"life_event": 2.5, "purchase": 6.0, "launch": 9.0, "notice": 2.0, "post": 2.0}.get(ev.kind, 0.0)

    def on_event(self, ev: Event, xy: tuple[float, float] | None = None, first_line: str = "") -> None:
        """Record a candidate moment (never private kinds)."""
        if ev.private:
            return
        s = self.score(ev)
        if s <= 0:
            return
        a, b = ev.agent_id, ev.other_id
        na, nb = self.names.get(a or -1, f"#{a}"), self.names.get(b or -1, f"#{b}")
        if ev.kind == "conversation":
            title = f"{na} and {nb} talk" + (f" about {ev.payload['topics'][0]}" if ev.payload.get("topics") else "")
            text = first_line
        elif ev.kind == "life_event":
            title, text = f"{na}'s phone got {ev.payload.get('type')}", ""
        else:
            title, text = ev.kind.replace("_", " ").title(), ""
        x, y = xy or (0.0, 0.0)
        self.moments.append({"t": ev.t, "kind": ev.kind, "agent_ids": [i for i in (a, b) if i is not None],
                             "x": round(x, 1), "y": round(y, 1), "title": title, "text": text[:200],
                             "ref_event_id": ev.event_id, "session_id": ev.session_id, "_score": s})

    def sample(self, t: int, positions: list[tuple[float, float]]) -> None:
        """Every 10 sim minutes: all agent positions."""
        if t % SAMPLE_EVERY == 0:
            self.samples.append([[round(x, 1), round(y, 1)] for x, y in positions])

    def finish_day(self, day: int) -> dict[str, Any]:
        """Highlights JSON for `day` (INTERFACES §4.3); resets for the next day."""
        top = sorted(self.moments, key=lambda m: (-m["_score"], m["t"], m["ref_event_id"]))[:TOP_N]
        moments = [{k: v for k, v in m.items() if k != "_score"} for m in sorted(top, key=lambda m: m["t"])]
        out = {"day": day, "moments": moments,
               "samples": {"t0": (day - 1) * 1440, "step_min": SAMPLE_EVERY, "positions": self.samples}}
        self.moments, self.samples, self.day = [], [], day + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form (moments only; samples restart after a crash)."""
        return {"day": self.day, "moments": self.moments}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict."""
        self.day = int(d.get("day", self.day))
        self.moments = list(d.get("moments", []))


def key_for(day: int) -> str:
    """Object key in the worlds bucket."""
    return f"highlights/day-{day}.json"


def encode(h: dict[str, Any]) -> bytes:
    """Compact JSON bytes."""
    return json.dumps(h, separators=(",", ":")).encode()


def day_of_end(t: int) -> int | None:
    """The day that just completed when t is a midnight, else None."""
    return simtime.day_of(t) - 1 if simtime.minute_of_day(t) == 0 and t > 0 else None
