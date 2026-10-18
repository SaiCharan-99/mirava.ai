"""Traffic model for the auto planner (L-06): OTS per site × facing × hour × agent from the world's own movement."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from shared.schemas.world import Site
from world.map import WorldMap
from world.sites import FIELD_OF_VIEW_HALF_DEG

STEP_M = 15.0          # interpolation spacing between 10-minute samples
MAX_STEP_JUMP_M = 1500  # longer jumps are teleports (metro/off-map), not walks


@dataclass
class Points:
    """Movement points: position, heading (compass), hour of day, agent id; weight = days covered."""

    x: np.ndarray
    y: np.ndarray
    heading: np.ndarray
    hour: np.ndarray
    agent: np.ndarray
    days: int = 1


@dataclass
class Traffic:
    """OTS counts per (site_id, facing): by hour (per day average) and the distinct agents reached."""

    by_hour: dict[tuple[str, float], np.ndarray] = field(default_factory=dict)
    agents: dict[tuple[str, float], dict[int, float]] = field(default_factory=dict)
    days: int = 1
    source: str = "highlights"


def _interp(seq: list[tuple[float, float]], t0_hour: float, step_min: int) -> list[tuple[float, float, float, float]]:
    out = []
    for k in range(1, len(seq)):
        (x0, y0), (x1, y1) = seq[k - 1], seq[k]
        d = math.hypot(x1 - x0, y1 - y0)
        if d < 1.0 or d > MAX_STEP_JUMP_M:
            continue
        h = math.degrees(math.atan2(x1 - x0, -(y1 - y0))) % 360
        n = max(1, int(d // STEP_M))
        for j in range(n):
            f = j / n
            hour = (t0_hour + (k - 1 + f) * step_min / 60) % 24
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, h, hour))
    return out


def points_from_highlights(days: list[dict], agent_ids: list[int]) -> Points:
    """Interpolated walking/riding points from highlight position samples (agent order = agent_ids)."""
    xs, ys, hs, hrs, ag = [], [], [], [], []
    for h in days:
        s = h.get("samples") or {}
        pos = s.get("positions") or []
        step = int(s.get("step_min", 10))
        if len(pos) < 2:
            continue
        n_agents = min(len(pos[0]), len(agent_ids))
        for i in range(n_agents):
            for x, y, hd, hr in _interp([tuple(p[i]) for p in pos], 0.0, step):
                xs.append(x)
                ys.append(y)
                hs.append(hd)
                hrs.append(hr)
                ag.append(agent_ids[i])
    return Points(np.array(xs), np.array(ys), np.array(hs), np.array(hrs, dtype=float), np.array(ag, dtype=int),
                  days=max(1, len(days)))


def points_from_commutes(m: WorldMap, profiles: list[dict]) -> Points:
    """Fallback before any movement history: home ↔ on-map workplace along the road graph (morning, evening)."""
    xs, ys, hs, hrs, ag = [], [], [], [], []
    for p in profiles:
        home, work = m.place_by_id.get(p.get("home_place_id", "")), m.place_by_id.get(p.get("workplace_place_id") or "")
        if home is None or work is None:
            continue
        a, b = m.nearest_node(*home.entrances[0]), m.nearest_node(*work.entrances[0])
        path = [m.nodes[n] for n in m.shortest_path(a, b)]
        if len(path) < 2:
            continue
        for seq, start in ((path, 8.5), (path[::-1], 18.0)):
            pts = _interp(seq, start, 1)
            for x, y, hd, hr in pts:
                xs.append(x)
                ys.append(y)
                hs.append(hd)
                hrs.append(hr)
                ag.append(p["agent_id"])
    return Points(np.array(xs), np.array(ys), np.array(hs), np.array(hrs, dtype=float), np.array(ag, dtype=int))


def ots_mask(site: Site, facing: float, pts: Points) -> np.ndarray:
    """Vectorised `world.sites.ots`: in range, in the face's cone and looking towards the board."""
    dx, dy = pts.x - site.x, pts.y - site.y
    d = np.hypot(dx, dy)
    near = d <= site.max_distance_m
    brg = np.degrees(np.arctan2(dx, -dy)) % 360
    ang = np.abs((facing - brg + 180) % 360 - 180)
    to_board = (brg + 180) % 360
    view = np.abs((pts.heading - to_board + 180) % 360 - 180)
    return near & (ang <= site.cone_half_angle_deg) & ((view <= FIELD_OF_VIEW_HALF_DEG) | (d < 0.5))


def build_traffic(sites: list[Site], pts: Points, source: str = "highlights") -> Traffic:
    """Count OTS per site face by hour and per agent (one OTS per agent per pass ≈ per point cluster)."""
    tr = Traffic(days=pts.days, source=source)
    if pts.x.size == 0:
        return tr
    for s in sites:
        for f in s.facings:
            mk = ots_mask(s, f, pts)
            key = (s.site_id, float(f))
            hrs = pts.hour[mk].astype(int) % 24
            ags = pts.agent[mk]
            # several interpolated points per pass: count one OTS per (agent, hour) per day
            pairs = sorted(set(zip(ags.tolist(), hrs.tolist(), strict=True)))
            hist = np.zeros(24)
            per: dict[int, float] = {}
            for a, h in pairs:
                hist[h] += 1
                per[a] = per.get(a, 0.0) + 1
            tr.by_hour[key] = hist / pts.days
            tr.agents[key] = {a: c / pts.days for a, c in per.items()}
    return tr


def load_highlight_days(files: object, bucket: str, day: int, n: int = 7) -> list[dict]:
    """The last n complete highlight days before `day` (missing days skipped)."""
    out = []
    for d in range(max(1, day - n), day):
        try:
            out.append(json.loads(files.read(bucket, f"highlights/day-{d}.json")))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — absent day
            continue
    return out
