"""Single-writer lease in Firestore `world/lease` (E-07): 60 s expiry, renewed every 20 s."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from shared.store import DocStore


class Lease:
    """Compare-and-set lease; only the holder may step the world."""

    def __init__(self, store: DocStore, holder: str | None = None, expiry_s: float = 60.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.holder = holder or uuid.uuid4().hex[:12]
        self.expiry_s = expiry_s
        self.clock = clock
        self.held = False

    def acquire(self) -> bool:
        """Take or renew the lease if it is free, expired or already ours."""
        now = self.clock()

        def free(doc: dict | None) -> bool:
            return doc is None or doc.get("holder") == self.holder or float(doc.get("expires_at", 0)) < now

        self.held = self.store.update_if("world", "lease", free, {"holder": self.holder,
                                                                   "expires_at": now + self.expiry_s,
                                                                   "renewed_at": now})
        return self.held

    renew = acquire

    def release(self) -> None:
        """Give the lease up (on shutdown) so a successor can start at once."""
        self.store.update_if("world", "lease", lambda d: d is not None and d.get("holder") == self.holder,
                             {"holder": None, "expires_at": 0, "renewed_at": self.clock()})
        self.held = False
