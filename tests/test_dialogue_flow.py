"""fix-C: conversations run several alternating turns, never repeat a line, and end naturally (fake LLM)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from shared.llm import FakeGemini, LLMResult, Usage
from shared.schemas.social import SharePlan
from shared.store import MemoryStoreBackend
from social.dialogue import DialogueOut, write_dialogue
from social.turns import TurnOut, near_duplicate, run_turns

NAMES = {1: "Meera", 2: "Arjun"}


def plans() -> tuple[SharePlan, SharePlan]:
    pa = SharePlan(session_id="s", agent_id=1, opening="Hi Arjun!", points_to_share=["new job"],
                   questions_to_ask=["how is your mother?"], tone="warm", withheld_count=0)
    pb = SharePlan(session_id="s", agent_id=2, opening="Hey Meera!", points_to_share=["trip to Mysuru"],
                   questions_to_ask=[], tone="warm", withheld_count=0)
    return pa, pb


class Scripted(FakeGemini):
    """Answers each turn from a per-speaker script (who speaks is read from the prompt)."""

    def __init__(self, lines: dict[str, list[tuple[str, bool]]]) -> None:
        super().__init__()
        self.lines = {k: list(v) for k, v in lines.items()}
        self.prompts: list[str] = []

    async def generate(self, model: str, prompt: Any, schema: type[BaseModel] | None = None, **kw: Any) -> LLMResult:
        assert schema is TurnOut
        self.prompts.append(prompt)
        me = "Meera" if "conversation with Arjun" in prompt else "Arjun"
        say, done = self.lines[me].pop(0) if self.lines[me] else ("", False)
        return LLMResult(data=TurnOut(say=say, done=done), text="", usage=Usage(cost_usd=0.0001), model=model)


async def _run(llm: Scripted, limit: int = 10):
    store = MemoryStoreBackend()
    pa, pb = plans()
    return await run_turns(pa, pb, NAMES, {}, {}, "friends", "a café", limit, store=store, llm=llm, t=0,
                           topics=["work"], product_ids=[])


def _alternates(msgs) -> bool:
    return all(x.speaker != y.speaker for x, y in zip(msgs, msgs[1:], strict=False))


async def test_multi_turn_chat_alternates_and_ends_on_an_answered_goodbye() -> None:
    llm = Scripted({
        "Arjun": [("Hey! Good to see you. Mum is better, thanks.", False), ("A new job? Congrats! Where?", False),
                  ("Nice. I just got back from Mysuru, loved it.", False), ("Bye, take care!", True)],
        "Meera": [("Thanks! It's at a design studio on 100 Feet Road.", False),
                  ("Mysuru! Did you see the palace lit up?", False), ("I have to run, see you soon!", True),
                  ("never said", False)]})
    msgs, _, cost, _ = await _run(llm)
    assert msgs[0].speaker == 1 and msgs[0].text == "Hi Arjun!"             # greeting first
    assert len(msgs) == 8 and _alternates(msgs)
    assert msgs[-1].text == "Bye, take care!"                                 # the goodbye was answered, then it ended
    assert [m.seq for m in msgs] == list(range(len(msgs))) and cost > 0


async def test_a_repeated_question_is_skipped_and_pushes_toward_closing() -> None:
    q = "So how is your mother doing these days?"
    llm = Scripted({
        "Arjun": [(q, False), ("so how is your mother doing these days", False), ("Okay, see you later!", True)],
        "Meera": [("She's fine, thanks for asking.", False), ("Bye then!", True)]})
    msgs, _, _, _ = await _run(llm)
    texts = [m.text for m in msgs]
    assert sum(near_duplicate(x, [q]) for x in texts) == 1                    # the repeat was never published
    assert _alternates(msgs)
    assert any("Wrap up now" in p for p in llm.prompts)                       # the repeat pushed toward a goodbye
    assert texts[-1] in ("Okay, see you later!", "Bye then!")


async def test_a_model_stuck_in_a_loop_still_ends_with_a_farewell() -> None:
    same = ("Did you hear about the new phone?", False)
    llm = Scripted({"Arjun": [same] * 20, "Meera": [same] * 20})
    msgs, _, _, _ = await _run(llm)
    texts = [m.text.casefold() for m in msgs]
    assert len(texts) == len(set(texts)) and _alternates(msgs)
    assert len(msgs) <= 4 and "get going" in msgs[-1].text


async def test_no_one_says_more_than_the_limit() -> None:
    words = ["metro", "rain", "biryani", "cricket", "rent", "office", "traffic", "festival", "cousin", "gym",
             "puppy", "exam", "wedding", "market", "lake", "concert", "bike", "garden", "movie", "recipe", "monsoon"]
    llm = Scripted({n: [(f"{w.title()}? {n[i % 5:]} has a story about the {w} {i}.", False)
                        for i, w in enumerate(words[k::2] * 2)] for k, n in enumerate(("Arjun", "Meera"))})
    msgs, _, _, _ = await _run(llm, limit=10)
    per = {1: 0, 2: 0}
    for m in msgs:
        per[m.speaker] += 1
    assert max(per.values()) <= 10 and len(msgs) >= 18 and _alternates(msgs)


class OneShot(FakeGemini):
    async def generate(self, model: str, prompt: Any, schema: type[BaseModel] | None = None, **kw: Any) -> LLMResult:
        lines = [("A", "Hi Arjun!"), ("B", "Hey Meera!"), ("B", "Long time."), ("A", "How was Mysuru?"),
                 ("B", "Great trip, the palace was lovely."), ("A", "How was Mysuru?"), ("A", "Bye!"), ("B", "Bye!")]
        data = DialogueOut.model_validate({"messages": [{"speaker": s, "text": x} for s, x in lines],
                                           "topics": ["travel"], "product_mentions": []})
        return LLMResult(data=data, text="", usage=Usage(cost_usd=0.001), model=model)


async def test_one_shot_dialogue_alternates_and_drops_repeats() -> None:
    pa, pb = plans()
    msgs, _, _, _ = await write_dialogue(pa, pb, {}, "friends", "a café", 10, llm=OneShot(), t=0)
    texts = [m.text for m in msgs]
    assert _alternates(msgs) and texts.count("How was Mysuru?") == 1
    assert texts[1] == "Hey Meera! Long time." and msgs[0].speaker == 1
