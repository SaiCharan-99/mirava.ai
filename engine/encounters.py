"""Encounter detection (E-03): 16 m spatial hash, co-located ≥ 2 sim min, available, per-pair cool-down."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

CELL_M = 16.0
MIN_TOGETHER = 2
COOLDOWN = 180


@dataclass
class Presence:
    """Where one available agent is this minute."""

    agent_id: int
    x: float
    y: float
    place_id: str | None


@dataclass
class EncounterTracker:
    """Tracks how long pairs have been within 16 m and yields each pair once per cool-down."""

    radius_m: float = CELL_M
    min_minutes: int = MIN_TOGETHER
    cooldown: int = COOLDOWN
    since: dict[tuple[int, int], int] = field(default_factory=dict)
    last_met: dict[tuple[int, int], int] = field(default_factory=dict)

    def close_pairs(self, people: list[Presence]) -> set[tuple[int, int]]:
        """All unordered pairs (a < b) within `radius_m` (neighbour cells of a uniform grid)."""
        grid: dict[tuple[int, int], list[Presence]] = defaultdict(list)
        for p in people:
            grid[(int(p.x // self.radius_m), int(p.y // self.radius_m))].append(p)
        out: set[tuple[int, int]] = set()
        for (cx, cy), cell in grid.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for q in grid.get((cx + dx, cy + dy), []):
                        for p in cell:
                            if p.agent_id < q.agent_id and math.dist((p.x, p.y), (q.x, q.y)) <= self.radius_m:
                                out.add((p.agent_id, q.agent_id))
        return out

    def update(self, t: int, people: list[Presence]) -> list[tuple[int, int]]:
        """Pairs that have now been together ≥ min_minutes and are off cool-down (sorted, each agent once)."""
        close = self.close_pairs(people)
        self.since = {k: v for k, v in self.since.items() if k in close}
        for k in close:
            self.since.setdefault(k, t)
        ready = sorted(k for k, s0 in self.since.items()
                       if t - s0 >= self.min_minutes and t - self.last_met.get(k, -10**9) >= self.cooldown)
        used: set[int] = set()
        out = []
        for a, b in ready:
            if a in used or b in used:
                continue
            used.update((a, b))
            out.append((a, b))
        return out

    def met(self, pair: tuple[int, int], t: int) -> None:
        """Start the cool-down for a pair (whether or not they talked)."""
        self.last_met[pair] = t
        self.since.pop(pair, None)
