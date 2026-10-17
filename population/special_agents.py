"""Special agents inside the 1,000: reviewers, salespeople, news desk (P-08)."""

from __future__ import annotations

from typing import Any

from engine.rng import stream
from population.config import market

TECH = {"tech", "gadgets", "startups", "gaming"}
LIFESTYLE = {"fashion", "fitness", "food", "travel", "photography"}


def assign_special(people: list[dict[str, Any]], seed: int) -> None:
    """Mark reviewers (tech/lifestyle), store salespeople (with shifts) and one news desk agent in place."""
    rng = stream(seed, "special")
    cfg = market()["special_agents"]
    for p in people:
        p["special_role"], p["special"] = "none", {}
    pool = [p for p in people if 21 <= p["age"] <= 40 and p["occupation"] not in ("homemaker", "salesperson")]
    creators = [p for p in pool if p["occupation"] == "content_creator"]
    others = [p for p in pool if p["occupation"] in ("software_engineer", "product_designer", "ux_designer",
                                                      "data_analyst", "startup_founder")]
    order = creators + [others[int(i)] for i in rng.permutation(len(others))]
    taken: set[int] = set()
    for niche, n in (("tech", cfg["reviewers"]["tech"]), ("lifestyle", cfg["reviewers"]["lifestyle"])):
        for p in [p for p in order if p["i"] not in taken][:n]:
            taken.add(p["i"])
            p["special_role"] = "reviewer"
            p["occupation"], p["label"] = "content_creator", ("Tech reviewer" if niche == "tech" else
                                                               "Lifestyle creator")
            p["special"] = {"niche": niche}
            want = TECH if niche == "tech" else LIFESTYLE
            p["interests"] = sorted(set(sorted(want)[:2]) | set(p["interests"][:1]))
    sellers = [p for p in people if p["occupation"] in ("salesperson", "shop_assistant") and 19 <= p["age"] <= 50
               and p["i"] not in taken]
    sellers = [sellers[int(i)] for i in rng.permutation(len(sellers))]
    k = 0
    for store_id, n in cfg["salespeople"].items():
        for s in range(n):
            if k >= len(sellers):
                break
            p = sellers[k]
            k += 1
            taken.add(p["i"])
            p["special_role"] = "salesperson"
            p["occupation"], p["label"] = "salesperson", "Retail salesperson"
            p["special"] = {"store_id": store_id, "shift": "a" if s % 2 == 0 else "b"}
            p["offmap"] = False
    desk = next((p for p in people if p["occupation"] == "journalist" and p["i"] not in taken), None)
    if desk is None:
        return
    desk["special_role"], desk["label"] = "news_desk", "News desk editor"
    desk["special"] = {"outlet": "The Indiranagar Times"}
    desk["offmap"] = False
