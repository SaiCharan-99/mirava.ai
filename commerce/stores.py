"""Fictional stores (S-04): opening hours, stock (launched products + baseline market), salesperson shifts."""

from __future__ import annotations

from typing import Any

from population.config import load
from shared.schemas.world import Store

BASELINE = [dict(b) for b in load("phones_market")["baseline_market"]]


def stores_cfg() -> dict[str, Any]:
    """`config/stores.yaml`."""
    return load("stores")


def is_open(store: Store, minute_of_day: int) -> bool:
    """Within opening hours."""
    a, b = store.opening_hours
    return a <= minute_of_day < b


def stock(store: Store, live_products: list[dict[str, Any]]) -> dict[str, int]:
    """Units per product id or baseline id: launched products whose plan lists this store + the baseline market."""
    c = stores_cfg()
    out = {b["id"]: int(c["baseline_stock_units"]) for b in BASELINE}
    for p in live_products:
        plan = p.get("plan") or {}
        if store.store_id in (plan.get("stores") or []) or store.kind == "online":
            out[p["product_id"]] = int(c["default_stock_units"])
    return out


def assign_staff(stores: list[Store], salespeople: list[int]) -> dict[str, list[int]]:
    """Salesperson agent ids per physical store (2 each, deterministic order)."""
    per = int(stores_cfg()["salespeople_per_store"])
    phys = [s for s in sorted(stores, key=lambda s: s.store_id) if s.kind != "online"]
    out: dict[str, list[int]] = {s.store_id: [] for s in stores}
    ids = sorted(salespeople)
    for i, s in enumerate(phys):
        out[s.store_id] = ids[i * per:(i + 1) * per]
    online = next((s for s in stores if s.kind == "online"), None)
    if online is not None:
        out[online.store_id] = ids[len(phys) * per:len(phys) * per + 1] or ids[:1]
    return out


def on_shift(store: Store, staff: list[int], minute_of_day: int) -> int | None:
    """Salesperson on the floor now (shift 1 or 2), or None when closed / unstaffed."""
    if not staff or not is_open(store, minute_of_day):
        return None
    if store.kind == "online":
        return staff[0]
    shifts = stores_cfg()["shifts"]
    for i, (a, b) in enumerate(shifts):
        if a <= minute_of_day < b and i < len(staff):
            return staff[i]
    return staff[0]


def offers(store_id: str) -> list[str]:
    """Current offers at a store."""
    return list(stores_cfg()["offers"].get(store_id, []))
