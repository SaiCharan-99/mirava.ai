"""`python -m tools.clean_beliefs`: merge duplicate belief subjects into the canonical one and drop junk.

Model-written beliefs drifted ("Pixel 10a", "Pixel-10a", "pixel-10a", "temple_visit"). For every agent this merges
non-canonical `product:` docs into `product:<id>` (most advanced stage, latest attitude, union of reasons ≤ 3, earliest
first_heard, summed sources) and deletes docs that match no product.

Dry run by default. `--apply` WRITES to the configured store (production when pointed at it): only run it after
reviewing the dry-run output.
"""

from __future__ import annotations

import argparse
from typing import Any

from commerce.consideration import STAGES
from shared.schemas.memory import Belief
from shared.store import DocStore, get_store
from shared.subjects import canonical

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


def plan_for_agent(rows: list[dict[str, Any]], catalog: dict[str, str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """({canonical subject: merged doc} to write, [doc ids] to delete) for one agent's belief rows."""
    groups: dict[str, list[dict[str, Any]]] = {}
    drop: list[str] = []
    for r in rows:
        subj = str(r.get("subject", ""))
        canon = canonical(subj, catalog)
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


def run(store: DocStore, apply: bool) -> dict[str, int]:
    """Clean every agent's beliefs; returns counts."""
    catalog = {d["product_id"]: d["name"] for d in store.list("products", 200)}
    stats = {"agents": 0, "merged": 0, "deleted": 0}
    for a in store.list("agents", 2000):
        aid = a["agent_id"]
        col = f"agents/{aid}/beliefs"
        rows = store.list(col, LIST_LIMIT)
        write, drop = plan_for_agent(rows, catalog)
        if not write and not drop:
            continue
        stats["agents"] += 1
        stats["merged"] += len(write)
        stats["deleted"] += len(drop)
        print(f"agent {aid}: write {sorted(write)} delete {sorted(drop)}")
        if apply:
            for canon, doc in write.items():
                store.set(col, canon.replace("/", "_"), doc)
            for doc_id in drop:
                store.delete(col, doc_id)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()
    stats = run(get_store(), args.apply)
    print(("APPLIED" if args.apply else "DRY RUN"), stats)


if __name__ == "__main__":
    main()
