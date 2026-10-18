"""Purchases (S-05, S-06): need ≥ θ, affordability (cash/card/EMI), margin ≥ δ → typed choice incl. baseline market."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from commerce.need import affordability, cfg
from commerce.stores import BASELINE
from shared.llm import LLMClient
from shared.models import MODEL_LITE

TIER_ORDER = ("budget", "mid", "premium", "flagship")


class PurchaseChoice(BaseModel):
    """Typed decision-model output."""

    decision: Literal["buy", "postpone", "not_buying"]
    option: str
    method: Literal["cash", "card", "emi", "none"]
    reason: str


@dataclass
class Option:
    """One purchasable option with its utility for this agent."""

    option_id: str
    label: str
    price_inr: int
    utility: float
    method: str | None
    afford: float


def options_for(interests: dict[str, float], products: dict[str, dict[str, Any]], money: dict[str, Any],
                current_tier: str) -> list[Option]:
    """Our launched products (utility = interest) and the baseline market (utility = appeal × tier fit)."""
    out: list[Option] = []
    for pid, i in interests.items():
        p = products.get(pid)
        if p is None:
            continue
        a, m = affordability(int(p["price_inr"]), money)
        out.append(Option(pid, p["name"], int(p["price_inr"]), round(i * (0.6 + 0.4 * a), 3), m, a))
    ti = TIER_ORDER.index(current_tier) if current_tier in TIER_ORDER else 1
    for b in BASELINE:
        fit = 1.0 - 0.35 * abs(TIER_ORDER.index(b["tier"]) - ti)
        a, m = affordability(int(b["price_inr"]), money)
        out.append(Option(b["id"], b["label"], int(b["price_inr"]), round(b["appeal"] * fit * (0.6 + 0.4 * a), 3),
                          m, a))
    return sorted(out, key=lambda o: (-o.utility, o.option_id))


def gate(need: float, opts: list[Option], life_event: bool) -> tuple[str, str, list[Option]]:
    """Rule gate → ('buy'|'postpone'|'not_buying', reason, allowed options)."""
    p = cfg()["purchase"]
    if need < p["theta_need"] and not life_event:
        return "not_buying", f"need {need:.2f} below θ {p['theta_need']}", []
    ok = [o for o in opts if o.method is not None]
    if not ok:
        return "postpone", "cannot afford any option yet", []
    best = ok[0]
    second = ok[1].utility if len(ok) > 1 else 0.0
    if best.utility - second < p["delta_margin"]:
        return "postpone", f"no clear favourite (margin {best.utility - second:.2f} < δ)", ok[:3]
    return "buy", f"need {need:.2f}, {best.label} leads by {best.utility - second:.2f}", ok[:3]


async def decide(agent_id: int, persona_card: str, need: float, opts: list[Option], life_event: bool, *,
                 llm: LLMClient | None) -> tuple[dict[str, Any], float]:
    """Decision for one agent at `deciding`; returns ({decision, option, method, price_inr, reason}, cost)."""
    verdict, reason, allowed = gate(need, opts, life_event)
    if verdict != "buy" or llm is None:
        o = allowed[0] if (verdict == "buy" and allowed) else None
        return ({"decision": verdict if o is not None or verdict != "buy" else "postpone",
                 "option": o.option_id if o else None, "method": o.method if o else None,
                 "price_inr": o.price_inr if o else None, "reason": reason, "rule": True}, 0.0)
    menu = "\n".join(f"- {o.option_id}: {o.label}, ₹{o.price_inr:,}, pay by {o.method}" for o in allowed)
    prompt = (f"A simulated resident of Indiranagar decides whether to buy a phone now (fictional simulation).\n"
              f"<me>\n{persona_card}\nNeed for a new phone: {need:.2f}\n</me>\nAffordable options (data):\n{menu}\n"
              "Choose decision buy|postpone|not_buying, the option id (one of the list) and the payment method "
              "shown for it, and a one-sentence first-person reason.")
    res = await llm.generate(MODEL_LITE, prompt, PurchaseChoice, purpose="purchase", reasoning="low",
                             max_tokens=120, priority_class="P0")
    c = res.data
    pick = next((o for o in allowed if o.option_id == c.option), allowed[0])
    if c.decision != "buy":
        return {"decision": c.decision, "option": None, "method": None, "price_inr": None,
                "reason": c.reason[:200], "rule": False}, res.usage.cost_usd
    return {"decision": "buy", "option": pick.option_id, "method": pick.method, "price_inr": pick.price_inr,
            "reason": c.reason[:200], "rule": False}, res.usage.cost_usd


def tier_of(option_id: str, products: dict[str, dict[str, Any]]) -> str:
    """Phone tier of an option (products by price)."""
    for b in BASELINE:
        if b["id"] == option_id:
            return str(b["tier"])
    price = int(products.get(option_id, {}).get("price_inr", 20000))
    return "budget" if price < 15000 else "mid" if price < 30000 else "premium" if price < 60000 else "flagship"
