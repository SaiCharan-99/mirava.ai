"""Document store: Firestore (emulator locally) with an in-memory fallback for tests."""

from __future__ import annotations

import builtins
import copy
import os
import threading
from collections.abc import Callable
from typing import Any, Protocol

from shared.settings import Settings, get_settings


class DocStore(Protocol):
    """Minimal document API used by api and engine."""

    def get(self, collection: str, doc_id: str) -> dict | None: ...
    def set(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None: ...
    def delete(self, collection: str, doc_id: str) -> None: ...
    def list(self, collection: str, limit: int = 1000) -> list[dict]: ...
    def set_many(self, collection: str, docs: dict[str, dict], merge: bool = False) -> None: ...
    def where(self, collection: str, field: str, value: Any, limit: int = 1000) -> builtins.list[dict]: ...
    def update_if(self, collection: str, doc_id: str, pred: Callable[[dict | None], bool], data: dict) -> bool: ...


_LOCK = threading.Lock()


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

    def set_many(self, collection: str, docs: dict[str, dict], merge: bool = False) -> None:
        """Write many documents."""
        for k, v in docs.items():
            self.set(collection, k, v, merge)

    def where(self, collection: str, field: str, value: Any, limit: int = 1000) -> builtins.list[dict]:
        """Documents whose top-level `field` equals `value`."""
        return [copy.deepcopy(v) for v in self._d.get(collection, {}).values() if v.get(field) == value][:limit]

    def update_if(self, collection: str, doc_id: str, pred: Callable[[dict | None], bool], data: dict) -> bool:
        """Atomically write `data` if `pred(current)` holds (lease compare-and-set)."""
        with _LOCK:
            if not pred(self.get(collection, doc_id)):
                return False
            self.set(collection, doc_id, data)
            return True


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

    def set_many(self, collection: str, docs: dict[str, dict], merge: bool = False) -> None:
        """Batched writes (≤ 450 per commit)."""
        items = list(docs.items())
        for i in range(0, len(items), 450):
            batch = self._db.batch()
            for k, v in items[i:i + 450]:
                batch.set(self._db.collection(collection).document(k), v, merge=merge)
            batch.commit()

    def where(self, collection: str, field: str, value: Any, limit: int = 1000) -> builtins.list[dict]:
        """Equality query on one field."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = self._db.collection(collection).where(filter=FieldFilter(field, "==", value)).limit(limit)
        return [d.to_dict() for d in q.stream()]

    def update_if(self, collection: str, doc_id: str, pred: Callable[[dict | None], bool], data: dict) -> bool:
        """Transactional compare-and-set."""
        from google.cloud import firestore

        ref = self._db.collection(collection).document(doc_id)

        @firestore.transactional
        def run(tx: Any) -> bool:
            snap = ref.get(transaction=tx)
            if not pred(snap.to_dict() if snap.exists else None):
                return False
            tx.set(ref, data)
            return True

        return bool(run(self._db.transaction()))


_default: DocStore | None = None


def get_store(settings: Settings | None = None, *, memory: bool = False) -> DocStore:
    """Firestore (emulator or cloud), or in-memory when `memory=True` or STORE_BACKEND=memory."""
    global _default
    s = settings or get_settings()
    if memory:
        return MemoryStoreBackend()
    if settings is None and _default is not None:
        return _default
    store: DocStore = MemoryStoreBackend() if s.store_backend == "memory" else FirestoreBackend(s)
    if settings is None:
        _default = store
    return store
