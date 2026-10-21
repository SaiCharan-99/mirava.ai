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
