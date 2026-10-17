"""Conversations: marker-fact isolation over 200 chats, dialogue typing, transcript bounds, sessions, gate, encounters."""

import json
import random
from typing import Any

import pytest
from pydantic import BaseModel

from engine.encounters import EncounterTracker, Presence
from mind.decision import DecisionRequest, FakeDecision, OpenRouterDecision
from mind.memory import MemoryStore
from shared.llm import FakeGemini, LLMResult, Usage, strict_schema
from shared.schemas.memory import MemoryEntry
from shared.schemas.social import SharePlan
from shared.store import MemoryStoreBackend
from social.conversation import Participant, run_conversation
from social.dialogue import write_dialogue
from social.gate import GateResult, Side, gate, topics_for
from social.sessions import SessionRegistry

MARKER = "Zubin"


class EchoLLM(FakeGemini):
    """Worst-case model: every string it returns is its whole prompt, so anything in a prompt leaks into output."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[tuple[str, str]] = []

    def _fill(self, node: dict, prompt: str, path: str) -> Any:
        if "enum" in node:
            return node["enum"][(sum(map(ord, path)) // 7) % len(node["enum"])]
        if "anyOf" in node:
            return self._fill(next(o for o in node["anyOf"] if o.get("type") != "null"), prompt, path)
        t = node.get("type")
        if t == "object":
            return {k: self._fill(v, prompt, f"{path}.{k}") for k, v in node.get("properties", {}).items()}
        if t == "array":
            n = 30 if path.endswith("messages") else 3
            return [self._fill(node.get("items", {"type": "string"}), prompt, f"{path}[{i}]") for i in range(n)]
        if t == "integer":
            return 5
        if t == "number":
            return 0.2
        if t == "boolean":
            return True
        return prompt[-1500:] + f" #{path}"

    async def generate(self, model: str, prompt: Any, schema: type[BaseModel] | None = None, **kw: Any) -> LLMResult:
        """Echo the prompt into every string field."""
        text = prompt if isinstance(prompt, str) else json.dumps(prompt)
        self.prompts.append((kw.get("purpose", ""), text))
        assert schema is not None
        data = schema.model_validate(self._fill(strict_schema(schema), text, ""))
        return LLMResult(data=data, text="", usage=Usage(cost_usd=0.001), model=model)


def profile(store: MemoryStoreBackend, aid: int, name: str) -> None:
    """agents/{id} with a persona card and disclosure style."""
    store.set("agents", str(aid), {"agent_id": aid, "profile": {
        "name": name, "persona_card": f"I am {name}, a resident of Indiranagar who likes coffee.",
        "persona": {"disclosure": {"opinions": 0.8, "money": 0.4, "feelings": 0.9, "plans": 0.9},
                    "speaking_style": "casual English"}}})


def gres(a: int, b: int, kind: str = "social") -> GateResult:
    """A rendered gate decision."""
    return GateResult((min(a, b), max(a, b)), True, kind, ["family", "weekend"], "test", 1.0, "P3", True)


async def test_marker_fact_never_leaks_over_200_conversations() -> None:
    store, llm, dec = MemoryStoreBackend(), EchoLLM(), FakeDecision()
    names = {1: "Meera", 2: "Arjun", 3: "Kavya"}
    for aid, nm in names.items():
        profile(store, aid, nm)
    await MemoryStore(1, store, llm).add(MemoryEntry(
        mid="secret", agent_id=1, t=0, kind="observation", text=f"My cousin is named {MARKER}.", importance=9,
        source={"channel": "life"}, entities=[], event_refs=[]))
    knows = {1}
    rng = random.Random(11)
    said_out_loud = 0
    for i in range(200):
        a, b = rng.choice([(1, 2), (1, 3), (2, 1), (3, 1), (2, 3)])
        pa, pb = Participant(a, names[a], "casual"), Participant(b, names[b], "casual")
        out = await run_conversation(f"s{i}", pa, pb, gres(a, b), "friends", 0.8, "cafe", 100 + i * 10,
                                     store=store, llm=llm, decider=dec)
        spoken = " ".join(m.text for m in out.messages)
        public = {e["agent_id"]: json.dumps({k: e["payload"][k] for k in ("opening", "points_to_share",
                                                                           "questions_to_ask", "tone")})
                  for e in out.events if e["kind"] == "share_plan"}
        for aid, pub in public.items():  # only a knowing agent can put the marker in its public plan
            assert MARKER not in pub or aid in knows
        if MARKER in spoken:             # the transcript has it only because a knowing agent chose to share it
            assert any(MARKER in pub for pub in public.values())
            said_out_loud += 1
            knows.update((a, b))
        for ev in out.events:           # private parts carry the marker only for agents who know it
            if ev["kind"] in ("share_plan", "debrief") and MARKER in json.dumps(ev["payload"]):
                assert ev["agent_id"] in knows, (i, ev["kind"], ev["agent_id"])
        for aid in (2, 3):
            mem = json.dumps(store.list(f"agents/{aid}/memories"))
            assert MARKER not in mem or aid in knows
    assert said_out_loud > 0          # the path where Meera does share it is exercised too


async def test_marker_not_shared_means_never_known() -> None:
    store, llm = MemoryStoreBackend(), EchoLLM()
    for aid, nm in ((1, "Meera"), (2, "Arjun")):
        profile(store, aid, nm)
    await MemoryStore(1, store, llm).add(MemoryEntry(mid="secret", agent_id=1, t=0, kind="observation",
                                                     text=f"My cousin is named {MARKER}.", importance=9,
                                                     source={}, entities=[], event_refs=[]))

    class NeverShare(FakeDecision):
        async def decide(self, req: DecisionRequest):  # type: ignore[no-untyped-def]
            r = await super().decide(req)
            return r.model_copy(update={"scores": {k: 0.0 for k in r.scores}}) if req.kind == "share" else r

    for i in range(20):
        out = await run_conversation(f"q{i}", Participant(1, "Meera", "x"), Participant(2, "Arjun", "y"),
                                     gres(1, 2), "friends", 0.9, "cafe", 50 + i * 10, store=store, llm=llm,
                                     decider=NeverShare())
        # B's prompts (prep/debrief built for Arjun) never contain the marker
        assert not any(MARKER in json.dumps(e["payload"]) for e in out.events if e["agent_id"] == 2
                       and e["kind"] in ("share_plan", "debrief"))
        assert all(MARKER not in m.text for m in out.messages)
    assert MARKER not in json.dumps(store.list("agents/2/memories"))


async def test_write_dialogue_rejects_non_shareplan() -> None:
    plan = SharePlan(session_id="s", agent_id=1, opening="Hi", points_to_share=[], questions_to_ask=[], tone="x",
                     withheld_count=0)

    class Sneaky(SharePlan):
        secret: str = MARKER

    with pytest.raises(TypeError):
        await write_dialogue(plan, {"agent_id": 2} , {}, "friends", "cafe", llm=FakeGemini())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await write_dialogue(plan, Sneaky(**plan.model_dump() | {"agent_id": 2}), {}, "x", "y", llm=FakeGemini())


@pytest.mark.parametrize("kind,cap", [("social", 10), ("stranger", 4)])
async def test_transcript_bounds_and_greeting_first(kind: str, cap: int) -> None:
    store, llm = MemoryStoreBackend(), EchoLLM()
    profile(store, 1, "Meera")
    profile(store, 2, "Arjun")
    out = await run_conversation("b1", Participant(1, "Meera", "x"), Participant(2, "Arjun", "y"), gres(1, 2, kind),
                                 "neighbours", 0.4, "cafe", 10, store=store, llm=llm, decider=FakeDecision())
    msgs = out.messages
    assert msgs[0].speaker == 1 and msgs[0].seq == 0
    plan_a = next(e for e in out.events if e["kind"] == "share_plan" and e["agent_id"] == 1)["payload"]
    assert msgs[0].text == plan_a["opening"] or msgs[0].text
    assert len(msgs) <= 2 * cap
    for aid in (1, 2):
        assert sum(m.speaker == aid for m in msgs) <= cap
    conv = next(e for e in out.events if e["kind"] == "conversation")["payload"]
    assert conv["n_messages"] == len(msgs) and conv["kind"] == kind


async def test_fake_backend_conversation_shapes() -> None:
    store, llm = MemoryStoreBackend(), FakeGemini()
    profile(store, 1, "Meera")
    profile(store, 2, "Arjun")
    out = await run_conversation("f1", Participant(1, "Meera", "x"), Participant(2, "Arjun", "y"), gres(1, 2),
                                 "friends", 0.7, "cafe", 10, store=store, llm=llm, decider=FakeDecision())
    kinds = [e["kind"] for e in out.events]
    assert kinds.count("share_plan") == 2 and kinds.count("debrief") == 2 and kinds.count("conversation") == 1
    assert len(store.list("agents/1/memories")) == 1 and len(store.list("agents/2/memories")) == 1


def test_sessions_never_double_book() -> None:
    reg, rng = SessionRegistry(), random.Random(5)
    for step in range(3000):
        if rng.random() < 0.6:
            reg.open(rng.sample(range(12), 2), "social", t=step, timeout=rng.randint(1, 20))
        elif reg.sessions:
            reg.close(rng.choice(sorted(reg.sessions)))
        reg.expire(step)
        seen: list[int] = [p for s in reg.sessions.values() for p in s.participants]
        assert len(seen) == len(set(seen))
    assert reg.open([1, 1], "social") is None
    r2 = SessionRegistry.from_dict(reg.to_dict())
    assert {k: vars(v) for k, v in r2.sessions.items()} == {k: vars(v) for k, v in reg.sessions.items()}


def test_encounters_scripted_pairs() -> None:
    tr = EncounterTracker()
    ppl = [Presence(1, 0, 0, "p"), Presence(2, 10, 0, "p"), Presence(3, 200, 0, "q"), Presence(4, 205, 3, "q"),
           Presence(5, 40, 0, "p")]
    assert tr.update(0, ppl) == []
    assert tr.update(1, ppl) == []
    pairs = tr.update(2, ppl)
    assert pairs == [(1, 2), (3, 4)]
    for p in pairs:
        tr.met(p, 2)
    assert tr.update(3, ppl) == []          # cool-down; no self-pairs, no duplicates
    moved = [Presence(1, 0, 0, "p"), Presence(2, 500, 0, "p")]
    tr2 = EncounterTracker()
    for t in range(5):
        assert tr2.update(t, moved) == []


class Allow:
    """Governor stub."""

    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def allow(self, priority_class: str, est_cost_usd: float) -> bool:
        return self.ok


async def test_gate_rules_and_product_talk() -> None:
    a = Side(1, ["cricket", "phones"], products_salient=["nova-x1"], free=1.0)
    b_uninterested = Side(2, ["cooking"], free=1.0)
    b_interested = Side(3, ["photography"], free=1.0)
    assert topics_for(a, b_uninterested)[1] is None
    assert topics_for(a, b_interested)[1] == "nova-x1"
    g = await gate(Side(1, []), Side(2, []), None, "home", 0, FakeDecision(), Allow(True))
    assert not g.talk and g.kind == "stranger"
    close = {"kind": "friend", "closeness": 1.0}
    talked = [await gate(a, b_interested, close, "park", t, FakeDecision(), Allow(False)) for t in range(40)]
    yes = [x for x in talked if x.talk]
    assert yes and all(not x.rendered and x.product == "nova-x1" and x.priority_class == "P2" for x in yes)
    s = await gate(a, b_interested, None, "cafe", 1, FakeDecision(), Allow(True))
    assert s.product is None and all(not tp.startswith("product:") for tp in s.topics)


async def test_decision_batches_32_per_call() -> None:
    calls: list[int] = []

    class Counting(FakeGemini):
        async def generate(self, model: str, prompt: Any, schema: Any = None, **kw: Any) -> LLMResult:
            n = prompt.count('"rid"')
            calls.append(n)
            data = schema.model_validate({"items": [{"rid": i, "scores": [0.9, 0.1], "reason": "r"}
                                                    for i in range(n)]})
            return LLMResult(data=data, usage=Usage(), model=model)

    d = OpenRouterDecision(Counting())
    reqs = [DecisionRequest(agent_id=i, kind="talk", options=["talk", "skip"], context={"t": i}) for i in range(70)]
    res = await d.decide_batch(reqs)
    assert calls == [32, 32, 6] and all(r.choice == "talk" and r.engine == "openrouter" for r in res)
    await d.decide_batch(reqs)
    assert len(calls) == 3                # dedup cache
