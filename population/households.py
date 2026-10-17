"""Group sampled people into households and place them in residential buildings (P-03)."""

from __future__ import annotations

from typing import Any

import numpy as np

from engine.rng import stream
from population.config import market
from world.map import WorldMap


def form_households(people: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Return households `{household_id, kind, members:[(i, role)]}`; every person belongs to exactly one."""
    rng = stream(seed, "households")
    hcfg = market()["household"]
    left = {p["i"] for p in people}
    by = {p["i"]: p for p in people}
    order = [int(i) for i in rng.permutation(len(people))]
    hh: list[dict[str, Any]] = []

    def take(i: int) -> None:
        left.discard(i)

    # couples among working-age adults (25–60), greedily matched by age
    cand = [i for i in order if 25 <= by[i]["age"] <= 60 and by[i]["occupation"] != "college_student"]
    fem = sorted([i for i in cand if by[i]["gender"] == "female"], key=lambda i: by[i]["age"])
    mal = sorted([i for i in cand if by[i]["gender"] == "male"], key=lambda i: by[i]["age"])
    n_couples = int(min(len(fem), len(mal)) * 0.86)
    pick_f = sorted(int(x) for x in rng.choice(len(fem), size=n_couples, replace=False))
    used_m: set[int] = set()
    couples: list[list[int]] = []
    for fi in pick_f:
        f = fem[fi]
        best = None
        for m in mal:
            if m in used_m:
                continue
            d = by[m]["age"] - by[f]["age"]
            if -3 <= d <= 7:
                best = m
                break
        if best is not None:
            used_m.add(best)
            couples.append([f, best])
    for c in couples:
        for i in c:
            take(i)
    fams = [{"members": [(c[0], "spouse"), (c[1], "head")], "kids": 0, "elders": 0, "age": by[c[0]]["age"]}
            for c in couples]

    # children (and some 18–24s) live with a couple whose mother is 20–42 years older
    def place_child(i: int, max_kids: int) -> bool:
        age = by[i]["age"]
        for f in fams:
            if f["kids"] < max_kids and 20 <= f["age"] - age <= 42:
                f["members"].append((i, "child"))
                f["kids"] += 1
                return True
        return False

    for i in sorted((i for i in order if by[i]["age"] < 18), key=lambda i: by[i]["age"]):
        if place_child(i, 2) or place_child(i, 3):
            take(i)
    young = [i for i in order if i in left and 18 <= by[i]["age"] <= 24]
    for i in young:
        if rng.random() < 0.45 and place_child(i, 3):
            take(i)

    # elders join their children's families (joint) or live as couples / alone
    elders = [i for i in order if i in left and by[i]["age"] >= 60]
    for i in elders:
        if rng.random() < hcfg["joint_share_of_elderly"]:
            for f in fams:
                if f["elders"] < 2 and 20 <= by[i]["age"] - f["age"] <= 40:
                    f["members"].append((i, "parent"))
                    f["elders"] += 1
                    take(i)
                    break
    for f in fams:
        kind = "joint" if f["elders"] else ("nuclear" if f["kids"] else "couple")
        hh.append({"kind": kind, "members": f["members"]})
    rest_elders = [i for i in elders if i in left]
    while len(rest_elders) >= 2 and rng.random() < 0.6:
        a, b = rest_elders.pop(), rest_elders.pop()
        take(a)
        take(b)
        hh.append({"kind": "couple", "members": [(a, "head"), (b, "spouse")]})

    # unplaced children: attach to any adult household (single parent)
    for i in [i for i in order if i in left and by[i]["age"] < 18]:
        adults = [h for h in hh if any(by[m]["age"] >= by[i]["age"] + 20 for m, _ in h["members"])]
        h = adults[int(rng.integers(len(adults)))] if adults else None
        if h is None:
            hh.append({"kind": "single", "members": [(i, "self")]})
        else:
            h["members"].append((i, "child"))
            h["kind"] = "nuclear" if h["kind"] in ("couple", "single") else h["kind"]
        take(i)

    # young singles: flatmates in groups of 2–4, others alone
    singles = [i for i in order if i in left]
    flat = [i for i in singles if by[i]["age"] <= 34 and rng.random() < hcfg["flatmate_share_of_young_singles"] * 1.6]
    while len(flat) >= 2:
        k = min(len(flat), int(rng.integers(2, 5)))
        grp, flat = flat[:k], flat[k:]
        for i in grp:
            take(i)
        hh.append({"kind": "flatmates", "members": [(i, "flatmate") for i in grp]})
    for i in [i for i in order if i in left]:
        take(i)
        hh.append({"kind": "single", "members": [(i, "self")]})
    for n, h in enumerate(hh):
        h["household_id"] = f"H-{n:04d}"
        h["members"].sort(key=lambda mr: (-by[mr[0]]["age"]))
    return hh


def place_homes(households: list[dict[str, Any]], wm: WorldMap, seed: int) -> None:
    """Assign each household a distinct residential place (`home_place_id`), deterministic."""
    rng = stream(seed, "homes")
    homes = sorted((p for p in wm.places if p.kind == "home"), key=lambda p: p.place_id)
    # bias towards larger buildings for big households (capacity proxy)
    idx = rng.choice(len(homes), size=len(households), replace=False)
    picked = sorted((homes[int(i)] for i in idx), key=lambda p: -p.capacity)
    big_first = sorted(range(len(households)), key=lambda h: -len(households[h]["members"]))
    for h_i, place in zip(big_first, picked, strict=True):
        households[h_i]["home_place_id"] = place.place_id
        households[h_i]["home_xy"] = tuple(place.entrances[0])


def household_sizes(households: list[dict[str, Any]]) -> np.ndarray:
    """Array of household sizes (for audits)."""
    return np.array([len(h["members"]) for h in households])
