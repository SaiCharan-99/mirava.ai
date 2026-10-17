"""Load the generated map assets: road graph, places, sites, stores; grid spatial index and shortest paths."""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from shared.schemas.world import Place, Site, Store

MAPS = Path("assets/maps")


@dataclass
class WorldMap:
    """Static world geometry used by the engine and the planner."""

    nodes: list[tuple[float, float]]
    adj: dict[int, list[tuple[int, float, str, tuple[str, ...]]]]
    places: list[Place]
    sites: list[Site]
    stores: list[Store]
    cell: float = 100.0
    _node_grid: dict[tuple[int, int], list[int]] = field(default_factory=dict)
    _place_grid: dict[tuple[int, int], list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ng: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, (x, y) in enumerate(self.nodes):
            ng[(int(x // self.cell), int(y // self.cell))].append(i)
        pg: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, p in enumerate(self.places):
            x, y = p.entrances[0]
            pg[(int(x // self.cell), int(y // self.cell))].append(i)
        self._node_grid, self._place_grid = dict(ng), dict(pg)
        self.place_by_id = {p.place_id: p for p in self.places}
        self.site_by_id = {s.site_id: s for s in self.sites}

    def nearest_node(self, x: float, y: float) -> int:
        """Closest road-graph node to a point (ring search over grid buckets)."""
        gx, gy = int(x // self.cell), int(y // self.cell)
        best, bd = -1, math.inf
        for r in range(0, 40):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    for i in self._node_grid.get((gx + dx, gy + dy), []):
                        d = math.dist((x, y), self.nodes[i])
                        if d < bd:
                            best, bd = i, d
            if best >= 0 and bd <= r * self.cell:
                return best
        return best

    def places_near(self, x: float, y: float, radius: float, kinds: set[str] | None = None) -> list[Place]:
        """Places whose entrance lies within `radius` m."""
        r = int(radius // self.cell) + 1
        gx, gy = int(x // self.cell), int(y // self.cell)
        out = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for i in self._place_grid.get((gx + dx, gy + dy), []):
                    p = self.places[i]
                    if (kinds is None or p.kind in kinds) and math.dist((x, y), p.entrances[0]) <= radius:
                        out.append(p)
        return sorted(out, key=lambda p: p.place_id)

    def shortest_path(self, a: int, b: int, mode: str = "walk") -> list[int]:
        """Dijkstra over edges allowing `mode`; [] if unreachable."""
        dist = {a: 0.0}
        prev: dict[int, int] = {}
        pq = [(0.0, a)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, w, _cls, modes in self.adj.get(u, []):
                if mode not in modes:
                    continue
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd, v))
        if b not in dist:
            return []
        path = [b]
        while path[-1] != a:
            path.append(prev[path[-1]])
        return path[::-1]

    def reachable(self, start: int = 0) -> int:
        """Count of nodes reachable from `start` (any mode)."""
        seen, stack = {start}, [start]
        while stack:
            u = stack.pop()
            for v, *_ in self.adj.get(u, []):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        return len(seen)


def load_map(root: Path = MAPS) -> WorldMap:
    """Read roadgraph/places/sites/stores JSON into a WorldMap."""
    g = json.loads((root / "roadgraph.json").read_text(encoding="utf-8"))
    nodes = [(n["x"], n["y"]) for n in sorted(g["nodes"], key=lambda n: n["id"])]
    adj: dict[int, list[tuple[int, float, str, tuple[str, ...]]]] = defaultdict(list)
    for e in g["edges"]:
        m = tuple(e["modes"])
        adj[e["a"]].append((e["b"], e["len_m"], e["class"], m))
        adj[e["b"]].append((e["a"], e["len_m"], e["class"], m))
    read = lambda name: json.loads((root / name).read_text(encoding="utf-8"))  # noqa: E731
    return WorldMap(nodes=nodes, adj=dict(adj), places=[Place.model_validate(p) for p in read("places.json")],
                    sites=[Site.model_validate(s) for s in read("sites.json")],
                    stores=[Store.model_validate(s) for s in read("stores.json")])


@lru_cache
def get_map() -> WorldMap:
    """Cached default map."""
    return load_map()
