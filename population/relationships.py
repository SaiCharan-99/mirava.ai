"""Relationship graph: family, partner, friends, colleagues, neighbours, followers (P-03)."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

from engine.rng import stream
from shared.schemas.agent import Relationship


def build_relationships(people: list[dict[str, Any]], households: list[dict[str, Any]],
                        seed: int) -> list[Relationship]:
    """All edges with closeness and channel; undirected pairs stored with a < b (followers: a follows b)."""
    rng = stream(seed, "relationships")
    by = {p["i"]: p for p in people}
    edges: dict[tuple[int, int], Relationship] = {}

    def add(a: int, b: int, kind: str, closeness: float, channel: str) -> None:
        if a == b:
            return
        key = (min(a, b), max(a, b)) if kind != "follower" else (a, b)
        if kind != "follower" and key in edges:
            return
        if kind == "follower" and (key in edges or (key[1], key[0]) in edges):
            return
        edges[key] = Relationship(a=key[0], b=key[1], kind=kind, closeness=round(float(closeness), 2),  # type: ignore[arg-type]
                                  channel=channel)  # type: ignore[arg-type]

    for h in households:
        mem = [m for m, _ in h["members"]]
        roles = dict(h["members"])
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                a, b = mem[x], mem[y]
                if h["kind"] == "flatmates":
                    add(a, b, "friend", rng.uniform(0.45, 0.75), "both")
                elif {roles[a], roles[b]} == {"head", "spouse"}:
                    add(a, b, "partner", rng.uniform(0.7, 0.98), "both")
                else:
                    add(a, b, "family", rng.uniform(0.6, 0.95), "both")

    # colleagues: same in-map workplace, or same occupation working off-map (teams of ~8)
    groups: dict[str, list[int]] = defaultdict(list)
    for p in people:
        if p["workplace_place_id"] and p["work_kind"] not in ("none", "home"):
            groups[p["workplace_place_id"]].append(p["i"])
        elif p["work_kind"] in ("offmap", "roaming"):
            groups[f"{p['work_kind']}:{p['occupation']}"].append(p["i"])
    for g in sorted(groups):
        mem = groups[g]
        if g.startswith(("offmap", "roaming")):
            mem = [mem[int(i)] for i in rng.permutation(len(mem))]
            teams = [mem[k:k + 8] for k in range(0, len(mem), 8)]
        else:
            teams = [mem]
        for team in teams:
            for a in team:
                others = [b for b in team if b != a]
                if not others:
                    continue
                k = min(len(others), int(rng.integers(1, 4)))
                for j in rng.choice(len(others), size=k, replace=False):
                    add(a, others[int(j)], "colleague", rng.uniform(0.2, 0.6), "both")

    # neighbours: homes within 70 m, different households
    home = {p["i"]: p["home_xy"] for p in people}
    hh_of = {p["i"]: p["household_id"] for p in people}
    cell: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x, y) in home.items():
        cell[(int(x // 70), int(y // 70))].append(i)
    for i in sorted(home):
        if by[i]["age"] < 14:
            continue
        x, y = home[i]
        cx, cy = int(x // 70), int(y // 70)
        near = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in cell.get((cx + dx, cy + dy), [])
                if hh_of[j] != hh_of[i] and math.dist(home[j], (x, y)) <= 70 and by[j]["age"] >= 14]
        near.sort()
        if near:
            for j in rng.choice(len(near), size=min(len(near), int(rng.integers(1, 3))), replace=False):
                add(i, near[int(j)], "neighbour", rng.uniform(0.15, 0.5), "in_person")

    # friends: homophily on age, interests and distance (~5 per person)
    ids = sorted(by)
    ages = np.array([by[i]["age"] for i in ids])
    for i in ids:
        p = by[i]
        want = int(rng.poisson(2.6)) + 1
        cand = rng.choice(len(ids), size=min(80, len(ids)), replace=False)
        scored = []
        for c in cand:
            j = ids[int(c)]
            if j == i or hh_of[j] == hh_of[i]:
                continue
            age_gap = abs(int(ages[int(c)]) - p["age"])
            if (p["age"] < 18) != (by[j]["age"] < 18):
                continue
            shared = len(set(p["interests"]) & set(by[j]["interests"]))
            dist = math.dist(home[i], home[j])
            s = -age_gap / 6 + shared * 1.2 - dist / 900 + rng.normal(0, 0.6)
            scored.append((s, j))
        scored.sort(reverse=True)
        for _, j in scored[:want]:
            add(i, j, "friend", rng.uniform(0.3, 0.9), "both" if rng.random() < 0.6 else "online")

    # followers: agent → reviewer (from media diet)
    for p in people:
        for r in p.get("follows", []):
            add(p["i"], r, "follower", rng.uniform(0.05, 0.3), "online")
    return sorted(edges.values(), key=lambda e: (e.a, e.b))


def degrees(edges: list[Relationship], n: int) -> np.ndarray:
    """Degree of every agent (followers count for both ends)."""
    d = np.zeros(n, dtype=int)
    for e in edges:
        d[e.a] += 1
        d[e.b] += 1
    return d
