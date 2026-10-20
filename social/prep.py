"""Private prep (T-02 step 1): own context → candidate thoughts → decision model → SharePlan."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mind.context import build
from mind.decision import DecisionAdapter, DecisionRequest
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.social import SharePlan
from shared.store import DocStore

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "prep.md"
STRANGER_TAGS = {"opinion", "question"}


def clean_tone(tone: str) -> str:
    """One short word only, so the free-text tone field can never smuggle private context into the dialogue."""
    word = "".join(ch for ch in (tone.split() or ["friendly"])[0] if ch.isalpha())[:20].lower()
    return word or "friendly"


class Candidate(BaseModel):
    """One thing this agent might say."""

    text: str
    tag: Literal["opinion", "question", "personal", "sensitive"]


class PrepOut(BaseModel):
    """Structured prep output."""

    opening: str
    candidates: list[Candidate]
    tone: str


async def prep(agent_id: int, session_id: str, other_name: str, relationship: str, closeness: float, place: str,
               topics: list[str], *, store: DocStore, llm: LLMClient, decider: DecisionAdapter, now: str = "",
               now_t: int | None = None, stranger: bool = False, priority_class: str = "P3", opinions: str = "",
               mind: str = "", visible: str = "", stance: str = "") -> tuple[SharePlan, list[Candidate], float]:
    """Return this agent's SharePlan, its private candidates and the model cost."""
    if place == "WhatsApp":
        situation = f"I'm texting {other_name} ({relationship}) on WhatsApp. Possible topics: {', '.join(topics)}."
    else:
        situation = f"I just ran into {other_name} ({relationship}) at {place}. Possible topics: {', '.join(topics)}."
    ctx = await build(agent_id, "prep", f"{other_name} {' '.join(topics)}", situation, store=store, llm=llm,
                      now=now, now_t=now_t, opinions=opinions)
    prompt = (PROMPT.read_text(encoding="utf-8").replace("{context}", ctx.render()).replace("{situation}", situation)
              .replace("{mind}", mind or "(nothing in particular)").replace("{visible}", visible or "(nothing notable)")
              .replace("{stance}", stance or "(none)"))
    res = await llm.generate(MODEL_LITE, prompt, PrepOut, purpose="conv_prep", reasoning="low", max_tokens=350,
                             priority_class=priority_class)
    out: PrepOut = res.data
    cands = list({c.text: c for c in out.candidates if c.text.strip()}.values())
    if stranger:
        cands = [c for c in cands if c.tag in STRANGER_TAGS]
    doc = store.get("agents", str(agent_id)) or {}
    disclosure = ((doc.get("profile") or {}).get("persona") or {}).get("disclosure", {})
    dec = await decider.decide(DecisionRequest(
        agent_id=agent_id, kind="share", options=[c.text for c in cands] or ["(nothing)"],
        context={"closeness": 0.1 if stranger else closeness, "disclosure": disclosure,
                 "tags": {c.text: c.tag for c in cands}, "mood": now, "other": other_name}))
    chosen = set(dec.chosen()[: (1 if stranger else 4)])
    plan = SharePlan(session_id=session_id, agent_id=agent_id, opening=out.opening.strip()[:160] or "Hi!",
                     points_to_share=[c.text for c in cands if c.text in chosen and c.tag != "question"],
                     questions_to_ask=[c.text for c in cands if c.text in chosen and c.tag == "question"],
                     tone=clean_tone(out.tone), withheld_count=sum(c.text not in chosen for c in cands))
    return plan, cands, res.usage.cost_usd
