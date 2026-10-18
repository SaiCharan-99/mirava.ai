"""Polls (I-07): estimate, deterministic ids; the engine asks each agent via the decision model (batched 32)."""

from __future__ import annotations

import hashlib
import json

from shared.models import price_per_mtok

TOKENS_IN_PER_AGENT = 260      # persona card + beliefs + 3 memories + question, inside a 32-agent batch
TOKENS_OUT_PER_AGENT = 45


def estimate_usd(n_agents: int) -> float:
    """Cost estimate for asking n agents (Flash-Lite prices from shared.models)."""
    pin, pout = price_per_mtok("lite")
    return round(n_agents * (TOKENS_IN_PER_AGENT * pin + TOKENS_OUT_PER_AGENT * pout) / 1e6, 4)


def poll_id(question: str, options: list[str], agent_ids: list[int] | None) -> str:
    """Stable id for a (question, options, cohort)."""
    body = json.dumps([question.strip().lower(), options, sorted(agent_ids) if agent_ids else None])
    return "poll-" + hashlib.sha256(body.encode()).hexdigest()[:10]
