"""Single-writer lease in Firestore `world/lease` (E-07): 60 s expiry, renewed every 20 s, revision handoff."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Callable

from shared.store import DocStore


def rev_num(revision: str | None) -> int:
    """Numeric part of a Cloud Run revision name (`world-engine-00007-abc` → 7); 0 if unknown."""
    m = re.search(r"-(\d{5})-", revision or "")
    return int(m.group(1)) if m else 0


class Lease:
    """Compare-and-set lease; only the holder may step the world. A newer revision may request a handoff."""

    def __init__(self, store: DocStore, holder: str | None = None, expiry_s: float = 60.0,
                 clock: Callable[[], float] = time.time, revision: str | None = None) -> None:
        self.store = store
        self.holder = holder or uuid.uuid4().hex[:12]
        self.revision = revision if revision is not None else os.environ.get("K_REVISION", "")
        self.expiry_s = expiry_s
        self.clock = clock
        self.held = False

    def acquire(self) -> bool:
        """Take or renew the lease if it is free, expired or already ours (never against a newer takeover)."""
        now = self.clock()

        def free(doc: dict | None) -> bool:
            if doc and rev_num(doc.get("takeover")) > rev_num(self.revision) and doc.get("holder") == self.holder:
                return False
            return doc is None or doc.get("holder") in (self.holder, None) or float(doc.get("expires_at", 0)) < now

        self.held = self.store.update_if("world", "lease", free, {"holder": self.holder, "revision": self.revision,
                                                                   "expires_at": now + self.expiry_s,
                                                                   "renewed_at": now, "takeover": None})
        return self.held

    renew = acquire

    def request_takeover(self) -> bool:
        """Ask an older-revision holder to hand over (it checkpoints and releases on its next renew)."""
        doc = self.store.get("world", "lease")
        if not doc or not doc.get("holder") or rev_num(doc.get("revision")) >= rev_num(self.revision):
            return False
        return self.store.update_if("world", "lease", lambda d: d is not None and d.get("holder") == doc["holder"],
                                    {**doc, "takeover": self.revision})

    def handoff_requested(self) -> bool:
        """True when a newer revision asked us to hand over."""
        doc = self.store.get("world", "lease") or {}
        return doc.get("holder") == self.holder and rev_num(doc.get("takeover")) > rev_num(self.revision)

    def release(self) -> None:
        """Give the lease up (on shutdown/handoff) so a successor can start at once."""
        self.store.update_if("world", "lease", lambda d: d is not None and d.get("holder") == self.holder,
                             {"holder": None, "revision": None, "expires_at": 0, "renewed_at": self.clock(),
                              "takeover": None})
        self.held = False
