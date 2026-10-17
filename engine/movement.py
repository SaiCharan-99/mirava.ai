"""Movement on the road graph (E-02): A* per mode, merged segments with headings, map exits and the metro."""

from __future__ import annotations

import heapq
import math
from collections import OrderedDict
from dataclasses import dataclass

from world.map import WorldMap

VEHICLE_MODES = ("two_wheeler", "car", "auto", "bus")
OFFMAP_DIR = {"Whitefield": (1, 0), "Koramangala": (0, 1), "MG Road": (-1, 0), "Electronic City": (0.3, 1),
              "Manyata": (0, -1), "Bellandur": (0.8, 0.7), "Domlur": (0.6, 0.6)}


def heading(x0: float, y0: float, x1: float, y1: float) -> float:
    """Compass heading in degrees (0 = north, clockwise; y grows south)."""
    return round(math.degrees(math.atan2(x1 - x0, -(y1 - y0))) % 360, 1)


@dataclass
class Seg:
    """One straight movement segment (sim minutes, metres)."""

    x0: float
    y0: float
    x1: float
    y1: float
    t0: float
    t1: float
    mode: str

    def at(self, t: float) -> tuple[float, float]:
        """Interpolated position at sim time t."""
        if self.t1 <= self.t0:
            return self.x1, self.y1
        f = min(1.0, max(0.0, (t - self.t0) / (self.t1 - self.t0)))
        return self.x0 + (self.x1 - self.x0) * f, self.y0 + (self.y1 - self.y0) * f

    @property
    def heading(self) -> float:
        """Direction of travel."""
        return heading(self.x0, self.y0, self.x1, self.y1)

    def wire(self, agent_id: int) -> dict:
        """Live-protocol shape (INTERFACES §4.4)."""
        return {"a": agent_id, "x0": round(self.x0, 1), "y0": round(self.y0, 1), "x1": round(self.x1, 1),
                "y1": round(self.y1, 1), "t0": round(self.t0, 2), "t1": round(self.t1, 2), "mode": self.mode}

    def pack(self) -> list:
        """Compact list for checkpoints."""
        return [self.x0, self.y0, self.x1, self.y1, self.t0, self.t1, self.mode]


class Router:
    """A* with an LRU path cache; nodes per mode; map exits for off-map destinations."""

    def __init__(self, wm: WorldMap, speeds: dict[str, float], cache_size: int = 40000) -> None:
        self.wm = wm
        self.speeds = speeds
        self.cache: OrderedDict[tuple[int, int, str], list[int]] = OrderedDict()
        self.cache_size = cache_size
        self.mode_nodes: dict[str, list[int]] = {}
        for m in ("walk",) + VEHICLE_MODES:
            ok = sorted({u for u, nb in wm.adj.items() if any(m in e[3] for e in nb)})
            self.mode_nodes[m] = ok
        xs = [p[0] for p in wm.nodes]
        ys = [p[1] for p in wm.nodes]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        cx, cy = (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2
        self.centre = (cx, cy)
        car = self.mode_nodes["car"]
        edge = [n for n in car if min(wm.nodes[n][0] - self.bbox[0], self.bbox[2] - wm.nodes[n][0],
                                      wm.nodes[n][1] - self.bbox[1], self.bbox[3] - wm.nodes[n][1]) < 60]
        self.exits = edge or car[:1]
        metro = [p for p in wm.places if p.kind == "metro"]
        self.metro_xy = tuple(metro[0].entrances[0]) if metro else self.centre
        self._grid: dict[str, dict[tuple[int, int], list[int]]] = {}

    def exit_for(self, area: str | None) -> int:
        """Map-exit node in the direction of an off-map area."""
        dx, dy = OFFMAP_DIR.get(area or "", (1, 0))
        cx, cy = self.centre
        return max(self.exits, key=lambda n: ((self.wm.nodes[n][0] - cx) * dx + (self.wm.nodes[n][1] - cy) * dy, -n))

    def nearest(self, x: float, y: float, mode: str) -> int:
        """Nearest node usable by `mode`."""
        g = self._grid.get(mode)
        if g is None:
            g = {}
            for n in self.mode_nodes[mode]:
                nx, ny = self.wm.nodes[n]
                g.setdefault((int(nx // 100), int(ny // 100)), []).append(n)
            self._grid[mode] = g
        gx, gy = int(x // 100), int(y // 100)
        best, bd = -1, math.inf
        for r in range(0, 30):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    for n in g.get((gx + dx, gy + dy), []):
                        d = math.dist((x, y), self.wm.nodes[n])
                        if d < bd:
                            best, bd = n, d
            if best >= 0 and bd <= r * 100:
                break
        return best

    def path(self, a: int, b: int, mode: str) -> list[int]:
        """A* node path for `mode` (cached); [] if unreachable."""
        key = (a, b, mode)
        hit = self.cache.get(key)
        if hit is not None:
            self.cache.move_to_end(key)
            return hit
        nodes = self.wm.nodes
        bx, by = nodes[b]
        g = {a: 0.0}
        prev: dict[int, int] = {}
        pq = [(math.dist(nodes[a], (bx, by)), 0.0, a)]
        while pq:
            _f, d, u = heapq.heappop(pq)
            if u == b:
                break
            if d > g.get(u, math.inf):
                continue
            for v, w, _cls, modes in self.wm.adj.get(u, []):
                if mode not in modes:
                    continue
                nd = d + w
                if nd < g.get(v, math.inf):
                    g[v], prev[v] = nd, u
                    vx, vy = nodes[v]
                    heapq.heappush(pq, (nd + math.hypot(vx - bx, vy - by), nd, v))
        out: list[int] = []
        if b in g:
            out = [b]
            while out[-1] != a:
                out.append(prev[out[-1]])
            out.reverse()
        self.cache[key] = out
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return out

    def leg(self, x0: float, y0: float, x1: float, y1: float, mode: str, t0: float,
            end_node: int | None = None) -> list[Seg]:
        """Segments from (x0,y0) to (x1,y1) along roads for `mode`, starting at sim time t0."""
        net = "walk" if mode == "walk" else ("bus" if mode == "bus" else "car" if mode == "car" else mode)
        if net not in self.mode_nodes or not self.mode_nodes[net]:
            net = "walk"
        a = self.nearest(x0, y0, net)
        b = end_node if end_node is not None else self.nearest(x1, y1, net)
        nodes = self.path(a, b, net) if a != b else [a]
        if not nodes and net != "walk":
            return self.leg(x0, y0, x1, y1, "walk", t0, None)
        pts = [(x0, y0)] + [self.wm.nodes[n] for n in nodes] + [(x1, y1)]
        pts = _simplify(pts)
        speed = self.speeds.get(mode, self.speeds["walk"])
        segs, t = [], t0
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            dt = math.dist((ax, ay), (bx, by)) / speed
            segs.append(Seg(ax, ay, bx, by, t, t + dt, mode))
            t += dt
        return segs


def _simplify(pts: list[tuple[float, float]], tol_deg: float = 8.0) -> list[tuple[float, float]]:
    """Drop duplicate points and merge nearly collinear runs (fewer live segments)."""
    out: list[tuple[float, float]] = []
    for p in pts:
        if out and math.dist(out[-1], p) < 0.5:
            continue
        if len(out) >= 2:
            h1 = heading(*out[-2], *out[-1])
            h2 = heading(*out[-1], *p)
            if abs((h2 - h1 + 180) % 360 - 180) < tol_deg:
                out[-1] = p
                continue
        out.append(p)
    if len(out) == 1:
        out.append(out[0])
    return out
