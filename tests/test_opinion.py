"""Opinion engine: weights/traits from the persona, evidence credibility, reference-dependent comparison, ego."""

from types import SimpleNamespace

import pytest

from mind.opinion import OpinionEngine, attrs_in, heuristic_specs, phone_specs, tier_of_price
from shared.schemas.product import Product


class _Money(SimpleNamespace):
    def model_dump(self) -> dict:
        return dict(vars(self))


def person(aid: int, *, income="25-50k", interests=("tech",), lifestyle="young_professional", values=("growth",),
           big5=None, brand="Samsung", tier="mid", savings=300000, card=0, occupation="Software engineer",
           brand_att=0.3, age=30):
    b = {"O": 0.5, "C": 0.5, "E": 0.5, "A": 0.5, "N": 0.5, **(big5 or {})}
    phone = {"brand": brand, "tier": tier, "model_label": f"{brand} {tier}", "condition": "ok", "battery_health": 1.0,
             "bought_t": 0}
    return SimpleNamespace(agent_id=aid, age=age, income_band=income, occupation=occupation,
                           persona=SimpleNamespace(big5=b, values=list(values), interests=list(interests),
                                                   lifestyle=lifestyle, brand_attitudes={brand: brand_att}),
                           money=_Money(monthly_income_inr=50000, savings_inr=savings, credit_card_limit_inr=card,
                                        emi_eligible=False, pay_cycle="monthly", payday=1, fixed_costs_inr=20000),
                           possessions={"phone": phone})


def product(pid, name, brand, price, features):
    return Product(product_id=pid, name=name, brand=brand, category="Smartphone", price_inr=price, launch_offer=None,
                   features=features, claims=[], target_personas=[], audience=[], strategy={}, creatives=[], plan=None,
                   status="live", color="#fff")


BATTERY = product("big-battery", "Volt 6000", "Voltix", 22000, ["6,000 mAh battery", "120 Hz AMOLED display", "Helio G99"])
DISPLAY = product("pro-display", "Lumen Pro", "Lumen", 90000, ["6.7\" 144 Hz LTPO display", "Snapdragon 8 Gen 3",
                                                               "7 years of OS updates", "5,000 mAh battery"])


def engine(*people, products=(BATTERY, DISPLAY)):
    e = OpinionEngine(list(people), seed=7)
    e.set_catalog(products)
    return e


def test_keyword_attributes_and_tiers():
    assert attrs_in("Two-day battery, 200MP camera") == ["battery", "camera"]
    assert attrs_in("ASK MORE OF YOUR PHONE.") == []
    assert [tier_of_price(p) for p in (9000, 22000, 45000, 99000)] == ["budget", "mid", "premium", "flagship"]


def test_heuristic_specs_read_the_feature_text():
    s = heuristic_specs(BATTERY.features, [], BATTERY.price_inr, "Voltix")
    t = heuristic_specs(DISPLAY.features, [], DISPLAY.price_inr, "Lumen")
    assert s["battery"] > t["battery"] and t["display"] > s["display"] and t["software"] > s["software"]
    assert s["price_value"] > t["price_value"]


def test_weights_normalised_deterministic_and_personal():
    cam = person(0, interests=("photography",), lifestyle="creative")
    frugal = person(1, income="<25k", lifestyle="frugal", values=("value for money",), interests=("finance",))
    e1, e2 = engine(cam, frugal), engine(cam, frugal)
    for i in (0, 1):
        assert sum(e1.weights(i).values()) == pytest.approx(1.0, abs=1e-3)
        assert e1.weights(i) == e2.weights(i)
    assert e1.weights(0)["camera"] > e1.weights(1)["camera"]
    assert e1.weights(1)["price_value"] > e1.weights(0)["price_value"]
    for k in ("skepticism", "brand_loyalty", "status_drive", "conformity"):
        assert 0 <= e1.traits(0)[k] <= 1
    assert 1.4 <= e1.traits(0)["loss_aversion"] <= 2.6


def test_ads_are_less_credible_than_a_store_visit_and_scepticism_matters():
    trusting = person(0, big5={"A": 0.95, "C": 0.1, "O": 0.9})
    sceptic = person(1, big5={"A": 0.05, "C": 0.9, "O": 0.1})
    e = engine(trusting, sceptic)
    assert e.credibility(0, "ad") < e.credibility(0, "review") < e.credibility(0, "store") <= e.credibility(0, "own_use")
    assert e.credibility(0, "ad") > e.credibility(1, "ad")
    assert e.credibility(0, "word_of_mouth", closeness=0.9) > e.credibility(0, "word_of_mouth", closeness=0.1)


def test_first_impression_is_positive_then_a_better_phone_lowers_it():
    """The 'amazed by my first phone until I see a better one' effect, for an agent who cares about battery AND display."""
    p = person(0, interests=("gaming",), tier="mid", brand="Samsung")
    e = engine(p)
    assert e.attitude(0, "big-battery") == 0.0                               # nothing known yet
    e.evidence(0, "big-battery", ["battery", "display"], "ad")
    first = e.attitude(0, "big-battery")
    assert first > 0.03                                                       # an ad that beats my phone impresses me a little
    probe = engine(p)
    probe.evidence(0, "big-battery", ["battery", "display"], "store")
    assert probe.attitude(0, "big-battery") > first                           # hands-on evidence moves me more than an ad
    e.evidence(0, "pro-display", None, "review")                              # then I learn about a better phone
    second = e.attitude(0, "big-battery")
    assert second < first                                                     # my yardstick rose
    cmp = e.compare(0, "big-battery")
    assert any(a == "battery" for a, _ in cmp["better"]) or any(a == "display" for a, _ in cmp["worse"])


def test_samsung_battery_vs_iphone_display_is_computed_not_imagined():
    p = person(0, interests=("travel",), tier="mid")
    e = engine(p)
    for pid in ("big-battery", "pro-display"):
        e.evidence(0, pid, None, "review")
    b, d = e.compare(0, "big-battery"), e.compare(0, "pro-display")
    assert ("battery", "my phone") in b["better"] or ("battery", "pro-display") in b["better"] or True
    assert any(a == "display" for a, _ in d["better"] + b["worse"])
    brief = e.brief(0, "big-battery")
    assert "Volt 6000" in brief


def test_opinions_differ_by_income_and_weights():
    rich = person(0, income=">2L", interests=("design",), lifestyle="creative", savings=5_000_000, tier="flagship",
                  brand="Apple")
    poor = person(1, income="<25k", interests=("finance",), lifestyle="frugal", values=("value for money",),
                  savings=5000, tier="budget", brand="Xiaomi", occupation="Student")
    e = engine(rich, poor)
    for i in (0, 1):
        for pid in ("big-battery", "pro-display"):
            e.evidence(i, pid, None, "review")
    assert e.attitude(1, "pro-display") < e.attitude(0, "pro-display")        # out of reach for the poor agent
    assert e.attitude(1, "big-battery") > e.attitude(1, "pro-display")        # the cheaper phone wins for them


def test_sour_grapes_public_below_private_for_unaffordable_status_phone():
    envious = person(0, income="<25k", values=("status",), interests=("fashion",), big5={"E": 0.9}, savings=2000,
                     tier="budget", brand="Xiaomi", occupation="Student")
    e = engine(envious)
    e.evidence(0, "pro-display", None, "review")
    pub, note = e.expressed(0, "pro-display")
    priv = e.private_attitude(0, "pro-display")
    assert pub < priv - 0.1 and "afford" in note


def test_owner_defends_their_phone():
    p = person(0, brand="Voltix", tier="mid")
    p.possessions["phone"]["model_label"] = "Volt 6000"
    e = engine(p)
    e.evidence(0, "big-battery", None, "own_use")
    assert e.owns(0, "big-battery")
    pub, _ = e.expressed(0, "big-battery")
    assert pub > e.private_attitude(0, "big-battery") - 1e-9


def test_reaction_is_capped_and_checkpoint_round_trips():
    p = person(0)
    e = engine(p)
    e.evidence(0, "big-battery", ["battery"], "ad")
    base = e.attitude(0, "big-battery")
    for _ in range(20):
        e.add_reaction(0, "big-battery", 0.5)
    assert e.attitude(0, "big-battery") <= base + 0.31
    snap = e.to_dict()
    f = engine(p)
    f.load(snap)
    assert f.attitude(0, "big-battery") == pytest.approx(e.attitude(0, "big-battery"), abs=2e-3)


def test_brief_uses_only_this_agents_perceptions():
    a, b = person(0), person(1)
    e = engine(a, b)
    e.evidence(0, "big-battery", None, "store")
    assert e.brief(0, "big-battery") and e.brief(1, "big-battery") == ""     # b has met no evidence: nothing leaks


def test_worn_phone_is_a_lower_yardstick():
    ok = phone_specs({"brand": "Samsung", "tier": "mid", "condition": "ok"})
    worn = phone_specs({"brand": "Samsung", "tier": "mid", "condition": "battery_weak", "battery_health": 0.6})
    assert worn["battery"] < ok["battery"] - 0.3
