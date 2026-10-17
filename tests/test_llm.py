"""LLM gateway: FakeGemini determinism, OpenRouter request shape (mocked httpx), retries, cache, cost."""

import json

import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr

from shared import models
from shared.llm import FakeGemini, LLMError, OpenRouterClient, get_llm, strict_schema
from shared.settings import Settings

BASE = "https://openrouter.ai/api/v1"


class Thought(BaseModel):
    text: str
    importance: int
    tags: list[str]
    mood: float | None


def settings() -> Settings:
    return Settings(_env_file=None, llm_backend="openrouter", openrouter_api_key=SecretStr("sk-or-test"))


def ok_body(content: dict, cost: float = 0.0012) -> dict:
    return {"model": models.MODEL_LITE, "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "cost": cost}}


async def test_fake_is_deterministic_and_valid():
    a, b = FakeGemini(), FakeGemini()
    r1 = await a.generate(models.MODEL_LITE, "hello", Thought, purpose="t")
    r2 = await b.generate(models.MODEL_LITE, "hello", Thought, purpose="t")
    r3 = await a.generate(models.MODEL_LITE, "other", Thought, purpose="t")
    assert isinstance(r1.data, Thought) and r1.data == r2.data and r1.data != r3.data
    e1, e2 = await a.embed(["x", "y"]), await b.embed(["x", "y"])
    assert e1 == e2 and len(e1[0]) == 768 and abs(sum(v * v for v in e1[0]) - 1) < 1e-6


def test_strict_schema_shape():
    s = strict_schema(Thought)
    assert s["additionalProperties"] is False and set(s["required"]) == {"text", "importance", "tags", "mood"}


def test_get_llm_backend_switch():
    assert isinstance(get_llm(Settings(_env_file=None, llm_backend="fake")), FakeGemini)
    assert isinstance(get_llm(settings()), OpenRouterClient)


@respx.mock
async def test_openrouter_request_shape_and_cost():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=ok_body({"text": "hi", "importance": 3, "tags": [], "mood": None})))
    seen = []
    c = OpenRouterClient(settings(), on_cost=seen.append)
    res = await c.generate(models.MODEL_LITE, "think", Thought, purpose="ad_thought", reasoning="low", max_tokens=300,
                           images=["https://x/y.png"], priority_class="P2")
    body = json.loads(route.calls[0].request.content)
    hdr = route.calls[0].request.headers
    assert hdr["authorization"] == "Bearer sk-or-test"
    assert body["model"] == models.MODEL_LITE and body["max_tokens"] == 300
    assert body["reasoning"] == {"effort": "low"} and body["usage"] == {"include": True}
    assert body["provider"] == {"require_parameters": True}
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "think"} and parts[1]["image_url"]["url"] == "https://x/y.png"
    assert res.data.text == "hi" and res.usage.cost_usd == pytest.approx(0.0012)
    assert seen[0].priority_class == "P2" and seen[0].purpose == "ad_thought"
    # cache: second identical call does not hit the network
    res2 = await c.generate(models.MODEL_LITE, "think", Thought, purpose="ad_thought", reasoning="low",
                            max_tokens=300, images=["https://x/y.png"], priority_class="P2")
    assert res2.cached and route.call_count == 1 and c.total_cost_usd == pytest.approx(0.0012)


@respx.mock
async def test_openrouter_retries_429_then_succeeds():
    route = respx.post(f"{BASE}/chat/completions").mock(side_effect=[
        httpx.Response(429, json={"error": "rate"}), httpx.Response(503),
        httpx.Response(200, json=ok_body({"text": "x", "importance": 1, "tags": ["a"], "mood": 0.5}))])
    c = OpenRouterClient(settings(), backoff_s=0)
    res = await c.generate(models.MODEL_LITE, "p", Thought, purpose="t")
    assert route.call_count == 3 and res.data.tags == ["a"]


@respx.mock
async def test_openrouter_no_retry_on_401_and_bad_json():
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401, json={"error": "no"}))
    with pytest.raises(LLMError):
        await OpenRouterClient(settings(), backoff_s=0).generate(models.MODEL_LITE, "p", Thought, purpose="t")
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(
        200, json={"choices": [{"message": {"content": "not json"}}], "usage": {}}))
    with pytest.raises(LLMError):
        await OpenRouterClient(settings(), backoff_s=0).generate(models.MODEL_LITE, "q", Thought, purpose="t")


@respx.mock
async def test_openrouter_embeddings_and_model_check():
    respx.post(f"{BASE}/embeddings").mock(return_value=httpx.Response(
        200, json={"data": [{"index": 0, "embedding": [3.0, 4.0] + [0.0] * 3070}]}))
    vec = (await OpenRouterClient(settings()).embed(["hi"]))[0]
    assert len(vec) == 768 and vec[0] == pytest.approx(0.6)
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(
        200, json={"data": [{"id": m} for m in models.CHAT_MODELS]}))
    respx.get(f"{BASE}/embeddings/models").mock(return_value=httpx.Response(200, json={"data": []}))
    with pytest.raises(LLMError, match="embedding"):
        await OpenRouterClient(settings()).check_models()
