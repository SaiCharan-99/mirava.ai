"""Document store: Firestore (emulator locally) with an in-memory fallback for tests."""

from __future__ import annotations

import copy
import os
from typing import Any, Protocol

from shared.settings import Settings, get_settings


class DocStore(Protocol):
    """Minimal document API used by api and engine."""

    def get(self, collection: str, doc_id: str) -> dict | None: ...
    def set(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None: ...
    def delete(self, collection: str, doc_id: str) -> None: ...
    def list(self, collection: str, limit: int = 1000) -> list[dict]: ...


class MemoryStoreBackend:
    """In-process dict store (tests, offline)."""

    def __init__(self) -> None:
        self._d: dict[str, dict[str, dict]] = {}

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Fetch a copy of one document."""
        doc = self._d.get(collection, {}).get(doc_id)
        return copy.deepcopy(doc) if doc is not None else None

    def set(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None:
        """Write (or merge) one document."""
        col = self._d.setdefault(collection, {})
        col[doc_id] = {**col.get(doc_id, {}), **copy.deepcopy(data)} if merge else copy.deepcopy(data)

    def delete(self, collection: str, doc_id: str) -> None:
        """Delete one document if present."""
        self._d.get(collection, {}).pop(doc_id, None)

    def list(self, collection: str, limit: int = 1000) -> list[dict]:
        """List up to `limit` documents."""
        return [copy.deepcopy(v) for v in list(self._d.get(collection, {}).values())[:limit]]


class FirestoreBackend:
    """google-cloud-firestore; honours FIRESTORE_EMULATOR_HOST locally."""

    def __init__(self, settings: Settings) -> None:
        from google.cloud import firestore

        if settings.env == "local" and settings.firestore_emulator_host:
            os.environ.setdefault("FIRESTORE_EMULATOR_HOST", settings.firestore_emulator_host)
        self._db: Any = firestore.Client(project=settings.gcp_project_id)

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Fetch one document."""
        snap = self._db.collection(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def set(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None:
        """Write (or merge) one document."""
        self._db.collection(collection).document(doc_id).set(data, merge=merge)

    def delete(self, collection: str, doc_id: str) -> None:
        """Delete one document."""
        self._db.collection(collection).document(doc_id).delete()

    def list(self, collection: str, limit: int = 1000) -> list[dict]:
        """List up to `limit` documents."""
        return [d.to_dict() for d in self._db.collection(collection).limit(limit).stream()]


def get_store(settings: Settings | None = None, *, memory: bool = False) -> DocStore:
    """Firestore (emulator or cloud), or in-memory when `memory=True`."""
    if memory:
        return MemoryStoreBackend()
    return FirestoreBackend(settings or get_settings())
