"""Word of mouth without a model: the teller's strongest agenda item reaches the listener (phase 2a).

Used for every conversation the budget could not render, and for phone chats. What is told is derived from the
teller's own state (opinion engine claims, agenda item); what the listener keeps depends on how close they are and how
credible the teller is to THEM (opinion engine credibility). Rules only; deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.rng import stream
from mind.opinion import OpinionEngine
from population.config import load
from social.agenda import Agenda, AgendaItem

PRAISE, CRITIC = 0.78, 0.25            # perceived value of an attribute the teller praised / criticised


@dataclass
class Told:
    """What one telling did (for events and memories)."""

    teller: int
    listener: int
    kind: str
    product_id: str | None
    attrs: dict[str, float]
    memory: str
    hint: str
    about: str = ""


def _pick(seed: int, key: str, options: list[str], t: int, a: int, b: int) -> str:
    rng = stream(seed, "wom", key, t, a, b)
    return options[int(rng.integers(len(options)))]


def tell(agenda: Agenda, opinion: OpinionEngine | None, teller: int, listener: int, closeness: float, t: int, *,
         name_of: Any, product_name: Any, seed: int = 0) -> Told | None:
    """The teller brings up their strongest unheard item; the listener's perceptions and agenda update."""
    item: AgendaItem | None = agenda.pick_to_tell(teller, listener, t)
    tpl = load("wom_templates")
    who = str(name_of(teller))
    if item is None:
        return Told(teller, listener, "general", None, {}, _pick(seed, "general", tpl["general"], t, teller, listener)
                    .format(teller=who), "")
    item.told.append(listener)
    pid = item.product_id
    attrs: dict[str, float] = {}
    if pid and opinion is not None and pid in opinion.catalog:
        for a, sign in opinion.top_claims(teller, pid, 2):
            attrs[a] = PRAISE if sign == "+" else CRITIC
        pname = str(product_name(pid))
        if attrs:
            a0, v0 = next(iter(attrs.items()))
            kind_key = "praise" if v0 >= 0.5 else "criticism"
            text = _pick(seed, kind_key, tpl[kind_key], t, teller, listener).format(
                teller=who, product=pname, attr=a0.replace("_", " "))
        else:
            text = _pick(seed, "mention", tpl["mention"], t, teller, listener).format(teller=who, product=pname)
        # the listener now knows of it; credible tellers move perceptions, and a liked product gets passed on
        opinion.evidence(listener, pid, attrs or [], "word_of_mouth", closeness=closeness)
        if opinion.private_attitude(listener, pid) > 0.2:
            agenda.add(listener, "opinion", t, hint=pname, product_id=pid, weight=0.3)
    else:
        key = {"phone_trouble": "trouble", "purchase": "purchase", "store_visit": "store_visit",
               "survey_invite": "survey", "got_goodies": "survey"}.get(item.kind, "general")
        text = _pick(seed, key, tpl[key], t, teller, listener).format(teller=who, hint=item.public_hint or "lately")
        if item.kind == "phone_trouble":
            agenda.add(listener, "life_news", t, hint=f"{who}'s phone", weight=0.25)
    return Told(teller, listener, item.kind, pid, attrs, text, item.public_hint, item.about)
