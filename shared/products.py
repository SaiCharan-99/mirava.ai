"""One source of truth for which products exist now (UI lists, prompts, dashboards, engine)."""

from __future__ import annotations

from typing import Any

from shared.store import DocStore

ACTIVE = ("live", "ready")


def active_products(store: DocStore, *, include_ended: bool = False, include_drafts: bool = False
                    ) -> list[dict[str, Any]]:
    """Products with status live/ready (+ ended / draft on request), never archived; sorted by launch time."""
    ok = set(ACTIVE) | ({"ended"} if include_ended else set()) | ({"draft"} if include_drafts else set())
    docs = [d for d in store.list("products", 200) if d.get("status") in ok]
    return sorted(docs, key=lambda d: (d.get("launched_at_t") is None, d.get("launched_at_t") or 0, d["product_id"]))


def active_ids(store: DocStore, *, include_ended: bool = True) -> set[str]:
    """Product ids that still count (archived and deleted ones do not)."""
    return {d["product_id"] for d in active_products(store, include_ended=include_ended, include_drafts=True)}
