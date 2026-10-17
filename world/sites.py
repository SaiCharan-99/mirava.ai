"""Hoarding-site exposure geometry (A-01 / W-04): is an agent in a board's cone, in range and looking at it?"""

from __future__ import annotations

import math

from pydantic import BaseModel

from shared.schemas.world import Site

FIELD_OF_VIEW_HALF_DEG = 60.0  # how far off-heading an agent can still see a board


class OTS(BaseModel):
    """Opportunity to see: geometry of one agent ↔ board face."""

    distance_m: float
    angle_deg: float          # angle between the face's direction and the board→agent vector
    view_angle_deg: float     # angle between the agent's heading and the agent→board vector
    in_cone: bool


def bearing(dx: float, dy: float) -> float:
    """Compass bearing in map space (0 = north, clockwise; y grows southwards)."""
    return math.degrees(math.atan2(dx, -dy)) % 360


def ang_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings (0–180)."""
    return abs((a - b + 180) % 360 - 180)


def ots(site: Site, facing: float, x: float, y: float, heading: float) -> OTS | None:
    """OTS for one face, or None when the agent is out of range, behind the board or looking away."""
    dx, dy = x - site.x, y - site.y
    d = math.hypot(dx, dy)
    if d > site.max_distance_m:
        return None
    if d < 0.5:
        return OTS(distance_m=d, angle_deg=0.0, view_angle_deg=0.0, in_cone=True)
    angle = ang_diff(facing, bearing(dx, dy))
    if angle > site.cone_half_angle_deg:
        return None
    view = ang_diff(heading, bearing(-dx, -dy))
    if view > FIELD_OF_VIEW_HALF_DEG:
        return None
    return OTS(distance_m=round(d, 2), angle_deg=round(angle, 2), view_angle_deg=round(view, 2), in_cone=True)


def best_ots(site: Site, x: float, y: float, heading: float) -> tuple[float, OTS] | None:
    """The face (facing, OTS) the agent sees best, if any."""
    hits = [(f, o) for f in site.facings if (o := ots(site, f, x, y, heading)) is not None]
    return min(hits, key=lambda h: (h[1].distance_m, h[1].angle_deg)) if hits else None
