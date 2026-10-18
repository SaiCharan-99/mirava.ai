"""Exposure geometry + attention model (A-01, A-02, A-05): pass / glance / notice without a model call."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml

from shared.schemas.product import StimulusRecord
from shared.schemas.world import Site
from world.sites import OTS, ang_diff, bearing

CONFIG = Path(__file__).resolve().parents[1] / "config" / "attention.yaml"
Outcome = Literal["pass", "glance", "notice"]


@lru_cache(maxsize=1)
def cfg() -> dict[str, Any]:
    """config/attention.yaml (assumptions)."""
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def sigmoid(z: float) -> float:
    """Logistic function."""
    return 1.0 / (1.0 + math.exp(-z))


def is_night(minute_of_day: int) -> bool:
    """Inside the configured night window."""
    a, b = cfg()["night"]
    return minute_of_day >= a or minute_of_day < b


def ots(site: Site, facing: float, x: float, y: float, heading: float, *, still: bool = False,
        minute_of_day: int | None = None) -> OTS | None:
    """OTS for one face: in front, in the cone, in range, looking roughly towards it, and lit at night."""
    if minute_of_day is not None and is_night(minute_of_day) and not site.lit:
        return None
    dx, dy = x - site.x, y - site.y
    d = math.hypot(dx, dy)
    if d > site.max_distance_m:
        return None
    if d < 0.5:
        return OTS(distance_m=d, angle_deg=0.0, view_angle_deg=0.0, in_cone=True)
    angle = ang_diff(facing, bearing(dx, dy))
    if angle > site.cone_half_angle_deg or angle >= 90:
        return None
    view = ang_diff(heading, bearing(-dx, -dy))
    lim = cfg()["view_half_angle_still_deg" if still else "view_half_angle_deg"]
    if view > lim:
        return None
    return OTS(distance_m=round(d, 2), angle_deg=round(angle, 2), view_angle_deg=round(view, 2), in_cone=True)


@dataclass
class AttentionCtx:
    """Situation of one exposure (everything except the creative)."""

    mode: str = "walk"
    dwell_s: float = 10.0
    lit_night: bool = False
    clutter: int = 0              # other boards within 100 m
    on_phone: bool = False
    fatigue: float = 0.0          # 0–1
    relevance: float = 0.0        # 0–1: interests, category need, target match
    attitude: float = 0.0         # prior belief −1…1
    familiarity: float = 0.0      # 0–1 brand awareness
    need: float = 0.0             # 0–1 category need (old/broken phone)
    n_seen: int = 0               # earlier exposures of this creative
    n_noticed: int = 0            # earlier notices of this creative


def dwell_seconds(site: Site, mode: str, still: bool) -> float:
    """Seconds inside the cone for one pass (straight-line chord at the mode's speed; still = a minute)."""
    v = float(cfg()["speed_m_s"].get(mode, 1.4))
    if still or v <= 0:
        return 60.0
    return min(60.0, 2 * site.max_distance_m * math.sin(math.radians(site.cone_half_angle_deg)) / v)


def novelty(n_seen: int) -> float:
    """1 for a first exposure, halving every `novelty_half_life` exposures (A-05)."""
    return 0.5 ** (n_seen / float(cfg()["novelty_half_life"]))


def p_glance(site: Site, o: OTS, stim: StimulusRecord, ctx: AttentionCtx) -> float:
    """Glance probability."""
    a = cfg()["glance"]
    area = site.width_m * site.height_m
    z = (a["a0"] + a["a1"] * math.log(area / max(1.0, o.distance_m) ** 2) + a["a2"] * ctx.dwell_s
         + a["a3"] * ctx.lit_night + a["a4"] * stim.salience - a["a5"] * ctx.clutter - a["a6"] * ctx.on_phone
         - a["a7"] * ctx.fatigue - a["a8"] * (ctx.mode in ("car", "two_wheeler")))
    return sigmoid(z)


def p_notice(stim: StimulusRecord, ctx: AttentionCtx) -> float:
    """Notice probability given a glance (novelty decays; wear-out after ~8 notices)."""
    b = cfg()["notice"]
    wear = float(cfg()["wear_out_penalty"]) if ctx.n_noticed >= int(cfg()["wear_out_after_notices"]) else 0.0
    z = (b["b0"] + b["b1"] * ctx.relevance + b["b2"] * novelty(ctx.n_seen) + b["b3"] * ctx.attitude
         + b["b4"] * stim.clarity + b["b5"] * ctx.familiarity + b["b6"] * ctx.need - wear)
    return sigmoid(z)


def attend(site: Site, o: OTS, stim: StimulusRecord, ctx: AttentionCtx, rng: np.random.Generator) -> Outcome:
    """Seeded draw: pass, glance or notice."""
    u1, u2 = rng.random(), rng.random()
    if u1 >= p_glance(site, o, stim, ctx):
        return "pass"
    return "notice" if u2 < p_notice(stim, ctx) else "glance"


FeedOutcome = Literal["scroll", "partial", "full"]


def attend_feed(stim: StimulusRecord, interest: float, item_idx: int, ctx: AttentionCtx,
                rng: np.random.Generator) -> FeedOutcome:
    """Feed item: scroll past, partial or full watch (partial/full count as notice)."""
    f = cfg()["feed"]
    z = (f["c0"] + f["hook"] * stim.salience + f["interest"] * interest - f["fatigue_per_item"] * item_idx
         + cfg()["notice"]["b2"] * (novelty(ctx.n_seen) - 1) - (float(cfg()["wear_out_penalty"])
         if ctx.n_noticed >= int(cfg()["wear_out_after_notices"]) else 0.0))
    u1, u2 = rng.random(), rng.random()
    if u1 >= sigmoid(z):
        return "scroll"
    return "full" if u2 < float(f["full_share_of_watch"]) * (0.5 + interest) else "partial"


def attend_print(size: str, page: str, interest: float, ctx: AttentionCtx, stim: StimulusRecord,
                 rng: np.random.Generator) -> Outcome:
    """Print ad seen by a reader: attention by size and page position."""
    p = cfg()["print"]
    z = p["c0"] + p["size"].get(size, 0.0) + p["page"].get(page, 0.0) + 0.6 * stim.salience - 0.5 * ctx.fatigue
    if rng.random() >= sigmoid(z):
        return "pass"
    return "notice" if rng.random() < p_notice(stim, AttentionCtx(**{**ctx.__dict__, "relevance": interest})) \
        else "glance"
