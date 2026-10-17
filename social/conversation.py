"""One conversation end to end: prep (private ×2) → dialogue (public) → debrief (private ×2), or unrendered."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from mind.decision import DecisionAdapter
from mind.memory import MemoryStore
from shared.llm import LLMClient
from shared.schemas.memory import MemoryEntry
from shared.schemas.social import Conversation, Message
from shared.store import DocStore
from social.debrief import debrief
from social.dialogue import write_dialogue
from social.gate import GateResult
from social.prep import prep

MAX_SOCIAL, MAX_STRANGER = 10, 4


@dataclass
class Participant:
    """Public facts about one participant used to set up the chat."""

    agent_id: int
    name: str
    style: str
    now: str = ""


@dataclass
class Outcome:
    """Everything the engine must emit when the conversation's result is applied."""

    session_id: str
    events: list[dict[str, Any]] = field(default_factory=list)   # {kind, agent_id, other_id, payload, private?}
    texts: list[dict[str, Any]] = field(default_factory=list)    # texts rows (embedding filled in)
    messages: list[Message] = field(default_factory=list)
    cost_usd: float = 0.0
    minutes: int = 3
    rendered: bool = True

    def ev(self, kind: str, agent_id: int | None, payload: dict[str, Any], other_id: int | None = None) -> None:
        """Queue one event spec."""
        self.events.append({"kind": kind, "agent_id": agent_id, "other_id": other_id, "payload": payload})

    def text(self, kind: str, agent_id: int, text: str, private: bool, t: int) -> None:
        """Queue one texts row."""
        self.texts.append({"kind": kind, "agent_id": agent_id, "session_id": self.session_id, "private": private,
                           "text": text, "t": t})


async def unrendered(sid: str, a: Participant, b: Participant, g: GateResult, t: int, store: DocStore) -> Outcome:
    """T-07: interaction event + template memory for each side (no model call)."""
    o = Outcome(sid, rendered=False, minutes=5)
    topic = g.topics[0] if g.topics else "small talk"
    o.ev("interaction", a.agent_id, {"topic": topic, "minutes": o.minutes, "conv_kind": g.kind}, b.agent_id)
    for me, other in ((a, b), (b, a)):
        await MemoryStore(me.agent_id, store).add(MemoryEntry(
            mid=f"int-{sid}-{me.agent_id}", agent_id=me.agent_id, t=t, kind="conversation",
            text=f"Chatted briefly with {other.name} about {topic}.", importance=2,
            source={"channel": "conversation", "person_id": other.agent_id, "session_id": sid},
            entities=[other.name], event_refs=[]))
    return o


async def run_conversation(sid: str, a: Participant, b: Participant, g: GateResult, relationship: str,
                           closeness: float, place: str, t: int, *, store: DocStore, llm: LLMClient,
                           decider: DecisionAdapter) -> Outcome:
    """Rendered 3-step conversation; each private step only ever sees its own agent's context."""
    o = Outcome(sid)
    stranger = g.kind == "stranger"
    names = {a.agent_id: a.name, b.agent_id: b.name}
    pc = g.priority_class
    (pa, ca, ka), (pb, cb, kb) = await asyncio.gather(
        prep(a.agent_id, sid, b.name, relationship, closeness, place, g.topics, store=store, llm=llm,
             decider=decider, now=a.now, now_t=t, stranger=stranger, priority_class=pc),
        prep(b.agent_id, sid, a.name, relationship, closeness, place, g.topics, store=store, llm=llm,
             decider=decider, now=b.now, now_t=t, stranger=stranger, priority_class=pc))
    o.cost_usd += ka + kb
    for plan, cands in ((pa, ca), (pb, cb)):
        o.ev("share_plan", plan.agent_id, {**plan.model_dump(), "candidates": [c.model_dump() for c in cands]})
        o.text("share_plan", plan.agent_id, " | ".join(c.text for c in cands), True, t)
    msgs, out, kd, model = await write_dialogue(pa, pb, {a.agent_id: a.style, b.agent_id: b.style}, relationship,
                                                place, MAX_STRANGER if stranger else MAX_SOCIAL, llm=llm, t=t,
                                                product=g.product is not None, priority_class=pc)
    o.cost_usd += kd
    o.messages = msgs
    o.minutes = max(2, (len(msgs) + 1) // 2)
    for m in msgs:
        o.ev("message", m.speaker, {"seq": m.seq, "speaker": m.speaker, "listener": m.listener, "text": m.text,
                                     "conv_kind": g.kind}, m.listener)
        o.text("message", m.speaker, m.text, False, t)
    products = list(dict.fromkeys(out.product_mentions + ([g.product] if g.product else [])))
    conv = Conversation(session_id=sid, participants=[a.agent_id, b.agent_id], place_id=place, kind=g.kind,
                        t_start=t, t_end=t + o.minutes, topics=out.topics or g.topics, product_mentions=products,
                        n_messages=len(msgs), rendered=True, model=model)
    o.ev("conversation", a.agent_id, conv.model_dump(), b.agent_id)
    sink: list[tuple[int, str, dict]] = []

    def hook_for(aid: int):  # noqa: ANN202 — tiny closure factory
        return lambda kind, payload: sink.append((aid, kind, payload))

    t_end = t + o.minutes
    (da, xa), (db, xb) = await asyncio.gather(
        debrief(a.agent_id, b.agent_id, b.name, msgs, names, t_end, store=store, llm=llm, now=a.now,
                product_ids=products, on_event=hook_for(a.agent_id), priority_class=pc),
        debrief(b.agent_id, a.agent_id, a.name, msgs, names, t_end, store=store, llm=llm, now=b.now,
                product_ids=products, on_event=hook_for(b.agent_id), priority_class=pc))
    o.cost_usd += xa + xb
    for aid, d in ((a.agent_id, da), (b.agent_id, db)):
        o.ev("debrief", aid, d.model_dump())
        o.text("debrief", aid, f"{d.reaction} {d.summary}", True, t_end)
        o.ev("memory_write", aid, {"mid": f"conv-{sid}-{aid}", "kind": "conversation", "importance": d.importance})
    for aid, kind, payload in sink:
        o.ev(kind, aid, payload)
    return o
