"""`python -m tools.clean_beliefs`: merge duplicate belief subjects into the canonical one and drop junk.

Model-written beliefs drifted ("Pixel 10a", "Pixel-10a", "pixel-10a", "temple_visit"). For every agent this merges
non-canonical `product:` docs into `product:<id>` (most advanced stage, latest attitude, union of reasons ≤ 3, earliest
first_heard, summed sources) and deletes docs that match no product.

Brand subjects that are not phone brands (model-written noise such as "grocery app" or a person's name) are dropped.

Dry run by default. `--apply` WRITES to the configured store (production when pointed at it): only run it after
reviewing the dry-run output. Every document that would be changed or deleted is first saved to `--backup FILE`
(JSON), and `--restore FILE` puts them back.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from commerce.consideration import STAGES
from population.config import load
from shared.schemas.memory import Belief
from shared.store import DocStore, get_store
from shared.subjects import canonical, slug

LIST_LIMIT = 500


def merge(docs: list[dict[str, Any]], subject: str) -> dict[str, Any]:
    """One belief doc from several that name the same subject."""
    docs = sorted(docs, key=lambda d: int(d.get("updated_t", 0)))
    latest = docs[-1]
    out = dict(latest)
    out["subject"] = subject
    out["stage"] = max((d.get("stage", "unaware") for d in docs), key=lambda s: STAGES.index(s) if s in STAGES else 0)
    for key in ("reasons_for", "reasons_against", "open_questions"):
        out[key] = list(dict.fromkeys(x for d in reversed(docs) for x in d.get(key, [])))[:3]
    firsts = [d["first_heard"] for d in docs if d.get("first_heard")]
    out["first_heard"] = min(firsts, key=lambda f: int(f.get("t", 0))) if firsts else None
    seen: dict[str, int] = {}
    for d in docs:
        for ch, n in (d.get("sources_seen") or {}).items():
            seen[ch] = seen.get(ch, 0) + int(n)
    out["sources_seen"] = seen
    return Belief.model_validate(out).model_dump()


def phone_brands(products: list[dict[str, Any]]) -> set[str]:
    """Slugs of real phone brands: the simulated market's brands plus the brands of every product in the catalog."""
    market = load("phones_market")["brand_share_by_band"]
    names = {b for shares in market.values() for b in shares} | {str(p.get("brand", "")) for p in products}
    return {slug(n) for n in names if n}


def plan_for_agent(rows: list[dict[str, Any]], catalog: dict[str, str], brands: set[str] | None = None
                   ) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """({canonical subject: merged doc} to write, [doc ids] to delete) for one agent's belief rows."""
    groups: dict[str, list[dict[str, Any]]] = {}
    drop: list[str] = []
    for r in rows:
        subj = str(r.get("subject", ""))
        canon = canonical(subj, catalog)
        if canon is not None and canon.startswith("brand:") and brands is not None and canon.split(":", 1)[1] not in brands:
            canon = None                                      # not a phone brand: model noise
        if canon is None:
            drop.append(subj.replace("/", "_"))
            continue
        groups.setdefault(canon, []).append(r)
    write: dict[str, dict[str, Any]] = {}
    for canon, docs in groups.items():
        if len(docs) == 1 and docs[0].get("subject") == canon:
            continue
        write[canon] = merge(docs, canon)
        drop += [str(d["subject"]).replace("/", "_") for d in docs if d["subject"] != canon]
    return write, drop


def run(store: DocStore, apply: bool, backup: Path | None = None) -> dict[str, int]:
    """Clean every agent's beliefs; returns counts.

    Two passes: first plan every agent and collect the documents that would change; with `apply`, save those to
    `backup` (complete, before anything is touched), then make the changes."""
    prods = store.list("products", 200)
    catalog = {d["product_id"]: d["name"] for d in prods}
    brands = phone_brands(prods)
    stats = {"agents": 0, "merged": 0, "deleted": 0}
    saved: dict[str, dict[str, Any]] = {}                     # "agents/<id>/beliefs/<doc id>" → document
    plans: list[tuple[str, dict[str, dict[str, Any]], list[str]]] = []
    for a in store.list("agents", 2000):
        col = f"agents/{a['agent_id']}/beliefs"
        rows = store.list(col, LIST_LIMIT)
        write, drop = plan_for_agent(rows, catalog, brands)
        if not write and not drop:
            continue
        touched = {str(r["subject"]).replace("/", "_"): r for r in rows}
        for doc_id in set(drop) | {c.replace("/", "_") for c in write}:
            if doc_id in touched:
                saved[f"{col}/{doc_id}"] = touched[doc_id]
        plans.append((col, write, drop))
        stats["agents"] += 1
        stats["merged"] += len(write)
        stats["deleted"] += len(drop)
        print(f"agent {a['agent_id']}: write {sorted(write)} delete {sorted(drop)}")
    if apply:
        if backup is not None:
            backup.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        for col, write, drop in plans:
            for canon, doc in write.items():
                store.set(col, canon.replace("/", "_"), doc)
            for doc_id in drop:
                store.delete(col, doc_id)
    return stats


def restore(store: DocStore, backup: Path) -> int:
    """Put back every document saved by a previous `--apply` (merged ones are overwritten with their old form)."""
    saved = json.loads(backup.read_text(encoding="utf-8"))
    for path, doc in saved.items():
        col, doc_id = path.rsplit("/", 1)
        store.set(col, doc_id, doc)
    return len(saved)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--backup", type=Path, default=Path("belief-backup.json"), help="where --apply saves the old documents")
    ap.add_argument("--restore", type=Path, help="restore the documents saved in this backup file and exit")
    args = ap.parse_args()
    if args.restore:
        print("RESTORED", restore(get_store(), args.restore), "documents")
        return
    stats = run(get_store(), args.apply, args.backup if args.apply else None)
    print(("APPLIED" if args.apply else "DRY RUN"), stats)


if __name__ == "__main__":
    main()
