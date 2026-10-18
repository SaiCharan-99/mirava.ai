"""Data dictionary loader (I-01 `describe_data`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PATH = Path(__file__).with_name("dictionary.yaml")


@lru_cache(maxsize=1)
def dictionary() -> dict[str, Any]:
    """Parsed `insights/dictionary.yaml`."""
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


def columns(view: str) -> list[str]:
    """Column names of one view."""
    return list(dictionary()["views"][view]["columns"])
