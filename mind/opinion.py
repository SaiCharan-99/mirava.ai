"""Opinion engine (phase 1): attitudes are computed from structured state, not accumulated from model deltas.

Each agent holds, per product, a *perceived* value for each attribute (battery, camera, display, …) built only from
evidence it met (ads, reviews, word of mouth, a store visit, owning it), weighted by how credible the source is to
THAT person. A product is judged against the agent's own phone and the best thing it has seen so far on each
attribute (a reference point), and losses weigh more than gains. Personal weights (income, interests, values, job)
decide what matters. What an agent says aloud can differ from what it privately thinks (ego, loyalty, conformity).

Rules decide the state; the language model only puts it into words. Everything here is deterministic.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from typing import Any

import numpy as np

from commerce.need import affordability, job_dependence
from engine.rng import stream
from population.config import load

_PATTERNS = {
    "battery": r"battery|mah\b|charg|all[- ]day|power ?bank",
    "camera": r"camera|\bmp\b|\d\s?mp\b|photo|selfie|zoom|telephoto|night sight|\blens\b|video",
    "display": r"display|screen|amoled|\boled\b|\bhz\b|brightness|ltpo|promotion",
    "performance": r"\bchip\b|processor|snapdragon|tensor|dimensity|bionic|\bram\b|gaming|\bfast\b|speed|performance|\blag",
    "software": r"software|update|\bios\b|android|gemini|\bai\b|smooth|\bos\b",
    "design": r"design|\bslim\b|titanium|glass|sleek|lightweight|colou?r|finish",
    "price_value": r"price|₹|\bemi\b|offer|\bvalue\b|afford|cheap|discount|\bdeal\b|\bsave\b",
    "brand": r"\bbrand\b|trusted|iconic",
}
ATTR_RE = {a: re.compile(p, re.I) for a, p in _PATTERNS.items()}
_CHIPS = (
    (0.90, ("a19", "a18", "a17", "snapdragon 8", "tensor g5", "dimensity 9", "gen 3", "gen 4", "elite")),
    (0.75, ("tensor g4", "tensor g3", "snapdragon 7", "dimensity 8", "a16")),
    (0.55, ("snapdragon 6", "dimensity 7", "helio g99", "tensor g2")),
    (0.40, ("helio", "snapdragon 4", "unisoc")),
)


def cfg() -> dict[str, Any]:
    """`config/opinion.yaml`."""
    return load("opinion")


def attrs() -> tuple[str, ...]:
    """Attribute names in canonical order."""
    return tuple(cfg()["attributes"])


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Limit x to [lo, hi]."""
    return max(lo, min(hi, x))


def attrs_in(text: str) -> list[str]:
    """Attributes a piece of text talks about (keyword rules), in canonical order."""
    return [a for a in attrs() if ATTR_RE[a].search(text)]


def tier_of_price(price_inr: int) -> str:
    """Phone tier from the price."""
    t = cfg()["tier_price_inr"]
    return "budget" if price_inr < t["budget_max"] else "mid" if price_inr < t["mid_max"] \
        else "premium" if price_inr < t["premium_max"] else "flagship"


def prior_specs(tier: str, brand: str | None = None) -> dict[str, float]:
    """What a phone of this tier (and brand character) is like, per attribute — no evidence needed."""
    m = load("phones_market")["spec_priors"]
    base = dict(m["tier"].get(tier, m["tier"]["mid"]))
    for a, d in (m["brand_adjust"].get(brand or "", {}) or {}).items():
        base[a] = clamp(base[a] + d)
    return base


def phone_specs(phone: dict[str, Any]) -> dict[str, float]:
    """An owned phone's attributes: tier prior + brand, minus wear (cracked screen, weak battery, slow)."""
    out = prior_specs(str(phone.get("tier", "mid")), phone.get("brand"))
    pen = load("phones_market")["condition_penalty"].get(str(phone.get("condition", "ok")), {})
    for a, d in pen.items():
        out[a] = clamp(out[a] - d)
    wear = 1.0 - float(phone.get("battery_health", 1.0))
    out["battery"] = clamp(out["battery"] - 0.3 * wear)
    return out


def heuristic_specs(features: list[str], claims: list[str], price_inr: int, brand: str) -> dict[str, float]:
    """Truth specs for a product from its feature text (offline fallback of the studio's spec extraction)."""
    text = " ".join([*features, *claims]).lower().replace("×", "x")
    out = prior_specs(tier_of_price(price_inr), brand)
    mah = [int(x.replace(",", "")) for x in re.findall(r"(\d[\d,]{3,5})\s?mah", text)]
    if mah:
        out["battery"] = clamp(0.2 + (max(mah) - 3000) / 4000 * 0.8)
    elif re.search(r"all[- ]day|two[- ]day|2[- ]day", text):
        out["battery"] = clamp(out["battery"] + 0.1)
    mps = [int(x) for x in re.findall(r"(\d{2,3})\s?mp", text)]
    if mps:
        out["camera"] = clamp(0.4 + 0.3 * min(1.0, max(mps) / 108)
                              + (0.12 if re.search(r"telephoto|periscope|\dx optical|\dx tele", text) else 0.0)
                              + (0.05 if re.search(r"\bois\b|night sight|stabili", text) else 0.0))
    hz = [int(x) for x in re.findall(r"(\d{2,3})\s?hz", text)]
    if hz:
        h = max(hz)
        out["display"] = clamp((0.4 if h <= 60 else 0.55 if h <= 90 else 0.75 if h <= 120 else 0.85)
                               + (0.1 if re.search(r"amoled|ltpo|oled|promotion", text) else 0.0))
    for score, names in _CHIPS:
        if any(n in text for n in names):
            out["performance"] = score
            break
    yrs = [int(x) for x in re.findall(r"(\d+)\s*years? of [a-z ]*updates", text)]
    if yrs:
        out["software"] = clamp(0.3 + 0.1 * max(yrs))
    if re.search(r"titanium|glass|ceramic|aluminium|slim|sleek", text):
        out["design"] = clamp(out["design"] + 0.1)
    out["price_value"] = clamp(1.0 - min(1.0, price_inr / 130000) ** 0.7)
    out["brand"] = float(cfg()["brand_prestige"].get(brand, out["brand"]))
    return {a: round(out[a], 3) for a in attrs()}


class OpinionEngine:
    """Per-agent weights/traits (from the persona) and per-agent-per-product perceptions (from evidence)."""

    def __init__(self, profiles: list[Any], seed: int, *, phones: list[dict[str, Any]] | None = None,
                 money_fn: Callable[[int], dict[str, Any]] | None = None) -> None:
        self.cfg = cfg()
        self.attrs = attrs()
        self.profiles = profiles
        self.seed = seed
        self.phones = phones
        self.money_fn = money_fn
        n = len(profiles)
        self.W = np.zeros((n, len(self.attrs)))
        self.skeptic = np.zeros(n)
        self.loss_aversion = np.zeros(n)
        self.status = np.zeros(n)
        self.loyalty = np.zeros(n)
        self.conformity = np.zeros(n)
        for i, p in enumerate(profiles):
            self._init_person(i, p)
        self.catalog: dict[str, dict[str, Any]] = {}
        self.perc: dict[int, dict[str, dict[str, list[float]]]] = {}
        self.react: dict[int, dict[str, float]] = {}
        self.heard: dict[int, dict[str, float]] = {}

    # ------------------------------------------------------------------ persona → weights and traits
    def _init_person(self, i: int, p: Any) -> None:
        c = self.cfg["weights"]
        w = {a: float(c["base"]) for a in self.attrs}

        def add(d: dict[str, float] | None) -> None:
            for a, v in (d or {}).items():
                w[a] += float(v)

        pe = p.persona
        for it in pe.interests:
            add(c["interests"].get(it))
        add(c["lifestyle"].get(pe.lifestyle))
        for v in pe.values:
            add(c["values"].get(v))
        add(c["income"].get(p.income_band))
        add(c["job_dependence"].get(job_dependence(p.occupation)))
        noise = stream(self.seed, "opinion_w", int(p.agent_id)).lognormal(0.0, float(c["noise_sigma"]), len(self.attrs))
        vec = np.maximum(float(c["floor"]), np.array([w[a] for a in self.attrs])) * noise
        self.W[i] = vec / vec.sum()
        b = pe.big5
        o, cc, e, ag, ne = (float(b.get(k, 0.5)) for k in "OCEAN")
        self.skeptic[i] = clamp(0.3 + 0.4 * (1 - ag) + 0.2 * cc - 0.1 * o, 0.1, 0.9)
        self.loss_aversion[i] = 1.4 + 1.2 * ne
        rich = p.income_band in ("1-2L", ">2L")
        self.status[i] = clamp(0.25 + 0.35 * (("status" in pe.values) or ("trends" in pe.values)) + 0.25 * e
                               + 0.15 * rich)
        own = self._own_brand(i)
        like = (float(pe.brand_attitudes.get(own, 0.0)) + 1) / 2 if own else 0.5
        self.loyalty[i] = clamp(0.3 * cc + 0.3 * min(1.0, p.age / 80) + 0.4 * like)
        self.conformity[i] = clamp(0.5 * ag + 0.3 * ne + 0.2 * (1 - o))

    def weights(self, aid: int) -> dict[str, float]:
        """This person's weight per attribute (sums to 1)."""
        return {a: round(float(self.W[aid, k]), 4) for k, a in enumerate(self.attrs)}

    def traits(self, aid: int) -> dict[str, float]:
        """This person's opinion traits."""
        return {"skepticism": float(self.skeptic[aid]), "loss_aversion": float(self.loss_aversion[aid]),
                "status_drive": float(self.status[aid]), "brand_loyalty": float(self.loyalty[aid]),
                "conformity": float(self.conformity[aid])}

    # ------------------------------------------------------------------ products
    def set_catalog(self, products: Iterable[Any]) -> None:
        """Live products (Product models) → catalog {id: name, brand, price, tier, specs}; baselines are always known."""
        cat: dict[str, dict[str, Any]] = {}
        for b in load("phones_market")["baseline_market"]:
            cat[b["id"]] = {"name": b["label"], "brand": None, "price": int(b["price_inr"]), "tier": b["tier"],
                            "specs": prior_specs(b["tier"], None), "baseline": True}
        for p in products:
            specs = p.specs or heuristic_specs(p.features, p.claims, p.price_inr, p.brand)
            cat[p.product_id] = {"name": p.name, "brand": p.brand, "price": int(p.price_inr),
                                 "tier": tier_of_price(int(p.price_inr)), "specs": {a: float(specs.get(a, 0.5)) for a in self.attrs},
                                 "baseline": False}
        self.catalog = cat
        for per in self.perc.values():                        # forget products that no longer exist
            for pid in [x for x in per if x not in cat]:
                del per[pid]

    def _phone(self, aid: int) -> dict[str, Any]:
        if self.phones is not None:
            return self.phones[aid]
        return dict(self.profiles[aid].possessions.get("phone", {}))

    def _own_brand(self, aid: int) -> str | None:
        ph = self.profiles[aid].possessions.get("phone") if self.phones is None else self.phones[aid]
        return (ph or {}).get("brand")

    def own_specs(self, aid: int) -> dict[str, float]:
        """My current phone, per attribute."""
        return phone_specs(self._phone(aid))

    def owns(self, aid: int, pid: str) -> bool:
        """Do I use this product right now?"""
        c = self.catalog.get(pid)
        return c is not None and self._phone(aid).get("model_label") == c["name"]

    # ------------------------------------------------------------------ evidence → perceptions
    def _perc(self, aid: int, pid: str) -> dict[str, list[float]]:
        per = self.perc.setdefault(aid, {})
        if pid not in per:
            cat = self.catalog.get(pid, {})
            base = prior_specs(cat.get("tier", "mid"), cat.get("brand"))   # a guess from tier and brand, not the truth
            per[pid] = {a: [float(base[a]), float(self.cfg["prior_conf"])] for a in self.attrs}
        return per[pid]

    def credibility(self, aid: int, source: str, closeness: float = 0.0, strength: float = 1.0) -> float:
        """How far one piece of evidence from `source` moves THIS person."""
        c = self.cfg["credibility"]
        base = float(c["word_of_mouth_base"]) + float(c["word_of_mouth_per_closeness"]) * closeness \
            if source == "word_of_mouth" else float(c.get(source, c["ad"]))
        return clamp(base * (1 - float(self.cfg["skepticism_discount"]) * float(self.skeptic[aid])) * strength, 0.0, 1.0)

    def evidence(self, aid: int, pid: str, attributes: dict[str, float] | Iterable[str] | None, source: str, *,
                 closeness: float = 0.0, strength: float = 1.0) -> bool:
        """Update perceptions of `pid` from one piece of evidence; returns False for unknown products.

        `attributes` is {attr: value} (what was claimed or observed), or just the attributes covered (the value is then
        the truth, plus optimism for ads), or None (everything: using / handling the product)."""
        cat = self.catalog.get(pid)
        if cat is None:
            return False
        truth = cat["specs"]
        if attributes is None:
            vals = {a: truth[a] for a in self.attrs}
        elif isinstance(attributes, dict):
            vals = {a: clamp(float(v)) for a, v in attributes.items() if a in truth}
        else:
            vals = {a: truth[a] for a in attributes if a in truth}
        if source == "ad":
            vals = {a: clamp(v + float(self.cfg["optimism"])) for a, v in vals.items()}
        cred = self.credibility(aid, source, closeness, strength)
        per = self._perc(aid, pid)
        if source != "word_of_mouth":                         # listings, ads and reviews state the price
            per["price_value"] = [truth["price_value"], max(per["price_value"][1], float(self.cfg["price_known_conf"]))]
        for a, v in vals.items():
            mean, conf = per[a]
            per[a][0] = clamp(mean + cred * (1 - conf * 0.5) * (v - mean))
            per[a][1] = 1 - (1 - conf) * (1 - cred)
        return True

    def add_reaction(self, aid: int, pid: str, delta: float, clamp_each: float = 0.1) -> None:
        """The language model's emotional reaction (small, capped) on top of the computed attitude."""
        lim = float(self.cfg["reaction_clamp"])
        d = max(-clamp_each, min(clamp_each, float(delta)))
        r = self.react.setdefault(aid, {})
        r[pid] = max(-lim, min(lim, r.get(pid, 0.0) + d))

    def aware_of(self, aid: int, pid: str) -> bool:
        """Has this agent met any evidence about the product?"""
        return pid in self.perc.get(aid, {})

    # ------------------------------------------------------------------ valuation
    def _afford(self, aid: int, pid: str) -> float:
        price = int(self.catalog[pid]["price"])
        money = self.money_fn(aid) if self.money_fn else self.profiles[aid].money.model_dump()
        return affordability(price, money)[0]

    def _reference(self, aid: int, pid: str) -> dict[str, float]:
        """My yardstick per attribute: my phone, lifted toward the best I have seen elsewhere."""
        own = self.own_specs(aid)
        alpha, minc = float(self.cfg["reference_alpha"]), float(self.cfg["reference_min_conf"])
        ref = dict(own)
        for other, per in self.perc.get(aid, {}).items():
            if other == pid:
                continue
            for a in self.attrs:
                mean, conf = per[a]
                if conf >= minc and mean > own[a]:
                    ref[a] = max(ref[a], own[a] + alpha * (mean - own[a]))
        return ref

    def _terms(self, aid: int, pid: str) -> dict[str, float]:
        """Per-attribute felt difference (loss-averse) between what I perceive and my yardstick."""
        per = self._perc(aid, pid)
        ref = self._reference(aid, pid)
        lam = float(self.loss_aversion[aid])
        pen = float(self.cfg["unaffordable_penalty"]) * (1 - self._afford(aid, pid))
        known = float(self.cfg["known_conf"])
        out: dict[str, float] = {}
        for a in self.attrs:
            if per[a][1] < known:                              # I don't know this one: no felt difference
                out[a] = 0.0
                continue
            x = per[a][0] - (pen if a == "price_value" else 0.0) - ref[a]
            out[a] = x if x >= 0 else lam * x
        return out

    def private_attitude(self, aid: int, pid: str) -> float:
        """What I really think of the product, −1..1 (0 when I know nothing about it)."""
        if pid not in self.catalog or not self.aware_of(aid, pid):
            return 0.0
        terms = self._terms(aid, pid)
        v = sum(float(self.W[aid, k]) * terms[a] for k, a in enumerate(self.attrs))
        att = math.tanh(float(self.cfg["attitude_scale"]) * v) + self.react.get(aid, {}).get(pid, 0.0)
        if self.owns(aid, pid):
            att += float(self.cfg["owner_bonus"]["private"])
        return clamp(att, -1.0, 1.0)

    attitude = private_attitude

    def fit(self, aid: int, pid: str) -> float:
        """How much better the product is than my own phone on what matters to me (0 = no better, 1 = far better).
        Only what I actually know counts, so merely being aware of a phone adds nothing."""
        per = self._perc(aid, pid)
        own = self.own_specs(aid)
        known = float(self.cfg["known_conf"])
        gain = sum(float(self.W[aid, k]) * max(0.0, per[a][0] - own[a]) for k, a in enumerate(self.attrs)
                   if per[a][1] >= known)
        return clamp(float(self.cfg["fit_scale"]) * gain)

    def attribute_view(self, aid: int, pid: str) -> dict[str, dict[str, float]]:
        """{attr: {perceived, conf, diff}}: this agent's own view only."""
        per = self._perc(aid, pid)
        terms = self._terms(aid, pid)
        return {a: {"perceived": round(per[a][0], 3), "conf": round(per[a][1], 3), "diff": round(terms[a], 3)}
                for a in self.attrs}

    # ------------------------------------------------------------------ comparison → words
    def compare(self, aid: int, pid: str) -> dict[str, list[tuple[str, str]]]:
        """{better: [(attr, vs)], worse: [(attr, vs)]} for attributes I know about, against my phone and the best
        alternative I have perceived. `vs` is 'my phone' or the other product's id."""
        per = self._perc(aid, pid)
        own = self.own_specs(aid)
        better: list[tuple[str, str]] = []
        worse: list[tuple[str, str]] = []
        for a in self.attrs:
            mean, conf = per[a]
            if conf < 0.2 or a == "brand":
                continue
            best_other, best_v = "my phone", own[a]
            for other, op in self.perc.get(aid, {}).items():
                if other != pid and op[a][1] >= 0.3 and op[a][0] > best_v:
                    best_other, best_v = other, op[a][0]
            gap = mean - best_v
            if gap >= 0.08:
                better.append((a, "my phone" if best_other == "my phone" else best_other))
            elif gap <= -0.08:
                worse.append((a, best_other))
        return {"better": better, "worse": worse}

    def _name(self, pid: str) -> str:
        return "my phone" if pid == "my phone" else str(self.catalog.get(pid, {}).get("name", pid))

    def reasons(self, aid: int, pid: str) -> tuple[list[str], list[str]]:
        """(reasons_for, reasons_against) as short phrases, from this agent's own comparison (≤ 3 each)."""
        cmp = self.compare(aid, pid)
        w = self.weights(aid)
        pro = sorted(cmp["better"], key=lambda x: -w[x[0]])
        con = sorted(cmp["worse"], key=lambda x: -w[x[0]])
        f = [f"{a.replace('_', ' ')} beats {self._name(v)}" for a, v in pro[:3]]
        g = [f"{a.replace('_', ' ')} worse than {self._name(v)}" for a, v in con[:3]]
        if self._afford(aid, pid) < 0.5:
            g = (g + ["out of my budget"])[:3]
        return f, g

    def brief(self, aid: int, pid: str) -> str:
        """First-person summary of how I see one product (own perceptions only; goes into my prompts)."""
        if pid not in self.catalog or not self.aware_of(aid, pid):
            return ""
        f, g = self.reasons(aid, pid)
        att = self.private_attitude(aid, pid)
        mood = "like it" if att > 0.25 else "am put off by it" if att < -0.25 else "am not sure about it"
        bits = [f"{self._name(pid)}: I {mood}"]
        if f:
            bits.append("good: " + "; ".join(f))
        if g:
            bits.append("not good: " + "; ".join(g))
        return " — ".join(bits)

    def brief_many(self, aid: int, pids: Iterable[str]) -> str:
        """Briefs for several products, one per line (empty ones skipped)."""
        return "\n".join(b for b in (self.brief(aid, p) for p in pids) if b)

    def top_claims(self, aid: int, pid: str, n: int = 2) -> list[tuple[str, str]]:
        """The (attribute, '+'/'-') I would mention first when talking about the product (strongest felt differences)."""
        terms = self._terms(aid, pid)
        per = self._perc(aid, pid)
        ranked = sorted((a for a in self.attrs if per[a][1] >= 0.2 and a != "brand"),
                        key=lambda a: -abs(terms[a]) * float(self.W[aid, self.attrs.index(a)]))
        return [(a, "+" if terms[a] >= 0 else "-") for a in ranked[:n]]

    # ------------------------------------------------------------------ what I say aloud
    def hear_stance(self, aid: int, pid: str, stance: float) -> None:
        """Remember what someone told me about the product (feeds conformity)."""
        self.heard.setdefault(aid, {})[pid] = clamp(stance, -1.0, 1.0)

    def expressed(self, aid: int, pid: str, closeness: float = 0.0) -> tuple[float, str]:
        """(public attitude, private note on any gap): ego, loyalty, ownership and conformity shape what I say."""
        e = self.cfg["expressed"]
        priv = self.private_attitude(aid, pid)
        pub = priv
        notes: list[str] = []
        cat = self.catalog.get(pid)
        if cat is None:
            return priv, ""
        premium = cat["tier"] in ("premium", "flagship")
        afford = self._afford(aid, pid)
        status = float(self.status[aid])
        own_brand = self._own_brand(aid)
        if self.owns(aid, pid):
            pub += float(self.cfg["owner_bonus"]["public"]) - float(self.cfg["owner_bonus"]["private"])
            notes.append("I own it, so I defend it")
        elif premium and afford < 0.5 and status > 0.45:
            pub -= float(e["sour_grapes"]) * status
            notes.append("I can't afford it and I'd rather not admit it, so I talk it down")
        elif premium and afford >= 0.8 and status > 0.55:
            pub += float(e["status_flex"]) * status
            notes.append("it's a status phone I can afford, so I play it up")
        brand = cat.get("brand")
        if brand and own_brand:
            loyal = float(self.loyalty[aid])
            if brand == own_brand:
                pub += float(e["tribal_own"]) * loyal
                notes.append("it's my own brand")
            elif loyal > 0.5:
                pub -= float(e["tribal_rival"]) * loyal * 0.5
                notes.append("I stick up for my brand")
        heard = self.heard.get(aid, {}).get(pid)
        if heard is not None and closeness > 0:
            pub += float(e["conformity_pull"]) * float(self.conformity[aid]) * closeness * (heard - pub)
            notes.append("I tend to agree with people close to me")
        pub = clamp(pub, -1.0, 1.0)
        note = ("" if abs(pub - priv) < 0.05 else f"privately {priv:+.2f} but I'd say {pub:+.2f}: " + "; ".join(notes))
        return pub, note

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form (rounded)."""
        return {"perc": {str(a): {p: {k: [round(v[0], 3), round(v[1], 3)] for k, v in d.items()}
                                  for p, d in per.items()} for a, per in self.perc.items()},
                "react": {str(a): {p: round(v, 3) for p, v in r.items()} for a, r in self.react.items()},
                "heard": {str(a): {p: round(v, 3) for p, v in r.items()} for a, r in self.heard.items()}}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict (missing keys are fine)."""
        self.perc = {int(a): {p: {k: [float(v[0]), float(v[1])] for k, v in dd.items()} for p, dd in per.items()}
                     for a, per in (d.get("perc") or {}).items()}
        self.react = {int(a): {p: float(v) for p, v in r.items()} for a, r in (d.get("react") or {}).items()}
        self.heard = {int(a): {p: float(v) for p, v in r.items()} for a, r in (d.get("heard") or {}).items()}
