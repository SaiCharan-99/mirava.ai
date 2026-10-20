"""Canonical belief subjects: `product:<id>`, `brand:<slug>`, `category:<slug>`.

Model output is free text ("Pixel 10a", "Pixel-10a", "pixel-10a", "temple_visit"). Every subject written to a belief
or a consideration pair goes through `canonical` first, so one product is always one subject and junk is dropped.
"""

from __future__ import annotations

import difflib
import re

FUZZY_CUTOFF = 0.85
PHONE_WORDS = {"phone", "phones", "smartphone", "smartphones", "mobile", "mobiles"}


def slug(s: str) -> str:
    """Lowercase alphanumerics joined by single hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _product_id(name: str, catalog: dict[str, str]) -> str | None:
    """Product id for a free-text product reference, or None when it matches nothing in the catalog."""
    key = slug(name)
    if not key:
        return None
    by_slug: dict[str, str] = {}
    for pid, pname in catalog.items():
        by_slug.setdefault(slug(pid), pid)
        by_slug.setdefault(slug(pname), pid)
    if key in by_slug:
        return by_slug[key]
    close = difflib.get_close_matches(key, list(by_slug), n=1, cutoff=FUZZY_CUTOFF)
    return by_slug[close[0]] if close else None


def canonical(subject: str, catalog: dict[str, str]) -> str | None:
    """Canonical form of a subject; `catalog` maps product_id → display name. None means drop it."""
    if ":" not in subject:
        return None
    prefix, rest = subject.split(":", 1)
    prefix = prefix.strip().lower()
    if prefix == "product":
        pid = _product_id(rest, catalog)
        return f"product:{pid}" if pid else None
    if prefix == "brand":
        s = slug(rest)
        return f"brand:{s}" if s else None
    if prefix == "category":
        s = slug(rest)
        if not s:
            return None
        return "category:phone" if s in PHONE_WORDS else f"category:{s}"
    return None
