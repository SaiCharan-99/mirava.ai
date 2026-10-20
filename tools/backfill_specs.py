"""`python -m tools.backfill_specs`: write `specs` (truth per attribute, opinion engine) on products that lack them.

Keyword rules by default (no model cost). `--llm` blends in a neutral Flash rating (costs a few cents).
Dry run by default; `--apply` WRITES to the configured store (production when pointed at it).
"""

from __future__ import annotations

import argparse
import asyncio

from agents.understanding import extract_specs
from shared.llm import get_llm
from shared.schemas.product import Product
from shared.store import get_store


async def run(apply: bool, use_llm: bool) -> int:
    """Fill missing specs; returns how many products were (or would be) updated."""
    store = get_store()
    llm = get_llm() if use_llm else None
    n = 0
    for d in store.list("products", 200):
        if d.get("specs"):
            continue
        p = Product.model_validate(d)
        specs = await extract_specs(p, llm)
        print(f"{p.product_id}: {specs}")
        n += 1
        if apply:
            store.set("products", p.product_id, {"specs": specs}, True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--llm", action="store_true", help="blend in a neutral Flash rating")
    args = ap.parse_args()
    n = asyncio.run(run(args.apply, args.llm))
    print(("APPLIED" if args.apply else "DRY RUN"), n, "products")


if __name__ == "__main__":
    main()
