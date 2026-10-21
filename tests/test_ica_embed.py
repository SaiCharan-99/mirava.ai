"""ICA embeddings: Vertex first in the cloud, OpenRouter on failure, OpenRouter only locally."""

import asyncio

import shared.llm as llm
from shared.settings import Settings


def _client(env: str) -> llm.ICAClient:
    return llm.ICAClient(Settings(env=env, llm_backend="ica", gcp_project_id="p"))


def test_cloud_uses_vertex(monkeypatch):
    async def fake_vertex(s, texts, dim):
        return [[1.0] * dim for _ in texts]
    monkeypatch.setattr(llm, "vertex_embed", fake_vertex)
    c = _client("cloud")

    async def boom(texts, dim=768):
        raise AssertionError("OpenRouter must not be called")
    monkeypatch.setattr(c.fallback, "embed", boom)
    assert asyncio.run(c.embed(["a", "b"], 8)) == [[1.0] * 8, [1.0] * 8]


def test_cloud_falls_back_to_openrouter(monkeypatch):
    async def bad_vertex(s, texts, dim):
        raise llm.LLMError("Vertex down")
    monkeypatch.setattr(llm, "vertex_embed", bad_vertex)
    c = _client("cloud")

    async def ok(texts, dim=768):
        return [[2.0] * dim for _ in texts]
    monkeypatch.setattr(c.fallback, "embed", ok)
    assert asyncio.run(c.embed(["a"], 4)) == [[2.0] * 4]


def test_local_skips_vertex(monkeypatch):
    async def never(s, texts, dim):
        raise AssertionError("Vertex must not be called locally")
    monkeypatch.setattr(llm, "vertex_embed", never)
    c = _client("local")

    async def ok(texts, dim=768):
        return [[3.0] * dim for _ in texts]
    monkeypatch.setattr(c.fallback, "embed", ok)
    assert asyncio.run(c.embed(["a"], 2)) == [[3.0] * 2]



def test_decision_batch_halves_on_bad_json():
    """A batch whose reply breaks is split and retried; only an irreducible failure uses the rule fallback."""
    import re

    from mind.decision import DecisionRequest, OpenRouterDecision, _Batch

    class Res:
        def __init__(self, data):
            self.data = data

    class LLM:
        calls: list[int] = []

        async def generate(self, model, prompt, schema, **kw):
            rids = [int(x) for x in re.findall(r'"rid": (\d+)', prompt)]
            self.calls.append(len(rids))
            if len(rids) > 8:
                raise llm.LLMError("structured output did not validate for _Batch")
            return Res(_Batch.model_validate({"items": [{"rid": r, "scores": [0.9, 0.1], "reason": "x"} for r in rids]}))

    fake = LLM()
    reqs = [DecisionRequest(agent_id=i, kind="consider", context={"n": i}, options=["yes", "no"]) for i in range(32)]
    out = asyncio.run(OpenRouterDecision(fake).decide_batch(reqs))
    assert all(r.engine == "openrouter" and r.choice == "yes" for r in out)
    assert fake.calls[0] == 32 and max(fake.calls[1:]) <= 16
