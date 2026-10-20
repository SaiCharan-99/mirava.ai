"""Ask reliability (Phase A): the stream always ends with exactly one answer, inside a time budget, with keep-alives."""

import asyncio
import json

from agents.insights_assistant import AskAnswer, Assistant, Call, Step, ToolArgs
from insights.tools import DuckRunner, Ledger, Tools
from shared.llm import LLMError, LLMResult
from tests.test_insights import db  # noqa: F401 — shared DuckDB fixture


class RaisingLLM:
    """Every model call fails (e.g. the provider key ran out)."""

    async def generate(self, *a, **k):
        raise LLMError("OpenRouter /chat/completions HTTP 403: Key limit exceeded")


class PlanThenAnswer:
    """Plans one SQL round that never says done, then composes a plain answer; counts calls."""

    def __init__(self, clock):
        self.clock, self.plans, self.composes = clock, 0, 0

    async def generate(self, model, prompt, schema=None, **k):
        if schema is Step:
            self.plans += 1
            self.clock[0] += 30                    # a slow planner round
            return LLMResult(data=Step(thought="count agents", calls=[Call(tool="run_sql", args=ToolArgs(
                sql="SELECT COUNT(*) AS n FROM agents_latest"))]))
        self.composes += 1
        return LLMResult(data=AskAnswer(answer_md="Simulated: 40 agents."))


async def _collect(a, q):
    items = []
    async for it in a.ask(q):
        items.append(it)
    return items


def _tools(db):  # noqa: F811
    return Tools(DuckRunner(db), Ledger(), embed=lambda xs: [[1.0, 0.0, 0.5] for _ in xs])


def test_failing_model_still_answers(db):  # noqa: F811
    a = Assistant(_tools(db), RaisingLLM(), products=[{"product_id": "pulse-5", "name": "Pulse 5"}])
    items = asyncio.run(_collect(a, "Which phone do people prefer, and why?"))
    answers = [i["answer"] for i in items if "answer" in i]
    assert len(answers) == 1 and items[-1] is not None and "answer" in items[-1]
    ans = answers[0]
    assert ans["answer_md"] and ans.get("error") == "model provider credit exhausted"
    assert "OpenRouter" not in json.dumps(ans)               # no raw provider text leaks


def test_time_budget_forces_early_compose(db):  # noqa: F811
    clock = [0.0]
    llm = PlanThenAnswer(clock)
    a = Assistant(_tools(db), llm, products=[], budget_s=45, clock=lambda: clock[0])
    items = asyncio.run(_collect(a, "How many agents are there?"))
    assert llm.plans == 2 and llm.composes == 1               # 0 s → 30 s → 60 s: third round and regenerate skipped
    assert any("Time budget" in (i.get("step") or "") for i in items)
    assert sum(1 for i in items if "answer" in i) == 1


def test_sse_pings_and_single_answer():
    from api.insights import sse_with_pings

    async def slow():
        yield {"step": "a"}
        await asyncio.sleep(0.05)
        yield {"answer": {"answer_md": "x"}}

    async def go():
        return [c async for c in sse_with_pings(slow(), 0.01)]

    chunks = asyncio.run(go())
    assert b": ping\n\n" in chunks
    data = [json.loads(c[6:]) for c in chunks if c.startswith(b"data: ")]
    assert [d for d in data if "answer" in d] == [{"answer": {"answer_md": "x"}}]
