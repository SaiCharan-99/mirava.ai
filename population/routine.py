"""Routine templates and workplace assignment (P-04)."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from engine.rng import stream
from population.config import load, market
from world.map import WorldMap

ROUTINE_BY_OCC_DEFAULT = "office"


@lru_cache
def templates() -> dict[str, Any]:
    """Routine templates from config/routines.yaml."""
    return load("routines")["templates"]


def routine_id_for(p: dict[str, Any]) -> str:
    """Pick the routine template id for one person."""
    if p["special_role"] == "reviewer":
        return "reviewer"
    if p["special_role"] == "news_desk":
        return "news_desk"
    if p["special_role"] == "salesperson":
        return f"salesperson_{p['special']['shift']}"
    return str(market()["occupations"][p["occupation"]]["routine"])


def _near(wm: WorldMap, xy: tuple[float, float], kinds: set[str], k: int) -> list[str]:
    """Ids of the `k` places of `kinds` closest to `xy`."""
    key = tuple(sorted(kinds))
    by_kind = wm.__dict__.setdefault("_by_kinds", {})
    if key not in by_kind:
        by_kind[key] = [p for p in wm.places if p.kind in kinds]
    cands = sorted(by_kind[key], key=lambda p: (math.dist(xy, p.entrances[0]), p.place_id))
    return [p.place_id for p in cands[:k]]


def assign_workplaces(people: list[dict[str, Any]], homes: dict[int, tuple[float, float]], wm: WorldMap,
                      seed: int) -> None:
    """Set `workplace_place_id` (None for off-map, roaming or no work) and nearby haunts for each person."""
    rng = stream(seed, "work")
    store_place = {s.store_id: s.place_id for s in wm.stores}
    offices = sorted(p.place_id for p in wm.places if p.kind in ("office",))
    techpark = [p.place_id for p in wm.places if p.kind == "techpark"]
    news = [p.place_id for p in wm.places if p.kind == "office"]
    for p in people:
        home = homes[p["i"]]
        work = market()["occupations"][p["occupation"]]["work"]
        wp: str | None = None
        if p["special_role"] == "salesperson":
            wp = store_place[p["special"]["store_id"]]
        elif p["special_role"] == "news_desk":
            wp = news[int(rng.integers(len(news)))]
        elif p["offmap"]:
            wp = None
        elif work == "school":
            wp = _near(wm, home, {"school"}, 3)[int(rng.integers(3))]
        elif work == "college":
            wp = _near(wm, home, {"college"}, 3)[int(rng.integers(3))]
        elif work == "techpark":
            wp = techpark[0] if techpark and rng.random() < 0.5 else offices[int(rng.integers(len(offices)))]
        elif work == "office":
            wp = offices[int(rng.integers(len(offices)))]
        elif work == "shop":
            near = _near(wm, home, {"shop"}, 25)
            wp = near[int(rng.integers(len(near)))]
        elif work == "restaurant":
            near = _near(wm, home, {"restaurant", "cafe"}, 20)
            wp = near[int(rng.integers(len(near)))]
        elif work == "home":
            wp = None
        p["workplace_place_id"] = wp
        p["work_kind"] = "offmap" if p["offmap"] else work
        p["haunts"] = {
            "cafe": _near(wm, home, {"cafe"}, 4), "eat": _near(wm, home, {"restaurant", "cafe"}, 5),
            "gym": _near(wm, home, {"gym"}, 2), "park": _near(wm, home, {"park"}, 3),
            "shop": _near(wm, home, {"shop", "mall", "store"}, 6),
        }
        if work == "roaming_homes":
            p["haunts"]["homes"] = [h for h in _near(wm, home, {"home"}, 6) if h != p.get("home_place_id")][:3]
        if wp is not None:
            wxy = wm.place_by_id[wp].entrances[0]
            p["haunts"]["eat_work"] = _near(wm, (wxy[0], wxy[1]), {"restaurant", "cafe"}, 4)
        p["routine_id"] = routine_id_for(p)
        p["wake_jitter"] = int(rng.integers(-load("routines")["jitter_min"], load("routines")["jitter_min"] + 1))
