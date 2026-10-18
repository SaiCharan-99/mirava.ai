"""Survey session runner (addendum B4): per table, per question — moderator, private prestance, discussion (floor
model + think → decide → speak), absorption (rules + embeddings), private ballots, debrief texts.

Returns a timeline of items {dt, kind, agent_id, payload, live?, text?}; the engine releases them at sim time
start + dt (one writer). Offline (fake backend) and over budget, deterministic human-like rules stand in for the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.rng import stream
from media.screen import wrap
from mind.decision import DecisionAdapter, DecisionRequest
from shared.llm import FakeGemini, LLMClient
from shared.models import MODEL_LITE
from shared.schemas.survey import HeardItem, PreStance, Question, SurveyAnswer

PROMPTS = Path(__file__).resolve().parents[2] / "shared" / "prompts"
EMO = ("love", "hate", "never", "always", "terrible", "amazing", "worst", "best", "honestly", "!", "seriously", "scam")


def _p(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


@dataclass
class Person:
    """Public + own-private facts of one participant (built by the engine from its own state)."""

    agent_id: int
    name: str
    age: int
    occupation: str
    income_band: str
    big5: dict[str, float]
    style: str
    card: str                      # persona card (own prompt only)
    phone: str                     # e.g. "Vivo budget, 6.1 years, battery_weak"
    attitude: float = 0.0          # attitude to the survey product (−1..1)
    experience: str | None = None  # "purchased" | "store_visit" | None — lived experience with the product
    memories: list[str] = field(default_factory=list)   # own top memories for the topic


@dataclass
class Budget:
    """Interactive money left for this session (ballots always run, discussion is skipped when out)."""

    left: float
    spent: float = 0.0

    def take(self, usd: float) -> None:
        """Book a cost."""
        self.spent += usd
        self.left -= usd


# ---------------------------------------------------------------- model schemas
class PreOut(BaseModel):
    """Private first answer."""

    choice: int = Field(0, description="index into the numbered options (single), or scale value")
    choices: list[int] = Field(default_factory=list, description="indexes for multi-select")
    text: str = Field("", description="open answer (≤ 60 words)")
    confidence: float = Field(0.5, ge=0, le=1)
    gut_reason: str = ""


class ThinkOut(BaseModel):
    """Speaker's private thought + what they could say."""

    thought: str
    candidates: list[str] = Field(default_factory=list, max_length=3)


class DecideOut(BaseModel):
    """Private speaking decision."""

    speak: bool = True
    stance: int = Field(0, description="option index (or scale value) they will express out loud")
    withheld: str = ""
    address_to: str = ""
    tone: Literal["agree", "disagree", "ask", "joke", "share_experience", "neutral"] = "neutral"


class Utter(BaseModel):
    """One spoken line."""

    text: str


class BallotOut(BaseModel):
    """Private ballot."""

    choice: int = 0
    choices: list[int] = Field(default_factory=list)
    text: str = ""
    confidence: float = Field(0.6, ge=0, le=1)
    reason: str = ""
    influence_type: Literal["persuaded", "conformed", "reinforced", "unchanged", "reacted_against"] = "unchanged"
    influenced_by: list[str] = Field(default_factory=list)
    effort: Literal["careful", "satisficed"] = "careful"


# ---------------------------------------------------------------- helpers
def options_view(q: Question, order: list[int]) -> str:
    """Numbered options in the agent's own (shuffled) order, or scale anchors."""
    if q.type in ("single", "multi"):
        return "\n".join(f"{k}. {q.options[i]}" for k, i in enumerate(order))  # type: ignore[index]
    if q.type == "scale":
        s = q.scale
        assert s is not None
        return f"Scale {s.min}–{s.max} ({s.min} = {s.low_label or 'low'}, {s.max} = {s.high_label or 'high'})"
    return "Open answer, ≤ 60 words."


def order_for(q: Question, aid: int, seed: int, survey_id: str) -> list[int]:
    """Seeded per-agent option order (avoids order bias)."""
    n = len(q.options or [])
    if not n:
        return []
    rng = stream(seed, "opt_order", survey_id, q.question_id, aid)
    return [int(x) for x in rng.permutation(n)]


def to_answer(q: Question, choice: int, choices: list[int], text: str, order: list[int]) -> Any:
    """Model output (indexes in the agent's order) → a valid answer."""
    if q.type == "single":
        k = max(0, min(len(order) - 1, int(choice)))
        return q.options[order[k]]  # type: ignore[index]
    if q.type == "multi":
        idx = [max(0, min(len(order) - 1, int(c))) for c in (choices or [choice])]
        vals = list(dict.fromkeys(q.options[order[i]] for i in idx))  # type: ignore[index]
        return vals[: q.max_select or 1] or [q.options[order[0]]]  # type: ignore[index]
    if q.type == "scale":
        s = q.scale
        assert s is not None
        return max(s.min, min(s.max, int(choice)))
    words = (text or "No strong view.").split()
    return " ".join(words[:60])


def key(ans: Any) -> str:
    """Comparable key of an answer."""
    if isinstance(ans, list):
        return "|".join(sorted(ans))
    return str(ans)


def bucket(q: Question, ans: Any) -> str:
    """Category used for majority / shift (open answers → 'answered')."""
    if q.type == "open":
        return "answered"
    if q.type == "scale":
        s = q.scale
        assert s is not None
        mid = (s.min + s.max) / 2
        return "high" if ans > mid else "low" if ans < mid else "mid"
    return key(ans)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity."""
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def susceptibility(p: Person, confidence: float, minority: bool, w: dict[str, float]) -> float:
    """Conformity susceptibility = f(A↑, N↑, confidence↓, minority, O↓)."""
    b = p.big5
    v = (w["agreeableness"] * float(b.get("A", 0.5)) + w["neuroticism"] * float(b.get("N", 0.5))
         + w["low_confidence"] * (1 - confidence) + (w["minority"] if minority else 0.0)
         + w["openness"] * float(b.get("O", 0.5)))
    return round(max(0.0, min(1.0, v)), 3)


# ---------------------------------------------------------------- the runner
class TableRunner:
    """Runs one table through all questions; produces the timeline and the answers."""

    def __init__(self, survey: dict[str, Any], table_id: str, session_id: str, people: list[Person], *,
                 llm: LLMClient, decider: DecisionAdapter, cfg: dict[str, Any], seed: int, budget: Budget,
                 product_name: str = "") -> None:
        self.s, self.table_id, self.session_id, self.people = survey, table_id, session_id, people
        self.by_id = {p.agent_id: p for p in people}
        self.llm, self.decider, self.cfg, self.seed, self.budget = llm, decider, cfg, seed, budget
        self.offline = isinstance(llm, FakeGemini)
        self.product = product_name or survey.get("topic", "")
        self.items: list[dict[str, Any]] = []
        self.answers: list[SurveyAnswer] = []
        self.prestances: dict[tuple[int, str], PreStance] = {}
        self.spoken = dict.fromkeys(self.by_id, 0)
        self.public_stance: dict[tuple[int, str], str] = {}
        self.said: dict[int, list[str]] = {p.agent_id: [] for p in people}
        self.retained: dict[int, list[str]] = {p.agent_id: [] for p in people}
        self.prompts: list[tuple[str, int | str, str]] = []      # (purpose, owner, prompt) — for isolation tests
        self.cost = 0.0
        self.skipped_discussion = False
        self.dt = 0.0

    # -- llm wrapper (books cost, keeps prompts for tests)
    async def _gen(self, purpose: str, owner: int | str, prompt: str, schema: type[BaseModel], max_tokens: int) -> Any:
        self.prompts.append((purpose, owner, prompt))
        res = await self.llm.generate(MODEL_LITE, prompt, schema, purpose=purpose, reasoning="low",
                                      max_tokens=max_tokens, priority_class="interactive")
        self.cost += res.usage.cost_usd
        self.budget.take(res.usage.cost_usd)
        return res.data

    def _emit(self, kind: str, agent_id: int | None, payload: dict[str, Any], *, live: dict[str, Any] | None = None,
              text: tuple[str, str, bool] | None = None, step: float = 0.5) -> None:
        self.dt += step
        self.items.append({"dt": round(self.dt, 2), "kind": kind, "agent_id": agent_id,
                           "payload": {"survey_id": self.s["survey_id"], "table_id": self.table_id, **payload},
                           "session_id": self.session_id, "live": live, "text": text})

    def _msg(self, q: Question, seq: int, speaker: int | str, text: str, addressed: int | None = None,
             reply_to: str | None = None) -> str:
        mid = f"{self.s['survey_id']}:{self.table_id}:{q.question_id}:{seq}"
        listener = addressed if addressed is not None else -1
        self._emit("message", speaker if isinstance(speaker, int) else None,
                   {"seq": seq, "speaker": speaker, "listener": listener, "text": text, "conv_kind": "focus_group",
                    "question_id": q.question_id, "message_id": mid, "addressed_to": addressed, "reply_to": reply_to},
                   live={"type": "survey_msg", "survey_id": self.s["survey_id"], "table_id": self.table_id,
                         "message_id": mid, "speaker": speaker, "text": text, "seq": seq},
                   text=("message", text, False), step=1.0)
        return mid

    # -- moderator (public inputs only)
    async def _moderator(self, q: Question, transcript: list[tuple[str, str]], purpose: str, invite: str = "") -> str:
        if self.offline or self.budget.left <= 0:
            if purpose == "open":
                opts = f" Options: {', '.join(q.options)}." if q.options else ""
                return f"Next question: {q.text}{opts} Take a moment, then let's hear a few views."
            if purpose == "invite":
                return f"{invite}, we haven't heard from you yet — what do you think?"
            return "Thanks, everyone. Let's capture your own answer privately on the tablet."
        pr = (_p("survey_moderator").replace("{question}", q.text)
              .replace("{options}", ", ".join(q.options or []) or (options_view(q, []) if q.type == "scale" else "open"))
              .replace("{purpose}", purpose).replace("{invite}", invite)
              .replace("{transcript}", wrap("\n".join(f"{a}: {b}" for a, b in transcript[-10:]) or "(none)", "transcript")))
        out = await self._gen("survey_moderator", "moderator", pr, Utter, 90)
        return out.text.strip()[:280] or "Let's continue."

    # -- prestance (private)
    async def _prestance(self, p: Person, q: Question, qi: int) -> PreStance:
        order = order_for(q, p.agent_id, self.seed, self.s["survey_id"])
        rng = stream(self.seed, "pre", self.s["survey_id"], q.question_id, p.agent_id)
        if self.offline:
            choice, conf = self._rule_choice(p, q, order, rng)
            ans = to_answer(q, choice, [choice], f"{p.memories[0] if p.memories else 'It depends on the price.'}"[:200], order)
            reason = self._rule_reason(p, q, ans)
        else:
            pr = (_p("survey_prestance").replace("{me}", self._me(p)).replace("{question}", wrap(q.text, "question"))
                  .replace("{options}", options_view(q, order)))
            out = await self._gen("survey_prestance", p.agent_id, pr, PreOut, 160)
            ans = to_answer(q, out.choice, out.choices, out.text, order)
            conf, reason = float(out.confidence), out.gut_reason[:200]
        ps = PreStance(agent_id=p.agent_id, question_id=q.question_id, answer=ans, confidence=round(conf, 2),
                       gut_reason=reason)
        self.prestances[(p.agent_id, q.question_id)] = ps
        self._emit("survey_prestance", p.agent_id, ps.model_dump(), text=None, step=0.1)
        return ps

    def _me(self, p: Person) -> str:
        mem = "\n".join(f"- {m}" for m in p.memories[:6]) or "- (nothing specific)"
        b5 = ", ".join(f"{k} {v:.1f}" for k, v in sorted(p.big5.items()))
        exp = f"\nLived experience with the product: {p.experience}." if p.experience else ""
        return (f"{p.card}\nBig Five: {b5}\nPhone: {p.phone}\nAttitude to {self.product}: {p.attitude:+.2f}{exp}\n"
                f"My memories:\n{mem}")

    def _rule_choice(self, p: Person, q: Question, order: list[int], rng: Any) -> tuple[int, float]:
        """Deterministic first answer from attitude, experience and noise (index in the agent's order)."""
        a = p.attitude + (0.4 if p.experience == "purchased" else 0.15 if p.experience == "store_visit" else 0.0)
        conf = min(0.95, 0.35 + 0.5 * abs(a) + (0.2 if p.experience else 0.0) + 0.1 * float(rng.random()))
        if q.type == "scale":
            s = q.scale
            assert s is not None
            v = s.min + (a + 1) / 2 * (s.max - s.min) + float(rng.normal(0, 0.6))
            return int(round(max(s.min, min(s.max, v)))), conf
        if q.type in ("single", "multi"):
            n = len(order)
            # option position by attitude (first options = more positive in authoring order), then map to agent order
            target = int(round((1 - (a + 1) / 2) * (n - 1) + float(rng.normal(0, 0.7))))
            target = max(0, min(n - 1, target))
            return order.index(target), conf
        return 0, conf

    def _rule_reason(self, p: Person, q: Question, ans: Any) -> str:
        if p.experience == "purchased":
            return "I already bought it, so I know how it really is."
        if p.experience == "store_visit":
            return "I asked about it in the store myself."
        return (p.memories[0][:120] if p.memories else f"My phone is {p.phone.split(',')[1].strip()} old.")

    # -- discussion
    async def _discuss(self, q: Question, qi: int, seq0: int) -> tuple[list[dict[str, Any]], int]:
        """Floor model + think → decide → speak; returns the public messages heard by everyone at the table."""
        cfgf = self.cfg["floor"]
        rng = stream(self.seed, "floor", self.s["survey_id"], self.table_id, q.question_id)
        lo, hi = self.cfg["turns_per_question"]
        n_turns = int(rng.integers(lo, hi + 1))
        cap = int(self.cfg["messages_per_person"])
        msgs: list[dict[str, Any]] = []
        transcript: list[tuple[str, str]] = []
        seq = seq0
        text = await self._moderator(q, transcript, "open")
        mid = self._msg(q, seq, "moderator", text)
        msgs.append({"message_id": mid, "speaker": "moderator", "text": text, "stance": None})
        transcript.append(("Moderator", text))
        seq += 1
        last: int | None = None
        addressed: int | None = None
        invited: int | None = None
        no_new = 0
        for turn in range(n_turns):
            if self.budget.left <= 0 and not self.offline:
                self.skipped_discussion = True
                break
            stances = {a: s for (a, qq), s in self.public_stance.items() if qq == q.question_id}
            props = {}
            for p in self.people:
                if self.spoken[p.agent_id] >= cap:
                    continue
                pre = self.prestances[(p.agent_id, q.question_id)]
                dis = 1.0 if last is not None and stances.get(last) not in (None, bucket(q, pre.answer)) else 0.0
                v = (cfgf["extraversion"] * float(p.big5.get("E", 0.5)) + cfgf["confidence"] * pre.confidence
                     + cfgf["stake"] * (1.0 if p.experience else 0.0) + cfgf["disagreement"] * dis
                     + cfgf["addressed"] * (1.0 if addressed == p.agent_id else 0.0)
                     + cfgf["invited"] * (1.0 if invited == p.agent_id else 0.0)
                     - cfgf["spoken_penalty"] * self.spoken[p.agent_id]
                     - cfgf["fatigue"] * qi / max(1, len(self.s["questions"]))
                     + cfgf["noise"] * float(rng.normal()))
                if p.agent_id == last:
                    v -= 2.0
                props[p.agent_id] = v
            if not props:
                break
            spk = max(sorted(props), key=lambda a: props[a])
            invited = None
            sp = self.by_id[spk]
            line, stance = await self._turn(sp, q, qi, msgs)
            if line is None:
                no_new += 1
                if no_new >= 2:
                    break
                continue
            addr = next((o.agent_id for o in self.people if o.agent_id != spk and o.name in line), None)
            mid = self._msg(q, seq, spk, line, addressed=addr, reply_to=msgs[-1]["message_id"] if msgs else None)
            msgs.append({"message_id": mid, "speaker": spk, "text": line, "stance": stance})
            transcript.append((sp.name, line))
            self.public_stance[(spk, q.question_id)] = stance
            self.said[spk].append(line)
            self.spoken[spk] += 1
            seq += 1
            last, addressed = spk, addr
            if turn % 4 == 3:                              # moderator invites the quietest person
                quiet = min(sorted(self.by_id), key=lambda a: (self.spoken[a], a))
                if self.spoken[quiet] == 0 and quiet != spk:
                    text = await self._moderator(q, transcript, "invite", self.by_id[quiet].name)
                    mid = self._msg(q, seq, "moderator", text, addressed=quiet)
                    msgs.append({"message_id": mid, "speaker": "moderator", "text": text, "stance": None})
                    transcript.append(("Moderator", text))
                    seq += 1
                    invited = quiet
            vals = set(stances.values())
            if turn >= lo and len(vals) == 1 and len(stances) >= len(self.people) - 1:
                break                                      # convergence
        text = await self._moderator(q, transcript, "wrap")
        mid = self._msg(q, seq, "moderator", text)
        msgs.append({"message_id": mid, "speaker": "moderator", "text": text, "stance": None})
        return msgs, seq + 1

    async def _turn(self, p: Person, q: Question, qi: int, msgs: list[dict[str, Any]]) -> tuple[str | None, str]:
        """think (private) → decide (private) → speak (public) for one speaker."""
        pre = self.prestances[(p.agent_id, q.question_id)]
        heard = self._heard_lines(p.agent_id, msgs)
        order = order_for(q, p.agent_id, self.seed, self.s["survey_id"])
        own = bucket(q, pre.answer)
        if self.offline:
            rng = stream(self.seed, "turn", self.s["survey_id"], q.question_id, p.agent_id, len(msgs))
            stances = [m["stance"] for m in msgs if m["stance"] is not None]
            maj = max(sorted(set(stances)), key=stances.count) if stances else own
            express = maj if (maj != own and float(p.big5.get("A", 0.5)) > 0.7 and pre.confidence < 0.5
                              and rng.random() < 0.5) else own
            thought = f"Privately I'm at {key(pre.answer)}. {pre.gut_reason}"
            tone = "share_experience" if p.experience else ("disagree" if stances and maj != own else "agree")
            dec = {"speak": True, "stance": express, "withheld": "" if express == own else "my real view",
                   "address_to": "", "tone": tone}
            line = (f"{'From my own experience, ' if p.experience else ''}{pre.gut_reason} "
                    f"{'I agree with what was said.' if tone == 'agree' else 'I see it differently.' if tone == 'disagree' else ''}"
                    ).strip()[:240]
        else:
            pt = (_p("survey_think").replace("{me}", self._me(p)).replace("{question}", wrap(q.text, "question"))
                  .replace("{options}", options_view(q, order)).replace("{prestance}", f"{key(pre.answer)} — {pre.gut_reason}")
                  .replace("{heard}", wrap(heard or "(nothing yet)", "heard")))
            th = await self._gen("survey_think", p.agent_id, pt, ThinkOut, 160)
            thought = th.thought[:300]
            cands = [c for c in th.candidates if c.strip()] or [pre.gut_reason or "I'm not sure yet."]
            r = await self.decider.decide(DecisionRequest(agent_id=p.agent_id, kind="speak",
                                                          options=[*cands, "(stay quiet)"],
                                                          context={"persona": p.card, "thought": thought,
                                                                   "spoken": self.spoken[p.agent_id]}))
            pick = r.choice if r.choice in cands else ("" if r.choice == "(stay quiet)" else cands[0])
            if not pick:
                self._emit("survey_thought", p.agent_id, {"question_id": q.question_id, "text": thought},
                           text=("survey_thought", thought, True), step=0.2)
                self._emit("survey_decision", p.agent_id, {"question_id": q.question_id, "speak": False, "stance": own,
                                                           "withheld": "chose to stay quiet"}, step=0.1)
                return None, own
            express = own
            dec = {"speak": True, "stance": express, "withheld": "", "address_to": "", "tone": "neutral"}
            ps = (_p("survey_speak").replace("{style}", p.style).replace("{item}", pick)
                  .replace("{heard}", wrap(heard or "(nothing yet)", "heard")))
            ut = await self._gen("survey_speak", p.agent_id, ps, Utter, 90)
            line = " ".join(ut.text.split()[:40])
        self._emit("survey_thought", p.agent_id, {"question_id": q.question_id, "text": thought},
                   text=("survey_thought", thought, True), step=0.2)
        self._emit("survey_decision", p.agent_id, {"question_id": q.question_id, **dec}, step=0.1)
        return line, str(dec["stance"])

    def _heard_lines(self, aid: int, msgs: list[dict[str, Any]]) -> str:
        """The speaker's OWN retained messages so far (not the full transcript)."""
        keep = set(self.retained.get(aid, []))
        recent = msgs[-2:]                                  # what was just said is in working memory
        lines = [m for m in msgs if m["message_id"] in keep or m in recent]
        return "\n".join(f"{self._label(m['speaker'])}: {m['text']}" for m in lines[-8:])

    def _label(self, sp: int | str) -> str:
        return "Moderator" if sp == "moderator" else self.by_id[int(sp)].name

    # -- absorption (rules + embeddings, no per-listener model call)
    async def _absorb(self, q: Question, qi: int, msgs: list[dict[str, Any]]) -> dict[int, list[HeardItem]]:
        w = self.cfg["absorption"]
        k_lo, k_hi = self.cfg["heard_k"]
        talk = [m for m in msgs if m["speaker"] != "moderator"]
        if not talk:
            return {p.agent_id: [] for p in self.people}
        concerns = [f"{self.prestances[(p.agent_id, q.question_id)].gut_reason} {' '.join(p.memories[:2])}"
                    for p in self.people]
        vecs = await self.llm.embed([m["text"] for m in talk] + concerns)
        mv, cv = vecs[: len(talk)], vecs[len(talk):]
        out: dict[int, list[HeardItem]] = {}
        for li, p in enumerate(self.people):
            pre = self.prestances[(p.agent_id, q.question_id)]
            own = bucket(q, pre.answer)
            scored = []
            for mi, m in enumerate(talk):
                if m["speaker"] == p.agent_id:
                    continue
                spk = self.by_id[int(m["speaker"])]
                rel = max(0.0, cosine(mv[mi], cv[li]))
                homo = (1.0 if spk.income_band == p.income_band else 0.0) * 0.4 + max(0.0, 1 - abs(spk.age - p.age) / 30) * 0.3
                cred = min(1.0, homo + (0.5 if spk.experience else 0.0))
                emo = min(1.0, sum(m["text"].lower().count(x) for x in EMO) / 3)
                nov = 0.0 if any(m["text"][:40].lower() in mm.lower() for mm in p.memories) else 1.0
                agree = m["stance"] == own
                cons = 1.0 if agree else (0.6 if cred > 0.7 else 0.2)
                pos = mi / max(1, len(talk) - 1)
                prim = max(1 - pos, pos)
                sal = (w["relevance"] * rel + w["credibility"] * cred + w["emotion"] * emo + w["novelty"] * nov
                       + w["consistency"] * cons + w["primacy_recency"] * prim)
                why = [n for n, v in (("relevance", rel > 0.5), ("credibility", cred > 0.6), ("emotion", emo > 0.3),
                                      ("novelty", nov > 0.5), ("agreement", agree), ("disagreement", not agree),
                                      ("primacy", pos < 0.2), ("recency", pos > 0.8)) if v]
                scored.append(HeardItem(message_id=m["message_id"], salience=round(max(0.0, min(1.0, sal)), 3),
                                        why=why or ["recency"]))
            c = float(p.big5.get("C", 0.5))
            fatigue = qi / max(1, len(self.s["questions"]))
            k = int(round(k_lo + (k_hi - k_lo) * max(0.0, min(1.0, c - 0.4 * fatigue))))
            top = sorted(scored, key=lambda h: (-h.salience, h.message_id))[:k]
            out[p.agent_id] = top
            self.retained[p.agent_id] = [h.message_id for h in top]
            gist = (f"Most of my table leaned {self._majority(q)}; " if talk else "") + \
                   (f"{self._label(next(m['speaker'] for m in talk if m['message_id'] == top[0].message_id))}'s point stuck "
                    "with me." if top else "Nothing much stuck.")
            self._emit("survey_heard", p.agent_id, {"question_id": q.question_id,
                                                    "items": [h.model_dump() for h in top], "gist": gist}, step=0.05)
        return out

    def _majority(self, q: Question) -> str:
        st = [s for (a, qq), s in self.public_stance.items() if qq == q.question_id]
        return max(sorted(set(st)), key=st.count) if st else "nowhere in particular"

    # -- ballot (private, one per agent per question)
    async def _ballot(self, p: Person, q: Question, qi: int, heard: list[HeardItem], msgs: list[dict[str, Any]],
                      written: bool) -> SurveyAnswer:
        order = order_for(q, p.agent_id, self.seed, self.s["survey_id"])
        pre = self.prestances.get((p.agent_id, q.question_id))
        own = bucket(q, pre.answer) if pre else None
        st = [s for (a, qq), s in self.public_stance.items() if qq == q.question_id and a != p.agent_id]
        maj = max(sorted(set(st)), key=st.count) if st else None
        share = (st.count(maj) / len(st)) if (st and maj) else 0.0
        minority = bool(maj and own and maj != own and share >= 0.5)
        sus = susceptibility(p, pre.confidence if pre else 0.5, minority, self.cfg["conformity"])
        text_by = {m["message_id"]: m for m in msgs}
        rng = stream(self.seed, "ballot", self.s["survey_id"], q.question_id, p.agent_id)
        if self.offline or self.budget.left <= 0:
            ans, conf, reason, infl, by, effort = self._rule_ballot(p, q, qi, pre, heard, text_by, maj, sus, order,
                                                                    rng, written)
        else:
            hl = "\n".join(f"[{h.message_id}] {self._label(text_by[h.message_id]['speaker'])}: "
                           f"{text_by[h.message_id]['text']}" for h in heard if h.message_id in text_by)
            pr = (_p("survey_ballot").replace("{me}", self._me(p)).replace("{question}", wrap(q.text, "question"))
                  .replace("{options}", options_view(q, order))
                  .replace("{prestance}", f"{key(pre.answer)} (confidence {pre.confidence:.1f}) — {pre.gut_reason}"
                           if pre else "(written survey: answer directly)")
                  .replace("{heard}", wrap(hl or "(no discussion)", "heard"))
                  .replace("{social}", f"Table majority leaned: {maj} ({share:.0%}); my conformity susceptibility "
                                       f"{sus:.2f}" if maj else "No clear majority.")
                  .replace("{position}", f"question {qi + 1} of {len(self.s['questions'])}"))
            out = await self._gen("survey_ballot", p.agent_id, pr, BallotOut, 220)
            ans = to_answer(q, out.choice, out.choices, out.text, order)
            conf, reason, infl, effort = float(out.confidence), out.reason, out.influence_type, out.effort
            by = [m for m in out.influenced_by if m in {h.message_id for h in heard}]
        if not q.valid(ans):
            ans = to_answer(q, 0, [0], "No strong view.", order)
        changed = bool(pre) and key(ans) != key(pre.answer)
        if not changed and infl in ("persuaded", "conformed"):
            infl = "reinforced" if by else "unchanged"
        if changed and infl in ("unchanged", "reinforced"):
            infl = "persuaded" if by else "reacted_against"
        spoken = self.public_stance.get((p.agent_id, q.question_id))
        gap = spoken is not None and spoken != bucket(q, ans)
        a = SurveyAnswer(agent_id=p.agent_id, question_id=q.question_id, answer=ans, confidence=round(conf, 2),
                         reason=" ".join(reason.split()[:40]) or "It just fits me.", changed_from_prestance=changed,
                         influence_type=infl, influenced_by=by, public_private_gap=gap, effort=effort)
        self.answers.append(a)
        txt = f"{a.reason}" + (f" Answer: {a.answer}" if q.type == "open" else "")
        self._emit("survey_answer", p.agent_id, {**a.model_dump(), "majority": maj, "susceptibility": sus,
                                                 "prestance": pre.answer if pre else None,
                                                 "written": written},
                   live={"type": "survey_ballot", "survey_id": self.s["survey_id"], "agent_id": p.agent_id,
                         "question_id": q.question_id, "done": True,
                         **({"note": a.reason[:120]} if written else {})},
                   text=("survey_answer", txt, False), step=0.25 if written else 0.1)
        return a

    def _rule_ballot(self, p: Person, q: Question, qi: int, pre: PreStance | None, heard: list[HeardItem],
                     text_by: dict[str, dict[str, Any]], maj: str | None, sus: float, order: list[int], rng: Any,
                     written: bool) -> tuple[Any, float, str, str, list[str], str]:
        """Human-like deterministic ballot: experience dominates, credible points persuade, susceptible minorities
        conform, contrarians react against, low-C / late questions satisfice."""
        if pre is None:                                   # written survey: the first answer is the answer
            choice, conf = self._rule_choice(p, q, order, rng)
            ans = to_answer(q, choice, [choice], self._rule_reason(p, q, None), order)
            pre = PreStance(agent_id=p.agent_id, question_id=q.question_id, answer=ans, confidence=conf,
                            gut_reason=self._rule_reason(p, q, ans))
        c = float(p.big5.get("C", 0.5))
        satisfice = c < 0.35 and qi >= 1 or (qi >= 3 and rng.random() < 0.5)
        ans, conf, infl, by = pre.answer, pre.confidence, "unchanged", []
        reason = pre.gut_reason
        agree_heard = [h for h in heard if text_by.get(h.message_id, {}).get("stance") == bucket(q, pre.answer)]
        if agree_heard:
            infl, by = "reinforced", [agree_heard[0].message_id]
        if p.experience is None and q.type != "open":
            strong = [h for h in heard if h.salience >= 0.62 and "credibility" in h.why and "disagreement" in h.why]
            contrarian = float(p.big5.get("A", 0.5)) < 0.3 and float(p.big5.get("O", 0.5)) > 0.6
            if maj and maj != bucket(q, pre.answer) and sus >= 0.55 and rng.random() < sus:
                ans, infl, by = self._toward(q, maj, pre.answer, order), "conformed", [h.message_id for h in heard
                                                                                      if text_by.get(h.message_id, {}).get("stance") == maj][:2]
                reason = f"Most people here felt {maj}; I suppose they have a point."
            elif strong and rng.random() < 0.5:
                st = text_by[strong[0].message_id]["stance"]
                ans, infl, by = self._toward(q, st, pre.answer, order), "persuaded", [strong[0].message_id]
                reason = f"{self._label(text_by[strong[0].message_id]['speaker'])}'s point changed my mind."
            elif contrarian and maj and maj == bucket(q, pre.answer) and rng.random() < 0.3:
                ans, infl, by = self._away(q, pre.answer, order), "reacted_against", [heard[0].message_id] if heard else []
                reason = "Everyone agreeing so fast made me doubt it."
        if satisfice and q.type in ("single", "scale") and infl == "unchanged":
            if q.type == "scale":
                s = q.scale
                assert s is not None
                ans = (s.min + s.max) // 2
            else:
                ans = q.options[order[0]]  # type: ignore[index]
            reason = "Fine, that one."
            return ans, 0.4, reason, "unchanged", [], "satisficed"
        if infl in ("persuaded", "conformed", "reacted_against") and not by and heard:
            by = [heard[0].message_id]
        return ans, conf, reason[:200], infl, by, "satisficed" if satisfice else "careful"

    def _toward(self, q: Question, target_bucket: str, current: Any, order: list[int]) -> Any:
        if q.type == "scale":
            s = q.scale
            assert s is not None
            return s.max - 1 if target_bucket == "high" else s.min + 1 if target_bucket == "low" else (s.min + s.max) // 2
        if q.type == "single" and target_bucket in (q.options or []):
            return target_bucket
        return current

    def _away(self, q: Question, current: Any, order: list[int]) -> Any:
        if q.type == "scale":
            s = q.scale
            assert s is not None
            return s.min if int(current) > (s.min + s.max) / 2 else s.max
        if q.type == "single":
            return next((o for o in (q.options or []) if o != current), current)
        return current

    # -- whole table
    async def run(self) -> None:
        """All questions for this table."""
        qs = [Question.model_validate(x) for x in self.s["questions"]]
        focus = self.s["mode"] == "focus_group" and len(self.people) >= 2
        seq = 0
        for qi, q in enumerate(qs):
            self._emit("survey_phase", None, {"phase": "question", "question_id": q.question_id},
                       live={"type": "survey", "survey_id": self.s["survey_id"], "phase": "question",
                             "question_id": q.question_id}, step=0.5)
            if focus:
                for p in self.people:
                    await self._prestance(p, q, qi)
            msgs: list[dict[str, Any]] = []
            heard: dict[int, list[HeardItem]] = {p.agent_id: [] for p in self.people}
            if focus and q.discuss:
                self._emit("survey_phase", None, {"phase": "discussion", "question_id": q.question_id},
                           live={"type": "survey", "survey_id": self.s["survey_id"], "phase": "discussion",
                                 "question_id": q.question_id}, step=0.2)
                msgs, seq = await self._discuss(q, qi, seq)
                heard = await self._absorb(q, qi, msgs)
            elif focus:
                text = await self._moderator(q, [], "open")
                self._msg(q, seq, "moderator", text)
                seq += 1
            self._emit("survey_phase", None, {"phase": "ballot", "question_id": q.question_id},
                       live={"type": "survey", "survey_id": self.s["survey_id"], "phase": "ballot",
                             "question_id": q.question_id}, step=0.3)
            for p in self.people:
                await self._ballot(p, q, qi, heard[p.agent_id], msgs, written=not focus)
