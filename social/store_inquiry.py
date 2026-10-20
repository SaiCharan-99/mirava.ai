"""Store inquiry, turn by turn (T-03): customer think → decide → speak; salesperson sees ONLY the spoken transcript."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from media.screen import wrap
from mind.context import build
from mind.decision import DecisionAdapter
from mind.memory import EventHook, MemoryStore
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.memory import MemoryEntry
from shared.schemas.social import Message
from shared.store import DocStore
from social.conversation import Outcome

PROMPTS = Path(__file__).resolve().parents[1] / "shared" / "prompts"
MAX_PER_PERSON = 6
TOPICS = ("battery", "camera", "price", "display", "performance", "warranty", "general")


def _p(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


class Candidate(BaseModel):
    """One thing the customer could do next, with the line they would say if they chose it."""

    text: str
    kind: Literal["ask", "share", "leave", "buy", "think_about_it"]
    say: str = ""


class CustomerThink(BaseModel):
    """Private thought + candidates (store_thought)."""

    thought: str
    candidates: list[Candidate] = Field(max_length=4)
    withhold: list[str] = Field(default_factory=list, max_length=3)


class ToolCall(BaseModel):
    """A salesperson tool use (recorded in the private note; results are pre-fetched into one briefing)."""

    tool: Literal["product_facts", "stock", "offers"]
    topic: Literal["battery", "camera", "price", "display", "performance", "warranty", "general"] = "general"


class SalesReply(BaseModel):
    """Salesperson's private note + the spoken reply (one call per turn)."""

    note: str
    text: str


class InquiryDebrief(BaseModel):
    """Customer's private debrief after the visit."""

    reaction: str
    questions: list[str]
    topics: list[str]
    answered: list[bool]
    satisfaction: float = Field(ge=0, le=1)
    outcome: Literal["left", "think_about_it", "buy", "referred_online"]
    attitude_delta: float = Field(ge=-0.5, le=0.5)
    summary: str
    importance: int = Field(ge=1, le=10)


@dataclass
class Customer:
    """Customer side (private agenda stays here)."""

    agent_id: int
    name: str
    style: str
    now: str
    agenda: list[str]


@dataclass
class Salesperson:
    """Salesperson side: persona + tools data (facts, stock, offers). Never any customer-private data."""

    agent_id: int
    name: str
    style: str
    store_id: str
    store_name: str
    product_id: str | None
    product_name: str
    facts: dict[str, str] = field(default_factory=dict)
    stock: dict[str, int] = field(default_factory=dict)
    offers: list[str] = field(default_factory=list)

    def call(self, c: ToolCall) -> str:
        """Run one tool."""
        if c.tool == "stock":
            n = self.stock.get(self.product_id or "", 0)
            return f"stock: {self.product_name} {n} units" + ("" if n else " (out of stock; baseline phones available)")
        if c.tool == "offers":
            return "offers: " + ("; ".join(self.offers) or "none today")
        return f"product_facts({c.topic}): " + self.facts.get(c.topic, self.facts.get("general", "no data"))


def product_facts(product: dict[str, Any]) -> dict[str, str]:
    """Per-topic facts for the salesperson tool, from the product document only."""
    feats = [str(f) for f in product.get("features", [])]
    claims = [str(c) for c in product.get("claims", [])]

    def pick(*keys: str) -> str:
        hits = [x for x in feats + claims if any(k in x.lower() for k in keys)]
        return "; ".join(hits[:3]) if hits else "no specific data; see general features"

    price = f"₹{int(product.get('price_inr', 0)):,}" + (f", launch offer: {product['launch_offer']}"
                                                         if product.get("launch_offer") else "")
    return {"battery": pick("battery", "mah", "charg"), "camera": pick("camera", "mp", "photo", "video"),
            "price": price, "display": pick("display", "screen", "amoled", "hz"),
            "performance": pick("processor", "chip", "ram", "gaming", "fast"),
            "warranty": "1-year manufacturer warranty (simulated store policy)",
            "general": f"{product.get('brand', '')} {product.get('name', '')}: " + "; ".join(feats[:5]) + f"; {price}"}


def topics_in(text: str) -> list[str]:
    """Inquiry topics mentioned in free text (keyword rules); order of TOPICS, general excluded."""
    low = text.lower()
    keys = {"battery": ("battery", "mah", "charg"), "camera": ("camera", "photo", "mp", "video", "selfie"),
            "price": ("price", "cost", "emi", "budget", "expensive", "cheap", "discount", "afford", "₹"),
            "display": ("display", "screen", "amoled", "hz"), "performance": ("fast", "speed", "gaming", "lag", "chip", "ram"),
            "warranty": ("warranty", "guarantee", "service")}
    return [t for t, ks in keys.items() if any(k in low for k in ks)]


def briefing(sales: Salesperson, msgs: list[Message]) -> tuple[str, list[ToolCall]]:
    """Pre-fetched tool results for one salesperson turn: general facts, stock, offers and every topic the customer
    has SAID out loud so far (never the private agenda)."""
    spoken = " ".join(m.text for m in msgs if m.speaker != sales.agent_id)
    topics = topics_in(spoken)[:3]
    calls = [ToolCall(tool="product_facts", topic="general"), ToolCall(tool="stock"), ToolCall(tool="offers"),
             *(ToolCall(tool="product_facts", topic=t) for t in topics)]  # type: ignore[arg-type]
    return "\n".join(sales.call(c) for c in calls), calls


def choose_candidate(cands: list[Candidate], turn: int, withhold: list[str], seed: str) -> Candidate:
    """Local, deterministic choice of the next move (no model call): asks first, wrapping up as the visit goes on,
    never volunteering something the customer decided to withhold."""
    base = {"ask": 0.9 if turn < 3 else 0.45, "share": 0.5, "buy": 0.25 + 0.1 * turn,
            "think_about_it": 0.2 + 0.12 * turn, "leave": 0.1 + 0.12 * turn}

    def score(c: Candidate) -> float:
        n = int(hashlib.sha256(f"{seed}|{turn}|{c.text}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
        hidden = any(w and w.lower() in c.text.lower() for w in withhold)
        return base.get(c.kind, 0.3) * (0.1 if hidden else 1.0) * (0.85 + 0.3 * n)

    return max(cands, key=score)


def transcript_text(msgs: list[Message], names: dict[int, str]) -> str:
    """Public transcript lines."""
    return "\n".join(f"{names.get(m.speaker, m.speaker)}: {m.text}" for m in msgs) or "(nothing said yet)"


async def run_inquiry(sid: str, cust: Customer, sales: Salesperson, t: int, *, store: DocStore, llm: LLMClient,
                      decider: DecisionAdapter, on_event: EventHook | None = None) -> Outcome:
    """Run the visit; returns event specs (store_thought / salesperson_thought private, message, inquiry)."""
    out = Outcome(sid, minutes=20)
    names = {cust.agent_id: cust.name, sales.agent_id: sales.name}
    ctx = await build(cust.agent_id, "store_inquiry", f"{sales.product_name} {' '.join(cust.agenda)}",
                      f"In {sales.store_name} asking about {sales.product_name}.", store=store, llm=llm,
                      now=cust.now, now_t=t)
    msgs: list[Message] = []
    n_c = n_s = 0
    seq = 0
    agenda = "\n".join(f"- {q}" for q in cust.agenda) or "- is it worth it for me?"
    ended = "left"
    while n_c < MAX_PER_PERSON:
        # salesperson greets / answers (sees the spoken transcript only): ONE call with pre-fetched tool results
        if n_s < MAX_PER_PERSON and (not msgs or msgs[-1].speaker == cust.agent_id):
            tools_text, calls = briefing(sales, msgs)
            fill = {"{name}": sales.name, "{store}": sales.store_name, "{style}": sales.style,
                    "{product}": sales.product_name, "{transcript}": transcript_text(msgs, names),
                    "{tools}": tools_text}
            pr = _p("salesperson_reply")
            for k, v in fill.items():
                pr = pr.replace(k, v)
            rep = await llm.generate(MODEL_LITE, pr, SalesReply, purpose="salesperson_reply", reasoning="low",
                                     max_tokens=180, priority_class="P0")
            out.cost_usd += rep.usage.cost_usd
            m = Message(session_id=sid, seq=seq, speaker=sales.agent_id, listener=cust.agent_id,
                        text=rep.data.text.strip()[:300], t=t)
            msgs.append(m)
            out.messages.append(m)
            out.ev("message", sales.agent_id, {"seq": seq, "speaker": sales.agent_id, "listener": cust.agent_id,
                                               "text": m.text, "conv_kind": "store", "store_id": sales.store_id},
                   other_id=cust.agent_id)
            out.ev("salesperson_thought", sales.agent_id, {"seq": seq, "note": rep.data.note[:300],
                                                           "tools": [c.model_dump() for c in calls],
                                                           "store_id": sales.store_id})
            seq += 1
            n_s += 1
        # customer: ONE call (think + candidate lines, private) → local choice → speak the chosen line
        tr = transcript_text(msgs, names)
        pt = (_p("store_think").replace("{store}", sales.store_name).replace("{product}", sales.product_name)
              .replace("{style}", cust.style).replace("{context}", ctx.render())
              .replace("{agenda}", wrap(agenda, "agenda")).replace("{transcript}", tr))
        th = await llm.generate(MODEL_LITE, pt, CustomerThink, purpose="store_think", reasoning="low",
                                max_tokens=420, priority_class="P0")
        out.cost_usd += th.usage.cost_usd
        cands = [c for c in th.data.candidates if c.text.strip()] or [Candidate(
            text="I'll think about it.", kind="think_about_it", say="Let me think about it and come back.")]
        if n_c >= 2 and not any(c.kind in ("leave", "think_about_it", "buy") for c in cands):
            cands.append(Candidate(text="I'll think about it and come back.", kind="think_about_it",
                                   say="Let me think about it and come back."))
        chosen = choose_candidate(cands, n_c, th.data.withhold, f"{cust.agent_id}|{t}")
        out.ev("store_thought", cust.agent_id, {"seq": seq, "thought": th.data.thought[:400],
                                                "candidates": [c.model_dump() for c in cands],
                                                "decision": {"speak": True, "chosen": chosen.model_dump(),
                                                             "withheld": th.data.withhold},
                                                "store_id": sales.store_id, "product_id": sales.product_id})
        m = Message(session_id=sid, seq=seq, speaker=cust.agent_id, listener=sales.agent_id,
                    text=(chosen.say.strip() or chosen.text.strip())[:300], t=t)
        msgs.append(m)
        out.messages.append(m)
        out.ev("message", cust.agent_id, {"seq": seq, "speaker": cust.agent_id, "listener": sales.agent_id,
                                          "text": m.text, "conv_kind": "store", "store_id": sales.store_id},
               other_id=sales.agent_id)
        seq += 1
        n_c += 1
        if chosen.kind in ("leave", "buy", "think_about_it"):
            ended = {"leave": "left", "buy": "buy", "think_about_it": "think_about_it"}[chosen.kind]
            break
    # private debrief
    pd = (_p("inquiry_debrief").replace("{store}", sales.store_name).replace("{product}", sales.product_name)
          .replace("{context}", ctx.render()).replace("{agenda}", wrap(agenda, "agenda"))
          .replace("{transcript}", transcript_text(msgs, names)))
    db = await llm.generate(MODEL_LITE, pd, InquiryDebrief, purpose="inquiry_debrief", reasoning="low",
                            max_tokens=320, priority_class="P0")
    out.cost_usd += db.usage.cost_usd
    d = db.data
    asked = [m.text for m in msgs if m.speaker == cust.agent_id and "?" in m.text] or d.questions[:4]
    answered = (list(d.answered) + [True] * len(asked))[:len(asked)]
    outcome = d.outcome if d.outcome != "left" or ended == "left" else ended
    if sales.store_id == "ST-SHOPKART" and outcome == "left":
        outcome = "referred_online"
    out.ev("inquiry", cust.agent_id, {"session_id": sid, "agent_id": cust.agent_id, "store_id": sales.store_id,
                                      "product_id": sales.product_id, "questions": asked,
                                      "topics": [x[:30] for x in d.topics][:4] or ["general"],
                                      "answered": answered, "satisfaction": round(d.satisfaction, 2),
                                      "outcome": outcome, "n_messages": len(msgs)},
           other_id=sales.agent_id)
    subject = f"product:{sales.product_id}" if sales.product_id else "category:phone"
    out.ev("debrief", cust.agent_id, {"conv_kind": "store", "reaction": d.reaction[:300], "summary": d.summary[:400],
                                      "belief_deltas": [{"subject": subject, "attitude_delta": d.attitude_delta}],
                                      "intents": [outcome], "importance": int(d.importance)})
    ms = MemoryStore(cust.agent_id, store, llm, on_event)
    await ms.add(MemoryEntry(mid=f"inq-{sid}-{cust.agent_id}", agent_id=cust.agent_id, t=t, kind="inquiry",
                             text=d.summary[:400], importance=int(d.importance),
                             source={"channel": "store", "session_id": sid, "product_id": sales.product_id,
                                     "person_id": sales.agent_id},
                             entities=[sales.product_name, sales.store_name], event_refs=[]))
    out.rendered = True
    out.minutes = max(8, 2 * len(msgs))
    return out
