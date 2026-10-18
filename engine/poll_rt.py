"""Polls in the engine (I-07): every agent answers from persona + beliefs + top memories via the decision model."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from engine.events import EventBus
from engine.governor import BudgetGovernor
from engine.world import World
from insights.likely_buyers import age_band
from insights.polls import estimate_usd
from mind.decision import BATCH, DecisionAdapter, DecisionRequest
from shared import time as simtime
from shared.store import DocStore

log = logging.getLogger("engine.poll")


def poll_context(w: World, aid: int, commerce: Any, social: Any, question: str) -> dict[str, Any]:
    """One agent's own context for a poll answer (no minute-level time: same day ⇒ same answer)."""
    prof = w.profiles[aid]
    beliefs = []
    if commerce is not None:
        for pid, st in sorted(commerce.stages_of(aid).items()):
            pr = commerce.pairs[f"{aid}|{pid}"]
            beliefs.append(f"{pid}: {st}, attitude {pr.attitude:+.2f}")
    mem = sorted((social.wm.get(aid, []) if social is not None else []), key=lambda e: (-e["importance"], -e["t"]))[:3]
    ph = w.phones[aid]
    return {"persona": prof.persona_card, "phone": f"{ph.get('brand')} {ph.get('tier')}, {ph.get('condition')}",
            "beliefs": beliefs, "memories": [m["text"] for m in mem], "question": question,
            "day": simtime.day_of(w.t)}


async def run_poll(w: World, bus: EventBus, decider: DecisionAdapter, gov: BudgetGovernor, store: DocStore,
                   cmd: dict[str, Any], *, commerce: Any = None, social: Any = None, llm: Any = None) -> dict[str, Any]:
    """Ask the agents; emit `poll_answer` events; write `polls/{poll_id}` with the result."""
    t0 = time.time()
    pid, q, opts = str(cmd["poll_id"]), str(cmd["question"]), [str(o) for o in cmd["options"]]
    ids = cmd.get("agent_ids") or [a.id for a in w.agents if w.profiles[a.id].special_role == "none"]
    est = estimate_usd(len(ids))
    if not gov.allow_interactive(est):
        res = {"poll_id": pid, "status": "refused", "reason": "interactive budget", "estimate_usd": est}
        await asyncio.to_thread(store.set, "polls", pid, res)
        return res
    await asyncio.to_thread(store.set, "polls", pid, {"poll_id": pid, "question": q, "options": opts, "n": len(ids),
                                                     "status": "running", "estimate_usd": est, "t": w.t})
    reqs = [DecisionRequest(agent_id=a, kind="poll", options=opts, context=poll_context(w, a, commerce, social, q))
            for a in ids]
    chunks = [reqs[i:i + BATCH] for i in range(0, len(reqs), BATCH)]
    sem = asyncio.Semaphore(8)

    async def one(ch: list[DecisionRequest]) -> list[Any]:
        async with sem:
            return await decider.decide_batch(ch)

    spent0 = float(getattr(llm, "total_cost_usd", 0.0) or 0.0)
    results = [r for part in await asyncio.gather(*(one(c) for c in chunks)) for r in part]
    actual = round(float(getattr(llm, "total_cost_usd", 0.0) or 0.0) - spent0, 5)
    gov.record(actual, "interactive")
    dist = {o: 0 for o in opts}
    seg: dict[str, dict[str, int]] = {}
    quotes = []
    t = w.t
    for req, r in zip(reqs, results, strict=True):
        choice = r.choice if r.choice in dist else opts[0]
        dist[choice] += 1
        prof = w.profiles[req.agent_id]
        band = age_band(prof.age)
        seg.setdefault(f"{band}|{prof.income_band}", {o: 0 for o in opts})[choice] += 1
        ev = bus.new("poll_answer", t, req.agent_id, {"poll_id": pid, "option": choice, "reason": r.reason[:240],
                                                      "question": q})
        if len(quotes) < 400:
            quotes.append({"agent_id": req.agent_id, "name": prof.name, "option": choice, "text": r.reason[:240],
                           "event_id": ev.event_id})
    res = {"poll_id": pid, "question": q, "options": opts, "n": len(ids), "status": "done", "distribution": dist,
           "by_segment": seg, "quotes": quotes[:12], "estimate_usd": est, "cost_usd": actual, "t": t,
           "seconds": round(time.time() - t0, 1)}
    await asyncio.to_thread(store.set, "polls", pid, res)
    log.info("poll %s done: %d answers in %.1fs", pid, len(ids), res["seconds"])
    return res
