"""Checkpoints (E-07): msgpack+zstd of the full world every sim hour; pointer in `world/state`."""

from __future__ import annotations

from typing import Any

from population.genesis import pack, unpack
from shared.files import Files
from shared.store import DocStore


def key_for(t: int) -> str:
    """Object key for a checkpoint at sim time t."""
    return f"checkpoints/{t:08d}.msgpack.zst"


def save(files: Files, bucket: str, store: DocStore, state: dict[str, Any]) -> dict[str, Any]:
    """Write a checkpoint and move the pointer; returns {key, bytes}."""
    data = pack(state)
    key = key_for(int(state["t"]))
    files.write(bucket, key, data)
    store.set("world", "state", {"last_checkpoint": key, "checkpoint_t": int(state["t"])}, merge=True)
    return {"key": key, "bytes": len(data)}


def load_latest(files: Files, bucket: str, store: DocStore) -> dict[str, Any] | None:
    """Latest checkpoint named by the pointer, or None."""
    doc = store.get("world", "state") or {}
    key = doc.get("last_checkpoint")
    if not key or not files.exists(bucket, key):
        return None
    return unpack(files.read(bucket, key))
