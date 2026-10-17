"""`make llm-smoke`: one structured call + one embedding through the configured backend (never prints the key)."""

from __future__ import annotations

import asyncio
import sys

from pydantic import BaseModel

from shared import models
from shared.llm import OpenRouterClient, get_llm
from shared.settings import get_settings


class Hello(BaseModel):
    """Tiny structured-output schema."""

    greeting: str
    city: str


async def main() -> int:
    """Run the smoke test; exit 0 on success or clean skip."""
    s = get_settings()
    if s.llm_backend == "openrouter" and not s.has_openrouter_key:
        print("SKIP llm-smoke: OPENROUTER_API_KEY is not set in .env (see docs/setup/00-openrouter.md).")
        return 0
    llm = get_llm()
    if isinstance(llm, OpenRouterClient):
        await llm.check_models()
        print(f"models OK: {', '.join(models.ALL_MODELS)}")
    res = await llm.generate(models.MODEL_LITE, "Greet a resident of Indiranagar, Bengaluru in five words.", Hello,
                             purpose="smoke", reasoning="low", max_tokens=200)
    print(f"[{s.llm_backend}] structured: {res.data.model_dump()}  cost=${res.usage.cost_usd:.6f}")
    vec = (await llm.embed(["hello Indiranagar"]))[0]
    print(f"[{s.llm_backend}] embedding dim={len(vec)}")
    return 0 if len(vec) == 768 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
