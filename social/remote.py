"""Phone / WhatsApp chats (phase 2d): who texts whom, decided by rules from the people's own state."""

from __future__ import annotations

from typing import Any


def friends_online(rel: dict[tuple[int, int], dict[str, Any]]) -> dict[int, list[tuple[int, float]]]:
    """{agent: [(friend, closeness)]} over ties that run online (channel online or both), strongest first."""
    out: dict[int, list[tuple[int, float]]] = {}
    for (a, b), r in rel.items():
        if r.get("channel") in ("online", "both") and r.get("kind") in ("family", "partner", "friend", "colleague"):
            c = float(r.get("closeness", 0.0))
            out.setdefault(a, []).append((b, c))
            out.setdefault(b, []).append((a, c))
    for v in out.values():
        v.sort(key=lambda x: (-x[1], x[0]))
    return out


def wants_to_text(agenda_weight: float, social_satisfaction: float, extraversion: float, draw: float, cfg: dict[str, Any]) -> bool:
    """Something on my mind (or I'm lonely) and I'm the texting type today."""
    reason = agenda_weight >= float(cfg["agenda_min_weight"]) or social_satisfaction < float(cfg["social_need_below"])
    p = float(cfg["base_p"]) + float(cfg["p_per_extraversion"]) * extraversion
    return reason and draw < p


def pick_partner(options: list[tuple[int, float]], available: set[int], draw: float) -> int | None:
    """One available friend, chosen with probability proportional to closeness."""
    pool = [(o, c) for o, c in options if o in available]
    if not pool:
        return None
    total = sum(c + 0.05 for _, c in pool)
    x = draw * total
    for o, c in pool:
        x -= c + 0.05
        if x <= 0:
            return o
    return pool[-1][0]
