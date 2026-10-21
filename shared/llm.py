"""LLM gateway (X-01): OpenRouter (default), Vertex AI (optional), FakeGemini (tests). All model calls go here."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel

from shared import models
from shared.settings import Settings, get_settings

log = logging.getLogger(__name__)

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
            out = {k: ({n: walk(v) for n, v in val.items()} if k == "properties" else walk(val))
                   for k, val in node.items() if k not in ("title", "default")}   # keep fields named title/default
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


async def vertex_embed(s: Settings, texts: list[str], dim: int) -> list[list[float]]:
    """Embeddings from Vertex AI `gemini-embedding-001` (one text per request; ADC auth), fitted to `dim`."""
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    await asyncio.to_thread(creds.refresh, google.auth.transport.requests.Request())
    loc = s.gcp_region or "asia-south1"
    url = (f"https://{loc}-aiplatform.googleapis.com/v1/projects/{s.gcp_project_id}/locations/{loc}"
           "/publishers/google/models/gemini-embedding-001:predict")
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        async def one(t: str) -> list[float]:
            r = await client.post(url, headers=headers, json={"instances": [{"content": t}],
                                                              "parameters": {"outputDimensionality": dim}})
            if r.status_code >= 400:
                raise LLMError(f"Vertex embeddings HTTP {r.status_code}: {r.text[:200]}")
            return fit_dim(r.json()["predictions"][0]["embeddings"]["values"], dim)
        return list(await asyncio.gather(*(one(t) for t in texts)))


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

_STATUS: dict[str, Any] = {"out_of_credit": False, "since": None}


def model_status() -> dict[str, Any]:
    """Whether model calls in this process are failing because every provider key is out of credit."""
    return dict(_STATUS)


def _mark(out_of_credit: bool) -> None:
    if out_of_credit and not _STATUS["out_of_credit"]:
        _STATUS.update(out_of_credit=True, since=time.time())
    elif not out_of_credit and _STATUS["out_of_credit"]:
        _STATUS.update(out_of_credit=False, since=None)


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
        self.using_fallback = False

    def _key(self) -> str:
        """Active key: the main key until it runs out, then the fallback (sticky for this process)."""
        k = self.s.openrouter_api_key_fallback if self.using_fallback else self.s.openrouter_api_key
        return k.get_secret_value()

    def _exhausted(self, r: httpx.Response) -> bool:
        """True when the key is out of credit (402) or over its key limit; switches to the fallback if one exists."""
        out = r.status_code == 402 or (r.status_code in (401, 403) and "limit" in r.text.lower())
        if out and (self.using_fallback or not self.s.openrouter_api_key_fallback.get_secret_value().strip()):
            _mark(True)                                         # no key left with credit
        if out and not self.using_fallback and self.s.openrouter_api_key_fallback.get_secret_value().strip():
            self.using_fallback = True
            log.warning("OpenRouter main key exhausted (HTTP %s); switching to the fallback key", r.status_code)
            return True
        return False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key()}",
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
                        _mark(False)
                        return r.json()
                    if self._exhausted(r):
                        r = await client.post(f"{self.base_url}{path}", json=body, headers=self._headers())
                        if r.status_code < 400:
                            _mark(False)
                            return r.json()
                        self._exhausted(r)
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
        u = raw.get("usage") or {}
        usage = Usage(prompt_tokens=int(u.get("prompt_tokens", 0)), cost_usd=float(u.get("cost", 0.0) or 0.0))
        self._record("embed", models.MODEL_EMBED, "P5",
                     LLMResult(usage=usage, model=models.MODEL_EMBED, cached=False))
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


# ---------------------------------------------------------------- IBM ICA (optional)

# keywords Bedrock's structured output rejects; Pydantic still enforces them when the reply is validated
_ICA_DROP = {"maxItems", "minItems", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength",
             "maxLength", "multipleOf", "pattern", "format", "default", "title"}
_ICA_HINT = {"minimum": "min {}", "maximum": "max {}", "minItems": "at least {} items", "maxItems": "at most {} items",
             "minLength": "at least {} chars", "maxLength": "at most {} chars"}


def ica_schema(node: Any) -> Any:
    """strict_schema() minus the keywords Bedrock does not support. Dropped limits move into "description" so the
    model still sees them; field names under "properties" are kept."""
    if isinstance(node, dict):
        out = {k: ({n: ica_schema(v) for n, v in val.items()} if k == "properties" else ica_schema(val))
               for k, val in node.items() if k not in _ICA_DROP}
        hints = [_ICA_HINT[k].format(node[k]) for k in _ICA_HINT if k in node]
        if hints:
            out["description"] = (f'{out["description"]}. ' if out.get("description") else "") + "; ".join(hints)
        return out
    if isinstance(node, list):
        return [ica_schema(v) for v in node]
    return node


class ICAClient(OpenRouterClient):
    """Chat via IBM ICA's OpenAI-compatible endpoint (LLM_BACKEND=ica). Every tier uses ICA_MODEL_ID; if ICA fails
    (down, rate-limited, bad output) the call is retried once on OpenRouter with the original model. Embeddings stay on
    OpenRouter because ICA has no embedding endpoint."""

    def __init__(self, settings: Settings | None = None, **kw: Any) -> None:
        super().__init__(settings, **kw)
        self.base_url = self.s.ica_base_url.rstrip("/")
        self.fallback = OpenRouterClient(self.s, on_cost=kw.get("on_cost"))
        self.ica_failures = 0
        self._gate = asyncio.Semaphore(max(1, self.s.ica_max_concurrent))       # ICA's gateway has a small DB pool: too many parallel calls give 400 QueuePool

    def _key(self) -> str:
        return self.s.ica_api_key.get_secret_value()

    def _exhausted(self, r: httpx.Response) -> bool:
        return False                                          # no second ICA key; OpenRouter is the fallback

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}

    def build_body(self, model: str, prompt: str | list, schema: type[BaseModel] | None, reasoning: Reasoning,
                   max_tokens: int, images: list[str] | None) -> dict:
        body: dict[str, Any] = {"model": self.s.ica_model_id, "messages": to_messages(prompt, images),
                                "max_tokens": max_tokens, "stream": False}
        if schema is not None:
            sch = ica_schema(strict_schema(schema))
            if json.dumps(sch).count('"anyOf"') > 12:         # Bedrock rejects schemas with too many unions: ask in-prompt
                body["messages"].append({"role": "user", "content": (
                    "Reply with ONLY one JSON object (no code fences, no commentary) that matches this JSON schema:\n"
                    + json.dumps(sch))})
            else:
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "strict": True, "schema": sch}}
        return body

    async def _post(self, path: str, body: dict) -> dict:
        if path != "/chat/completions":
            raise LLMError(f"ICA has no {path}")
        raw: dict = {}
        for attempt in range(4):
            try:
                async with self._gate:
                    raw = await super()._post("/chat-models/chat/completions", body)
                break
            except LLMError as e:
                if "QueuePool" not in str(e) or attempt == 3:   # gateway pool exhausted: back off and retry
                    raise
                await asyncio.sleep(self.backoff_s * 2 * (attempt + 1))
        try:                                                  # tolerate ```json fences around in-prompt JSON
            msg = raw["choices"][0]["message"]
            txt = (msg.get("content") or "").strip()
            if txt.startswith("```"):
                msg["content"] = txt.strip("`").removeprefix("json").strip()
        except (KeyError, IndexError, AttributeError):
            pass
        return raw

    async def generate(self, model: str, prompt: str | list, schema: type[BaseModel] | None = None, *,
                       purpose: str, reasoning: Reasoning = "low", max_tokens: int = 600,
                       images: list[str] | None = None, priority_class: str = "P5") -> LLMResult:
        try:
            try:
                return await super().generate(model, prompt, schema, purpose=purpose, reasoning=reasoning,
                                              max_tokens=max_tokens, images=images, priority_class=priority_class)
            except LLMError as e:
                if "did not validate" not in str(e) or e.__cause__ is None:
                    raise
                fix = ("Your previous JSON broke these rules, so reply again with valid JSON that respects every limit "
                       f"(keep text short):\n{str(e.__cause__)[:600]}")
                again = [*prompt, {"role": "user", "content": fix}] if isinstance(prompt, list) else f"{prompt}\n\n{fix}"
                return await super().generate(model, again, schema, purpose=purpose, reasoning=reasoning,
                                              max_tokens=max_tokens, images=images, priority_class=priority_class)
        except LLMError as e:
            self.ica_failures += 1
            log.warning("ICA call failed (%s); falling back to OpenRouter", e)
            return await self.fallback.generate(model, prompt, schema, purpose=purpose, reasoning=reasoning,
                                                max_tokens=max_tokens, images=images, priority_class=priority_class)

    async def embed(self, texts: list[str], dim: int = 768) -> list[list[float]]:
        """ICA has no embeddings: Vertex gemini-embedding-001 first (cloud only), then OpenRouter."""
        if self.s.env == "cloud":
            try:
                return await vertex_embed(self.s, texts, dim)
            except Exception:  # noqa: BLE001 — any Vertex failure falls through to OpenRouter
                log.warning("Vertex embedding failed; trying OpenRouter", exc_info=True)
        keep = dict(_STATUS)                                  # an OpenRouter embedding failure must not flag chat as down
        try:
            return await self.fallback.embed(texts, dim)
        finally:
            _STATUS.update(keep)

    async def list_models(self) -> set[str]:
        return {self.s.ica_model_id}

    async def check_models(self) -> None:
        return None


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
    """Backend chosen by LLM_BACKEND (fake | openrouter | vertex | ica)."""
    global _client
    if _client is not None and not fresh and settings is None:
        return _client
    s = settings or get_settings()
    client: LLMClient
    if s.llm_backend == "openrouter":
        client = OpenRouterClient(s)
    elif s.llm_backend == "vertex":
        client = VertexClient(s)
    elif s.llm_backend == "ica":
        client = ICAClient(s)
    else:
        client = FakeGemini()
    if settings is None:
        _client = client
    return client
