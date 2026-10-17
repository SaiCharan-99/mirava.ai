"""YAML config loaders for genesis (config/*.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG = Path("config")


@lru_cache
def load(name: str) -> dict[str, Any]:
    """Parse `config/<name>.yaml` (cached)."""
    return yaml.safe_load((CONFIG / f"{name}.yaml").read_text(encoding="utf-8"))


def market() -> dict[str, Any]:
    """Indiranagar population priors."""
    return load("markets/indiranagar")


def band_key(age: int, bands: list[str]) -> str:
    """Return the 'lo-hi' key from `bands` containing `age`."""
    for b in bands:
        lo, hi = (int(x) for x in b.split("-"))
        if lo <= age <= hi:
            return b
    return bands[-1]
