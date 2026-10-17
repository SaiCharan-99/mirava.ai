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
