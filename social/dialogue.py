"""Shared dialogue writer (T-02 step 2). Accepts ONLY public inputs: two SharePlans, styles, relationship, place."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from shared.llm import LLMClient
from shared.models import MODEL_FLASH, MODEL_LITE
from shared.schemas.social import Message, SharePlan

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
    for s, text in lines:
        if count[s] >= max_per_person:
            continue
        count[s] += 1
        other = "B" if s == "A" else "A"
        msgs.append(Message(session_id=a.session_id, seq=len(msgs), speaker=ids[s], listener=ids[other], text=text,
                            t=t + len(msgs) // 2))
    return msgs, out, res.usage.cost_usd, model
