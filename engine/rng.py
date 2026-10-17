"""Seeded RNG streams keyed by (world_seed, purpose, *keys) — never wall-clock dependent (E-06)."""

from __future__ import annotations

import hashlib

import numpy as np


def _key(part: object) -> int:
    """Stable 32-bit integer for any key part (strings hashed, ints kept)."""
    if isinstance(part, int | np.integer) and int(part) >= 0:
        return int(part) & 0xFFFFFFFF
    return int.from_bytes(hashlib.sha256(str(part).encode()).digest()[:4], "little")


def stream(world_seed: int, purpose: str, *keys: object) -> np.random.Generator:
    """Independent generator for (seed, purpose, keys…), e.g. stream(seed, "plan", day, agent_id)."""
    entropy = [_key(world_seed), _key(purpose), *(_key(k) for k in keys)]
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))


def quota(n: int, shares: dict[str, float]) -> dict[str, int]:
    """Largest-remainder apportionment of `n` items to shares (exact marginals)."""
    total = sum(shares.values()) or 1.0
    raw = {k: n * v / total for k, v in shares.items()}
    out = {k: int(v) for k, v in raw.items()}
    rest = n - sum(out.values())
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))[:rest]:
        out[k] += 1
    return out


def choice(rng: np.random.Generator, weights: dict[str, float]) -> str:
    """Pick one key with probability proportional to its weight (sorted keys for stability)."""
    keys = sorted(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=p / p.sum()))]
