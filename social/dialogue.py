"""Shared dialogue writer (T-02 step 2). Accepts ONLY public inputs: two SharePlans, styles, relationship, place."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from shared.llm import LLMClient
from shared.models import MODEL_FLASH, MODEL_LITE
from shared.schemas.social import Message, SharePlan
from social.turns import near_duplicate

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "dialogue.md"


class _Line(BaseModel):
    speaker: Literal["A", "B"]
    text: str


class DialogueOut(BaseModel):
    """Structured dialogue output."""

    messages: list[_Line]
    topics: list[str]
    product_mentions: list[str]


def _plan_block(p: SharePlan) -> str:
    """Public view of a share plan (never anything else)."""
    return json.dumps({"opening": p.opening, "points_to_share": p.points_to_share,
                       "questions_to_ask": p.questions_to_ask, "tone": p.tone}, ensure_ascii=False)


async def write_dialogue(a: SharePlan, b: SharePlan, styles: dict[int, str], relationship: str, place: str,
                         max_per_person: int = 10, *, llm: LLMClient, t: int = 0, product: bool = False,
                         priority_class: str = "P3") -> tuple[list[Message], DialogueOut, float, str]:
    """Write the conversation; returns (messages, raw output, cost, model). Greeting first, ≤ max per person."""
    for p in (a, b):
        if type(p) is not SharePlan:
            raise TypeError("write_dialogue accepts only SharePlan objects")
    if a.session_id != b.session_id:
        raise ValueError("share plans belong to different sessions")
    model = MODEL_FLASH if product else MODEL_LITE
    prompt = (PROMPT.read_text(encoding="utf-8").replace("{max_per_person}", str(max_per_person))
              .replace("{relationship}", relationship).replace("{place}", place)
              .replace("{style_a}", styles.get(a.agent_id, "")).replace("{style_b}", styles.get(b.agent_id, ""))
              .replace("{plan_a}", _plan_block(a)).replace("{plan_b}", _plan_block(b)))
    res = await llm.generate(model, prompt, DialogueOut, purpose="conv_dialogue", reasoning="low",
                             max_tokens=120 * max_per_person, priority_class=priority_class)
    out: DialogueOut = res.data
    lines = [(ln.speaker, ln.text.strip()) for ln in out.messages if ln.text.strip()]
    if not lines or lines[0][0] != "A":
        lines.insert(0, ("A", a.opening))
    else:
        lines[0] = ("A", lines[0][1])
    if not any(s == "B" for s, _ in lines):
        lines.append(("B", b.opening))
    ids = {"A": a.agent_id, "B": b.agent_id}
    count = {"A": 0, "B": 0}
    msgs: list[Message] = []
    said: list[str] = []
    for s, text in lines:
        if said and near_duplicate(text, said):
            continue                                  # drop a repeated line instead of publishing it again
        if msgs and msgs[-1].speaker == ids[s]:       # strict alternation: a speaker's run is one message
            prev = msgs[-1]
            msgs[-1] = prev.model_copy(update={"text": f"{prev.text} {text}"[:300]})
            said.append(text)
            continue
        if count[s] >= max_per_person:
            break                                     # the next speaker is out of turns: the talk ends here
        count[s] += 1
        said.append(text)
        other = "B" if s == "A" else "A"
        msgs.append(Message(session_id=a.session_id, seq=len(msgs), speaker=ids[s], listener=ids[other], text=text,
                            t=t + len(msgs) // 2))
    if len(msgs) < 2:                                 # everything after the greeting was a repeat: B still answers
        msgs.append(Message(session_id=a.session_id, seq=len(msgs), speaker=b.agent_id, listener=a.agent_id,
                            text=b.opening.strip()[:300] or "Hi!", t=t))
    return msgs, out, res.usage.cost_usd, model
