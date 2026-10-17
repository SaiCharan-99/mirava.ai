"""Encounter gate (T-01): rules → who → decision model {talk, topics} → priority → governor → rendered or not."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from mind.decision import DecisionAdapter, DecisionRequest

STRANGER_PLACES = {"shop", "store", "cafe", "bus_stop", "queue", "metro", "restaurant"}
PRODUCT_INTERESTS = {"phones", "tech", "gadgets", "photography", "gaming", "smartphones"}
EST_COST = {"social": 0.0016, "stranger": 0.0007, "product": 0.0030}


class Governor(Protocol):
    """The part of the budget governor the gate needs."""

    def allow(self, priority_class: str, est_cost_usd: float) -> bool: ...


@dataclass
class Side:
    """What the gate may know about one participant (no private text, only tags)."""

    agent_id: int
    interests: list[str]
    salient: list[str] = field(default_factory=list)          # topic tags from recent memories: "phone broke", …
    products_salient: list[str] = field(default_factory=list)  # product ids with recent notice / open question
    free: float = 0.5                                          # 0..1 free time right now
    watched: bool = False


@dataclass
class GateResult:
    """Gate decision (logged as a `gate` event)."""

    pair: tuple[int, int]
    talk: bool
    kind: Literal["social", "stranger"]
    topics: list[str]
    reason: str
    priority: float
    priority_class: str
    rendered: bool
    product: str | None = None

    def payload(self) -> dict[str, Any]:
        """`gate` event payload."""
        return {"pair": list(self.pair), "talk": self.talk, "topics": self.topics, "reason": self.reason,
                "priority": round(self.priority, 3), "priority_class": self.priority_class, "rendered": self.rendered,
                "conv_kind": self.kind}


def _interested(side: Side) -> bool:
    return any(i.lower() in PRODUCT_INTERESTS for i in side.interests)


def topics_for(a: Side, b: Side) -> tuple[list[str], str | None]:
    """Shared interests ∩ salient memories; product talk only if one side has it salient and the other cares."""
    shared = sorted({i.lower() for i in a.interests} & {i.lower() for i in b.interests})
    topics: list[str] = []
    product = None
    for x, y in ((a, b), (b, a)):
        for pid in x.products_salient:
            if product is None and (_interested(y) or set(shared) & PRODUCT_INTERESTS or pid in y.products_salient):
                product = pid
    if product:
        topics.append(f"product:{product}")
    for s in a.salient + b.salient:
        if any(w in s.lower() for w in shared) or s in a.salient and s in b.salient:
            topics.append(s)
    topics += shared
    topics += [s for s in a.salient[:1] + b.salient[:1]]
    out = list(dict.fromkeys(t for t in topics if t))[:4] or ["how the day is going"]
    return out, product


async def gate(a: Side, b: Side, relationship: dict | None, place_kind: str | None, t: int,
               decider: DecisionAdapter, governor: Governor) -> GateResult:
    """Decide whether and how a co-located pair talks (sessions/busy/co-location rules are checked by the caller)."""
    pair = (min(a.agent_id, b.agent_id), max(a.agent_id, b.agent_id))
    known = relationship is not None and relationship.get("kind") != "follower"
    if not known and (place_kind or "") not in STRANGER_PLACES:
        return GateResult(pair, False, "stranger", [], "strangers only talk in stores, queues, stops, cafés",
                          0.0, "P5", False)
    closeness = float(relationship["closeness"]) if known and relationship else 0.0
    free = min(a.free, b.free)
    p_talk = 0.15 + 0.6 * closeness * free if known else 0.12
    topics, product = topics_for(a, b)
    if not known:
        product = None
        topics = [x for x in topics if not x.startswith("product:")][:2]
    res = await decider.decide(DecisionRequest(agent_id=pair[0], kind="talk", options=["talk", "skip"],
                                               context={"pair": list(pair), "t": t, "p_talk": round(p_talk, 3),
                                                        "relationship": relationship, "place": place_kind,
                                                        "topics": topics}))
    kind: Literal["social", "stranger"] = "social" if known else "stranger"
    if res.choice != "talk":
        return GateResult(pair, False, kind, topics, f"skip ({res.reason})", 0.0, "P5", False, product)
    watched = a.watched or b.watched
    priority = 2.0 * (product is not None) + 1.0 * watched + closeness
    pclass = "P0" if watched else ("P2" if product else "P4")   # §17: P0 watched, P2 product chats, P4 social
    est = EST_COST["product" if product else kind]
    rendered = governor.allow(pclass, est)
    why = f"{'known' if known else 'stranger'} c={closeness:.2f} free={free:.2f}" + (f" product={product}" if product else "")
    return GateResult(pair, True, kind, topics, why, priority, pclass, rendered, product)
