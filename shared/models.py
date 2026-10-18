"""The only place model ids live (INTERFACES §8). Gemini 3 only; overridable via MODEL_*_ID."""

from __future__ import annotations

import os

MODEL_PRO: str = os.environ.get("MODEL_PRO_ID", "google/gemini-3.1-pro-preview")
MODEL_FLASH: str = os.environ.get("MODEL_FLASH_ID", "google/gemini-3.6-flash")
MODEL_LITE: str = os.environ.get("MODEL_LITE_ID", "google/gemini-3.5-flash-lite")
MODEL_EMBED: str = os.environ.get("MODEL_EMBED_ID", "google/gemini-embedding-001")

CHAT_MODELS: tuple[str, ...] = (MODEL_PRO, MODEL_FLASH, MODEL_LITE)
EMBED_MODELS: tuple[str, ...] = (MODEL_EMBED,)
ALL_MODELS: tuple[str, ...] = CHAT_MODELS + EMBED_MODELS

# Standard prices in USD per million tokens (in, out), checked on OpenRouter 2026-10-17 (docs/techstack.md).
PRICES: dict[str, tuple[float, float]] = {"pro": (2.00, 12.00), "flash": (0.75, 3.75), "lite": (0.30, 2.50),
                                          "embed": (0.15, 0.0)}


def price_per_mtok(tier: str) -> tuple[float, float]:
    """(input, output) USD per million tokens for pro | flash | lite | embed."""
    return PRICES[tier]


def cost_usd(tier: str, tokens_in: int, tokens_out: int) -> float:
    """Estimated cost of one call."""
    pin, pout = PRICES[tier]
    return (tokens_in * pin + tokens_out * pout) / 1e6
