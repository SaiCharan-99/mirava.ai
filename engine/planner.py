"""Daily plans from routine templates (E-01): pick options, jitter times, resolve places."""

from __future__ import annotations

from typing import Any

from engine.rng import choice, stream
from population.routine import templates

OFFMAP = "offmap"


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def build_plan(profile: dict[str, Any], meta: dict[str, Any], day: int, seed: int) -> list[dict[str, Any]]:
    """Today's blocks `[{s, e, act, place}]` covering minutes 0..1440 (place None = roam)."""
    rng = stream(seed, "plan", day, profile["agent_id"])
    weekday = (day - 1) % 7 < 5
    tpl = templates()[profile["routine_id"]]["weekday" if weekday else "weekend"]
    jitter = int(meta.get("wake_jitter") or 0) + int(rng.integers(-10, 11))
    raw: list[tuple[int, str]] = []
    for k, b in enumerate(tpl):
        start = _hm(b["at"])
        if k > 0:
            start = max(1, min(1439, start + jitter))
        if start == 0 and k > 0:
            start = 1439
        act = b.get("act") or choice(rng, b["options"])
        raw.append((start, act))
    raw.sort(key=lambda x: x[0])
    blocks: list[dict[str, Any]] = []
    for k, (s, act) in enumerate(raw):
        e = raw[k + 1][0] if k + 1 < len(raw) else 1440
        if e <= s:
            continue
        prev = blocks[-1]["act"] if blocks else None
        place = resolve_place(profile, meta, act, prev, rng)
        if blocks and blocks[-1]["act"] == act and blocks[-1]["place"] == place:
            blocks[-1]["e"] = e
            continue
        blocks.append({"s": s, "e": e, "act": act, "place": place})
    if blocks and blocks[0]["s"] > 0:
        blocks[0]["s"] = 0
    return blocks


def resolve_place(profile: dict[str, Any], meta: dict[str, Any], act: str, prev: str | None, rng: Any) -> str | None:
    """Place id for an activity (home, workplace, a haunt, OFFMAP, or None for roaming)."""
    home = profile["home_place_id"]
    work = profile.get("workplace_place_id")
    wk = meta.get("work_kind")
    haunts = meta.get("haunts") or {}

    def pick(key: str) -> str:
        opts = haunts.get(key) or []
        return opts[int(rng.integers(len(opts)))] if opts else home

    if act in ("sleep", "home"):
        return home
    if act in ("work", "school", "college", "store_shift"):
        if wk == "offmap":
            return OFFMAP
        if wk in ("home", "none") or work is None:
            return home if wk != "roaming_homes" else pick("homes")
        return work
    if act == "roam":
        return None
    if act == "eat":
        if wk == "offmap" and prev in ("work", "college"):
            return OFFMAP
        if prev in ("work", "store_shift") and haunts.get("eat_work"):
            return pick("eat_work")
        return pick("eat")
    if act in ("cafe", "gym", "park", "shop"):
        return pick(act)
    return home
