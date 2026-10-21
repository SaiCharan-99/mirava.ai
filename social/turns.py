"""Turn-by-turn conversation (phase 2c): each speaker is a private call over THEIR OWN context, THEIR OWN share plan,
THEIR OWN stance and the spoken transcript so far — never the other person's plan or private context.

Used for product chats and for watched agents (the shared one-shot dialogue writer stays for everything else).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from mind.context import build
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.social import Message, SharePlan
from shared.store import DocStore

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "turn.md"


class TurnOut(BaseModel):
    """One spoken line."""

    say: str
    done: bool = False


@dataclass
class TurnsOut:
    """Same shape the engine reads from the one-shot writer."""

    topics: list[str] = field(default_factory=list)
    product_mentions: list[str] = field(default_factory=list)


def _plan_text(p: SharePlan) -> str:
    pts = "\n".join(f"- {x}" for x in p.points_to_share) or "- (nothing in particular)"
    qs = "\n".join(f"- ask: {x}" for x in p.questions_to_ask)
    return f"tone: {p.tone}\n{pts}" + (f"\n{qs}" if qs else "")


async def run_turns(a: SharePlan, b: SharePlan, names: dict[int, str], styles: dict[int, str], nows: dict[int, str],
                    relationship: str, place: str, max_per_person: int, *, store: DocStore, llm: LLMClient, t: int,
                    topics: list[str], product_ids: list[str], opinions: dict[int, str] | None = None,
                    stances: dict[int, str] | None = None, priority_class: str = "P3"
                    ) -> tuple[list[Message], TurnsOut, float, str]:
    """A opens with their planned greeting, then B and A alternate (one private call per line) until someone wraps up
    or both reach the limit. Returns (messages, topics/mentions, cost, model)."""
    for p in (a, b):
        if type(p) is not SharePlan:
            raise TypeError("run_turns accepts only SharePlan objects")
    if a.session_id != b.session_id:
        raise ValueError("share plans belong to different sessions")
    plans = {a.agent_id: a, b.agent_id: b}
    other = {a.agent_id: b.agent_id, b.agent_id: a.agent_id}
    ctx = {}
    for me in (a.agent_id, b.agent_id):
        c = await build(me, "turn", f"{names[other[me]]} {' '.join(topics)}", f"Talking with {names[other[me]]} at {place}.",
                        store=store, llm=llm, now=nows.get(me, ""), now_t=t, opinions=(opinions or {}).get(me, ""))
        ctx[me] = c.render()
    msgs = [Message(session_id=a.session_id, seq=0, speaker=a.agent_id, listener=b.agent_id,
                    text=a.opening.strip()[:300] or "Hi!", t=t)]
    count = {a.agent_id: 1, b.agent_id: 0}
    cost = 0.0
    speaker = b.agent_id
    tmpl = PROMPT.read_text(encoding="utf-8")
    calls = 0
    while any(c < max_per_person for c in count.values()) and len(msgs) < 2 * max_per_person \
            and calls < 4 * max_per_person + 4:                       # empty replies can never loop forever
        if count[speaker] >= max_per_person:
            speaker = other[speaker]
            continue
        transcript = "\n".join(f"{names[m.speaker]}: {m.text}" for m in msgs)
        prompt = (tmpl.replace("{other}", names[other[speaker]]).replace("{relationship}", relationship)
                  .replace("{place}", place).replace("{style}", styles.get(speaker, ""))
                  .replace("{context}", ctx[speaker]).replace("{plan}", _plan_text(plans[speaker]))
                  .replace("{stance}", (stances or {}).get(speaker) or "(none)").replace("{transcript}", transcript))
        res = await llm.generate(MODEL_LITE, prompt, TurnOut, purpose="conv_turn", reasoning="low", max_tokens=90,
                                 priority_class=priority_class)
        calls += 1
        cost += res.usage.cost_usd
        text = res.data.say.strip()[:300]
        if text and any(m.speaker == speaker and m.text.casefold() == text.casefold() for m in msgs):
            break  # do not publish a repeated question or loop over the same reply
        if text:
            msgs.append(Message(session_id=a.session_id, seq=len(msgs), speaker=speaker, listener=other[speaker],
                                text=text, t=t + len(msgs) // 2))
            count[speaker] += 1
        if res.data.done and count[b.agent_id] >= 1:
            break
        speaker = other[speaker]
    if count[b.agent_id] == 0:
        msgs.append(Message(session_id=a.session_id, seq=len(msgs), speaker=b.agent_id, listener=a.agent_id,
                            text=b.opening.strip()[:300] or "Hi!", t=t))
    return msgs, TurnsOut(topics=topics[:4], product_mentions=list(product_ids)), cost, MODEL_LITE
