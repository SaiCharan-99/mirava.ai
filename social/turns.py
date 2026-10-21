"""Turn-by-turn conversation (phase 2c): each speaker is a private call over THEIR OWN context, THEIR OWN share plan,
THEIR OWN stance and the spoken transcript so far — never the other person's plan or private context.

Used for product chats and for watched agents (the shared one-shot dialogue writer stays for everything else).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel

from mind.context import build
from shared.llm import LLMClient
from shared.models import MODEL_LITE
from shared.schemas.social import Message, SharePlan
from shared.store import DocStore

PROMPT = Path(__file__).resolve().parents[1] / "shared" / "prompts" / "turn.md"
CLOSE_HINT = "Wrap up now: answer anything left open in one short line, say a natural goodbye and set `done` to true."
FAREWELL = "Anyway, I should get going. Good talking to you!"
_WORD = re.compile(r"[a-z0-9']+")


def _norm(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def near_duplicate(text: str, earlier: list[str], threshold: float = 0.8) -> bool:
    """Is `text` (almost) a line already said? Word-overlap or character similarity at or above `threshold`."""
    w = _norm(text)
    if not w:
        return False
    for e in earlier:
        ew = _norm(e)
        if not ew:
            continue
        if w == ew:
            return True
        overlap = len(set(w) & set(ew)) / max(1, min(len(set(w)), len(set(ew))))
        if (overlap >= threshold and min(len(w), len(ew)) >= 4) or                 SequenceMatcher(None, " ".join(w), " ".join(ew)).ratio() >= threshold + 0.05:
            return True
    return False


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
    """A opens with their planned greeting, then B and A strictly alternate (one private call per line). A near-repeat
    is skipped and pushes toward a goodbye; a goodbye is answered, then the talk ends (or at the per-person limit).
    Returns (messages, topics/mentions, cost, model)."""
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
    min_each = min(2, max_per_person)                 # a greeting and a reply each before anyone may leave
    closing = False                                   # someone said goodbye or the talk started going in circles
    misses = 0                                        # consecutive turns without a new line from this speaker
    calls = 0

    def add(who: int, text: str) -> None:
        msgs.append(Message(session_id=a.session_id, seq=len(msgs), speaker=who, listener=other[who], text=text,
                            t=t + len(msgs) // 2))
        count[who] += 1

    # Strict alternation A, B, A, B…: the talk ends when the next speaker is at their limit or the goodbye is answered.
    while count[speaker] < max_per_person and calls < 3 * max_per_person + 4:
        transcript = "\n".join(f"{names[m.speaker]}: {m.text}" for m in msgs)
        wrap = closing or count[speaker] >= max_per_person - 1
        prompt = (tmpl.replace("{other}", names[other[speaker]]).replace("{relationship}", relationship)
                  .replace("{place}", place).replace("{style}", styles.get(speaker, ""))
                  .replace("{context}", ctx[speaker]).replace("{plan}", _plan_text(plans[speaker]))
                  .replace("{stance}", (stances or {}).get(speaker) or "(none)").replace("{transcript}", transcript)
                  .replace("{closing}", CLOSE_HINT if wrap else ""))
        try:
            res = await llm.generate(MODEL_LITE, prompt, TurnOut, purpose="conv_turn", reasoning="low",
                                     max_tokens=90, priority_class=priority_class)
        except Exception:
            if len(msgs) < 2:
                raise                                 # nothing worth keeping: the engine falls back
            break                                     # keep the transcript so far
        calls += 1
        cost += res.usage.cost_usd
        text = res.data.say.strip()[:300]
        if not text or near_duplicate(text, [m.text for m in msgs]):
            misses += 1                               # skip the repeat and push this speaker toward closing
            closing = True
            if misses < 2:
                continue
            misses = 0
            if count[speaker] == 0:                   # never got a line out: use their planned greeting
                add(speaker, plans[speaker].opening.strip()[:300] or "Hi!")
                speaker = other[speaker]
                continue
            if text:
                add(speaker, FAREWELL)                # still circling: close the chat for them
            break
        misses = 0
        was_closing = closing
        add(speaker, text)
        if res.data.done and min(count.values()) >= min_each:
            if was_closing and len(msgs) >= 3:
                break                                 # the goodbye was answered
            closing = True                            # let the other person answer the goodbye
        elif was_closing and res.data.done:
            break
        speaker = other[speaker]
    return msgs, TurnsOut(topics=topics[:4], product_mentions=list(product_ids)), cost, MODEL_LITE
