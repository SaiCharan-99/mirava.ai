"""`python -m tools.products_audit`: list product docs and stale product ids still found in the analytics views.

Prints every Firestore product (id, name, status, launched_at_t), then every distinct `product_id` in
`beliefs_latest`, `v_funnel_daily` and `v_purchases` that is not an active product (baseline:* ids are the simulated
market and are skipped). `--archive id1,id2` sets those product docs to `archived` (hidden from every UI list, prompt
and dashboard; their events stay in BigQuery). Dry run by default: nothing is written without `--apply`.
"""

from __future__ import annotations

import argparse
from typing import Any

from shared.products import active_ids
from shared.store import DocStore, get_store

QUERIES = {"beliefs_latest": "SELECT DISTINCT product_id FROM beliefs_latest WHERE product_id IS NOT NULL",
           "v_funnel_daily": "SELECT DISTINCT product_id FROM v_funnel_daily WHERE product_id IS NOT NULL",
           "v_purchases": "SELECT DISTINCT option AS product_id FROM v_purchases WHERE option IS NOT NULL"}


def stale_in_views(runner: Any, active: set[str]) -> dict[str, list[str]]:
    """{view: [product ids that are not active and not baseline]}."""
    out: dict[str, list[str]] = {}
    for view, sql in QUERIES.items():
        try:
            rows, _ = runner.run(sql, None, trusted=True)
        except Exception as e:  # noqa: BLE001 — report and carry on with the other views
            print(f"  ! {view}: {type(e).__name__}: {str(e)[:120]}")
            continue
        out[view] = sorted({str(r["product_id"]) for r in rows} - active
                           - {str(r["product_id"]) for r in rows if str(r["product_id"]).startswith("baseline:")})
    return out


def archive(store: DocStore, ids: list[str], apply: bool) -> list[str]:
    """Set these product docs to archived (only with apply); returns the ids that exist."""
    done = []
    for pid in ids:
        doc = store.get("products", pid)
        if doc is None:
            print(f"  ? {pid}: no product doc (its old events stay; Insights already ignores it)")
            continue
        done.append(pid)
        print(f"  {'ARCHIVE' if apply else 'would archive'} {pid} (was {doc.get('status')})")
        if apply:
            store.set("products", pid, {**doc, "status": "archived"})
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", default="", help="comma-separated product ids to archive")
    ap.add_argument("--apply", action="store_true", help="really write (default: dry run)")
    args = ap.parse_args()
    from insights.tools import default_runner

    st = get_store()
    print("Product docs:")
    for d in sorted(st.list("products", 200), key=lambda d: d["product_id"]):
        print(f"  {d['product_id']:<22} {d.get('name', ''):<22} {d.get('status', ''):<9} launched_at_t={d.get('launched_at_t')}")
    act = active_ids(st)
    print("Stale product ids in the analytics views (not active):")
    for view, ids in stale_in_views(default_runner(), act).items():
        print(f"  {view}: {', '.join(ids) or '(none)'}")
    if args.archive:
        archive(st, [x.strip() for x in args.archive.split(",") if x.strip()], args.apply)
    print("APPLIED" if args.apply else "DRY RUN (nothing written)")


if __name__ == "__main__":
    main()
