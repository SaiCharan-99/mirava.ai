"""Agenda: what is on each person's mind to tell people (phase 2a).

An item is created by something that happened to the agent (a phone broke, a hoarding caught their eye, a purchase, a
store visit, a plan from a debrief). Items decay, expire and are marked `told` per listener. Only the short
`public_hint` tag is visible to the encounter gate; the model never reads the agenda directly — rules turn it into
topics, and the private prompts of the agent turn it into words.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MAX_ITEMS = 8
DAY = 1440
DECAY = 0.85
DROP_BELOW = 0.1
KINDS = ("phone_trouble", "product_noticed", "purchase", "opinion", "store_visit", "wants_to_tell", "life_news",
         "errand_question", "survey_invite", "got_goodies")
WEIGHT = {"phone_trouble": 0.8, "product_noticed": 0.45, "purchase": 0.9, "opinion": 0.3, "store_visit": 0.6,
          "wants_to_tell": 0.7, "life_news": 0.5, "errand_question": 0.8, "survey_invite": 0.6, "got_goodies": 0.6}
LIFE_DAYS = {"purchase": 7, "phone_trouble": 5, "errand_question": 10}


@dataclass
class AgendaItem:
    """One thing someone wants to bring up."""

    kind: str
    weight: float
    created_t: int
    expires_t: int
    public_hint: str = ""
    product_id: str | None = None
    target_id: int | None = None          # only worth telling this person (e.g. "tell Ravi")
    about: str = ""                       # short factual note used to word it (never another person's private text)
    told: list[int] = field(default_factory=list)


class Agenda:
    """Per-agent lists of items (≤ 8, strongest kept)."""

    def __init__(self) -> None:
        self.items: dict[int, list[AgendaItem]] = {}

    def add(self, aid: int, kind: str, t: int, *, hint: str = "", product_id: str | None = None,
            target_id: int | None = None, about: str = "", weight: float | None = None) -> AgendaItem:
        """Add or refresh an item (same kind + product + target refreshes the weight instead of duplicating)."""
        w = max(0.0, min(1.0, WEIGHT.get(kind, 0.4) if weight is None else weight))
        lst = self.items.setdefault(aid, [])
        for it in lst:
            if it.kind == kind and it.product_id == product_id and it.target_id == target_id:
                it.weight = max(it.weight, w)
                it.created_t, it.expires_t = t, t + LIFE_DAYS.get(kind, 3) * DAY
                it.about = about or it.about
                it.public_hint = hint or it.public_hint
                return it
        it = AgendaItem(kind, w, t, t + LIFE_DAYS.get(kind, 3) * DAY, hint, product_id, target_id, about)
        lst.append(it)
        lst.sort(key=lambda x: -x.weight)
        del lst[MAX_ITEMS:]
        return it

    def top(self, aid: int, n: int = 3, listener: int | None = None, t: int | None = None) -> list[AgendaItem]:
        """Strongest live items, optionally only those the listener has not heard and that are not aimed at someone else."""
        out = []
        for it in sorted(self.items.get(aid, []), key=lambda x: -x.weight):
            if t is not None and t >= it.expires_t:
                continue
            if listener is not None and (listener in it.told or (it.target_id is not None and it.target_id != listener)):
                continue
            out.append(it)
        return out[:n]

    def pick_to_tell(self, aid: int, listener: int, t: int) -> AgendaItem | None:
        """The item this person would bring up with this listener (strongest first), or None."""
        got = self.top(aid, 1, listener, t)
        return got[0] if got else None

    def hints(self, aid: int, n: int = 3, t: int | None = None) -> list[str]:
        """Public hint tags of the strongest items (what the gate may see)."""
        return list(dict.fromkeys(i.public_hint for i in self.top(aid, n + 2, None, t) if i.public_hint))[:n]

    def product_ids(self, aid: int, t: int | None = None) -> list[str]:
        """Products on this person's mind (strongest first)."""
        return list(dict.fromkeys(i.product_id for i in self.top(aid, MAX_ITEMS, None, t) if i.product_id))[:3]

    def nightly(self, t: int) -> None:
        """Decay weights, drop weak or expired items."""
        for aid in list(self.items):
            keep = []
            for it in self.items[aid]:
                it.weight *= DECAY
                if it.weight >= DROP_BELOW and t < it.expires_t:
                    keep.append(it)
            if keep:
                self.items[aid] = keep
            else:
                del self.items[aid]

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        return {str(a): [asdict(i) for i in lst] for a, lst in self.items.items()}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict."""
        self.items = {int(a): [AgendaItem(**i) for i in lst] for a, lst in (d or {}).items()}
