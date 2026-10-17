"""LLM gateway (X-01): OpenRouter (default), Vertex AI (optional), FakeGemini (tests). All model calls go here."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel

from shared import models
from shared.settings import Settings, get_settings

Reasoning = Literal["minimal", "low", "medium", "high"]
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class Usage(BaseModel):
    """Token usage and exact cost of one call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class LLMResult(BaseModel):
    """Result of `generate`: parsed `data` when a schema was given, raw `text` always."""

    data: Any = None
    text: str = ""
    usage: Usage = Usage()
    model: str = ""
    cached: bool = False


@dataclass
class CostRecord:
    """One per-call cost record (fed to the budget governor)."""

    purpose: str
    model: str
    priority_class: str
    usage: Usage
    cached: bool
    at: float = field(default_factory=time.time)


class LLMError(RuntimeError):
    """Raised when a model call fails after retries or returns unusable output."""


class LLMClient(Protocol):
    """Interface every backend implements (INTERFACES §3)."""

    async def generate(self, model: str, prompt: str | list, schema: type[BaseModel] | None = None, *,
                       purpose: str, reasoning: Reasoning = "low", max_tokens: int = 600,
                       images: list[str] | None = None, priority_class: str = "P5") -> LLMResult: ...

    async def embed(self, texts: list[str], dim: int = 768) -> list[list[float]]: ...


# ---------------------------------------------------------------- helpers

def input_hash(*parts: Any) -> str:
    """Stable sha256 over JSON-serialisable parts (cache key, fake seed)."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def strict_schema(schema_model: type[BaseModel]) -> dict:
    """JSON schema for strict structured output: refs inlined, all props required, no extra props."""
    raw = schema_model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = defs[node["$ref"].split("/")[-1]]
                return walk(copy.deepcopy(target))
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)


def to_messages(prompt: str | list, images: list[str] | None) -> list[dict]:
    """Build OpenAI-style chat messages; images become image_url parts on the last user message."""
    msgs: list[dict[str, Any]]
    if isinstance(prompt, list):
        msgs = copy.deepcopy(prompt)
    else:
        msgs = [{"role": "user", "content": prompt}]
    if images:
        last = msgs[-1]
        text = last["content"] if isinstance(last["content"], str) else ""
        parts: list[dict] = [{"type": "text", "text": text}] if text else []
        parts += [{"type": "image_url", "image_url": {"url": u}} for u in images]
        last["content"] = parts
    return msgs


def fit_dim(vec: list[float], dim: int) -> list[float]:
    """Truncate (Matryoshka) and L2-normalise an embedding to `dim`."""
    v = vec[:dim]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class _CachingClient:
    """Shared cache + cost bookkeeping for all backends."""

    def __init__(self, on_cost: Callable[[CostRecord], None] | None = None) -> None:
        self._cache: dict[str, LLMResult] = {}
        self.costs: list[CostRecord] = []
        self._on_cost = on_cost

    def _record(self, purpose: str, model: str, priority_class: str, res: LLMResult) -> None:
        rec = CostRecord(purpose, model, priority_class, res.usage, res.cached)
        self.costs.append(rec)
        if self._on_cost:
            self._on_cost(rec)

    @property
    def total_cost_usd(self) -> float:
        """Sum of reported cost of all non-cached calls."""
        return sum(c.usage.cost_usd for c in self.costs if not c.cached)


# ---------------------------------------------------------------- OpenRouter

class OpenRouterClient(_CachingClient):
    """OpenRouter chat/completions + embeddings with strict structured output, usage accounting and retries."""

    def __init__(self, settings: Settings | None = None, *, http: httpx.AsyncClient | None = None,
                 on_cost: Callable[[CostRecord], None] | None = None, max_retries: int = 3,
                 backoff_s: float = 0.8) -> None:
        super().__init__(on_cost)
        self.s = settings or get_settings()
        self.base_url = self.s.openrouter_base_url.rstrip("/")
        self._http = http
        self.max_retries = max_retries
        self.backoff_s = backoff_s

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.s.openrouter_api_key.get_secret_value()}",
                "Content-Type": "application/json", "X-Title": self.s.openrouter_app_title,
                "HTTP-Referer": "https://mirava.ai"}

    def build_body(self, model: str, prompt: str | list, schema: type[BaseModel] | None, reasoning: Reasoning,
                   max_tokens: int, images: list[str] | None) -> dict:
        """Request body for /chat/completions (exposed for tests)."""
        body: dict[str, Any] = {
            "model": model, "messages": to_messages(prompt, images), "max_tokens": max_tokens,
            "reasoning": {"effort": reasoning}, "usage": {"include": True},
        }
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": strict_schema(schema)}}
            body["provider"] = {"require_parameters": True}
        return body

    async def _post(self, path: str, body: dict) -> dict:
        client = self._http or httpx.AsyncClient(timeout=60)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    r = await client.post(f"{self.base_url}{path}", json=body, headers=self._headers())
                except httpx.TransportError as e:
                    if attempt == self.max_retries:
                        raise LLMError(f"transport error: {type(e).__name__}") from e
                else:
                    if r.status_code < 400:
                        return r.json()
                    if r.status_code not in RETRY_STATUS or attempt == self.max_retries:
                        raise LLMError(f"OpenRouter {path} HTTP {r.status_code}: {r.text[:300]}")
                await asyncio.sleep(self.backoff_s * (2 ** attempt))
            raise LLMError("unreachable")
        finally:
            if self._http is None:
                await client.aclose()

    async def generate(self, model: str, prompt: str | list, schema: type[BaseModel] | None = None, *,
                       purpose: str, reasoning: Reasoning = "low", max_tokens: int = 600,
                       images: list[str] | None = None, priority_class: str = "P5") -> LLMResult:
        """One model call (cached by input hash)."""
        key = input_hash("gen", model, prompt, schema.__name__ if schema else None,
                         strict_schema(schema) if schema else None, reasoning, max_tokens, images or [])
        if key in self._cache:
            res = self._cache[key].model_copy(update={"cached": True})
            self._record(purpose, model, priority_class, res)
            return res
        raw = await self._post("/chat/completions", self.build_body(model, prompt, schema, reasoning, max_tokens,
                                                                     images))
        try:
            text = raw["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"malformed response: {str(raw)[:200]}") from e
        u = raw.get("usage") or {}
        usage = Usage(prompt_tokens=int(u.get("prompt_tokens", 0)), completion_tokens=int(u.get("completion_tokens", 0)),
                      cost_usd=float(u.get("cost", 0.0) or 0.0))
        data = None
        if schema is not None:
            try:
                data = schema.model_validate_json(text)
            except ValueError as e:
                raise LLMError(f"structured output did not validate for {schema.__name__}") from e
        res = LLMResult(data=data, text=text, usage=usage, model=raw.get("model", model), cached=False)
        self._cache[key] = res
        self._record(purpose, model, priority_class, res)
        return res

    async def embed(self, texts: list[str], dim: int = 768) -> list[list[float]]:
        """Embeddings via /embeddings, normalised to `dim`."""
        raw = await self._post("/embeddings", {"model": models.MODEL_EMBED, "input": texts, "dimensions": dim})
        rows = sorted(raw.get("data", []), key=lambda d: d.get("index", 0))
        return [fit_dim(r["embedding"], dim) for r in rows]

    async def list_models(self) -> set[str]:
        """Ids served by OpenRouter (chat + embedding catalogues)."""
        client = self._http or httpx.AsyncClient(timeout=30)
        try:
            ids: set[str] = set()
            for path in ("/models", "/embeddings/models"):
                r = await client.get(f"{self.base_url}{path}", headers=self._headers())
                if r.status_code < 400:
                    ids |= {m["id"] for m in r.json().get("data", [])}
            return ids
        finally:
            if self._http is None:
                await client.aclose()

    async def check_models(self) -> None:
        """Startup check: fail fast if any configured MODEL_*_ID is not listed."""
        missing = [m for m in models.ALL_MODELS if m not in await self.list_models()]
        if missing:
            raise LLMError(f"OpenRouter does not list configured models: {missing}")


# ---------------------------------------------------------------- Vertex AI (optional)

class VertexClient(OpenRouterClient):
    """Gemini on Vertex AI through its OpenAI-compatible endpoint; switch with LLM_BACKEND=vertex."""

    def __init__(self, settings: Settings | None = None, **kw: Any) -> None:
        super().__init__(settings, **kw)
        loc = self.s.vertex_location
        host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
        self.base_url = f"https://{host}/v1/projects/{self.s.gcp_project_id}/locations/{loc}/endpoints/openapi"

    def _headers(self) -> dict[str, str]:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}

    def build_body(self, model: str, prompt: str | list, schema: type[BaseModel] | None, reasoning: Reasoning,
                   max_tokens: int, images: list[str] | None) -> dict:
        """Vertex accepts the same body minus OpenRouter-only fields."""
        body = super().build_body(model, prompt, schema, reasoning, max_tokens, images)
        body.pop("usage", None)
        body.pop("provider", None)
        body["reasoning_effort"] = body.pop("reasoning")["effort"]
        return body

    async def check_models(self) -> None:
        """Vertex has no public model list here; nothing to check."""


# ---------------------------------------------------------------- Fake

def _fake_value(schema: dict, seed: str, path: str) -> Any:
    """Deterministic value for a (strict) JSON schema node."""
    h = int(hashlib.sha256(f"{seed}|{path}".encode()).hexdigest()[:12], 16)
    if "enum" in schema:
        return schema["enum"][h % len(schema["enum"])]
    if "const" in schema:
        return schema["const"]
    if "anyOf" in schema:
        options = [o for o in schema["anyOf"] if o.get("type") != "null"] or schema["anyOf"]
        return _fake_value(options[0], seed, path)
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        props = schema.get("properties", {})
        return {k: _fake_value(v, seed, f"{path}.{k}") for k, v in props.items()}
    if t == "array":
        n = schema.get("minItems", 0) or (1 + h % 3)
        if "prefixItems" in schema:
            return [_fake_value(s, seed, f"{path}[{i}]") for i, s in enumerate(schema["prefixItems"])]
        return [_fake_value(schema.get("items", {"type": "string"}), seed, f"{path}[{i}]") for i in range(n)]
    if t == "integer":
        lo, hi = schema.get("minimum", 1), schema.get("maximum", 10)
        return int(lo + h % (int(hi) - int(lo) + 1))
    if t == "number":
        lo, hi = schema.get("minimum", 0.0), schema.get("maximum", 1.0)
        return round(lo + (h % 1000) / 999 * (hi - lo), 3)
    if t == "boolean":
        return bool(h % 2)
    if t == "null":
        return None
    return f"fake-{path.split('.')[-1] or 'text'}-{h % 10000:04d}"


class FakeGemini(_CachingClient):
    """Deterministic offline backend: same inputs → same outputs; zero cost."""

    async def generate(self, model: str, prompt: str | list, schema: type[BaseModel] | None = None, *,
                       purpose: str, reasoning: Reasoning = "low", max_tokens: int = 600,
                       images: list[str] | None = None, priority_class: str = "P5") -> LLMResult:
        """Return schema-valid deterministic data (or a short text) derived from the input hash."""
        seed = input_hash("fake", model, prompt, schema.__name__ if schema else None, images or [])
        if schema is not None:
            data = schema.model_validate(_fake_value(strict_schema(schema), seed, ""))
            text = data.model_dump_json()
        else:
            data, text = None, f"[fake:{purpose}] {seed[:12]}"
        n_in = len(json.dumps(prompt, default=str)) // 4
        res = LLMResult(data=data, text=text, usage=Usage(prompt_tokens=n_in, completion_tokens=len(text) // 4),
                        model=model, cached=False)
        self._record(purpose, model, priority_class, res)
        return res

    async def embed(self, texts: list[str], dim: int = 768) -> list[list[float]]:
        """Deterministic unit vectors from the text hash."""
        out = []
        for t in texts:
            digest = b""
            i = 0
            while len(digest) < dim:
                digest += hashlib.sha256(f"{t}|{i}".encode()).digest()
                i += 1
            out.append(fit_dim([(b - 127.5) / 127.5 for b in digest[:dim]], dim))
        return out


# ---------------------------------------------------------------- factory

_client: LLMClient | None = None


def get_llm(settings: Settings | None = None, *, fresh: bool = False) -> LLMClient:
    """Backend chosen by LLM_BACKEND (fake | openrouter | vertex)."""
    global _client
    if _client is not None and not fresh and settings is None:
        return _client
    s = settings or get_settings()
    client: LLMClient
    if s.llm_backend == "openrouter":
        client = OpenRouterClient(s)
    elif s.llm_backend == "vertex":
        client = VertexClient(s)
    else:
        client = FakeGemini()
    if settings is None:
        _client = client
    return client
