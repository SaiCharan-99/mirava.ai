"""Phase 4: occasions → errands, visit hazard, catalogue recommendations."""

from commerce.occasions import (
    DAY,
    Errand,
    Errands,
    best_for,
    birthday_doy,
    budget_for,
    cfg,
    days_until_birthday,
    default_requirements,
    festival_active,
    plan_errands,
    requirement_phrase,
)
from commerce.visits import visit_kind, visit_probability
from shared.schemas.memory import Belief  # noqa: F401  (import check only)
from shared.schemas.social import Message
from social.store_inquiry import Salesperson, briefing, budget_in

SEED = 7


def day_with_birthday_in(aid: int, n: int) -> int:
    """A sim day on which `aid`'s birthday is exactly n days away."""
    return (birthday_doy(SEED, aid) - n) % 365 + 1


def test_birthdays_are_fixed_and_countdown_is_consistent():
    assert birthday_doy(SEED, 5) == birthday_doy(SEED, 5) and 0 <= birthday_doy(SEED, 5) < 365
    d = day_with_birthday_in(5, 6)
    assert days_until_birthday(SEED, 5, d) == 6 and days_until_birthday(SEED, 5, d + 6) == 0
    assert days_until_birthday(SEED, 5, d + 7) == 364


def test_festival_runs_in_blocks():
    days = [d for d in range(1, 91) if festival_active(d)]
    assert len(days) == 15 and days[:5] == list(range(days[0], days[0] + 5))


def test_budget_follows_income_and_closeness_within_what_they_can_pay():
    rich = {"monthly_income_inr": 150000, "savings_inr": 900000, "credit_card_limit_inr": 300000}
    poor = {"monthly_income_inr": 18000, "savings_inr": 2000, "credit_card_limit_inr": 0}
    assert budget_for(rich, 0.9) > budget_for(poor, 0.9)
    assert budget_for(rich, 0.9) > budget_for(rich, 0.1)
    assert 6000 <= budget_for(poor, 0.1) and budget_for(rich, 1.0) <= 90000


def test_default_requirements_by_age_and_plain_words():
    assert "durable" in default_requirements(10) and "display" in default_requirements(70)
    assert "performance" in default_requirements(20)
    assert requirement_phrase(["camera", "battery"]) == "a good camera, a long-lasting battery"


def world(n_households=60, cond="ok", recent=False):
    members, ages, kids = {}, {}, []
    for h in range(n_households):
        a, b, c = h * 10, h * 10 + 1, h * 10 + 2
        members[f"h{h}"] = [(a, "head"), (b, "spouse"), (c, "child")]
        ages.update({a: 42, b: 40, c: 15})
        kids.append(c)
    return members, ages, kids, cond, recent


def run(day, existing=None, cond="ok", recent=False, student=False):
    members, ages, kids, _, _ = world()
    existing = existing or Errands()
    out = plan_errands(day=day, t=(day - 1) * DAY + 360, seed=SEED, members=members, ages=lambda a: ages[a],
                       closeness=lambda a, b: 0.8, money=lambda a: {"monthly_income_inr": 80000, "savings_inr": 200000,
                                                                    "credit_card_limit_inr": 100000},
                       phone_condition=lambda a: cond if a in kids else "ok", life_recent=lambda a: recent,
                       need=lambda a: 0.2, is_student=lambda a: student, existing=existing)
    return out, existing, kids


def test_gifts_come_from_a_household_adult_for_a_birthday_soon():
    got, kids = [], None
    existing = Errands()
    for d in range(1, 366):                                  # a whole year, daily, like the engine
        out, _, kids = run(d, existing)
        for e in out:
            existing.add(e)
        got += out
    gifts = [e for e in got if e.reason == "gift"]
    assert 5 <= len(gifts) <= 60
    for e in gifts:
        assert e.buyer != e.beneficiary and e.buyer // 10 == e.beneficiary // 10      # someone else in the same household
        assert e.buyer not in kids                                                     # an adult buys
        assert e.budget_inr >= 6000 and e.requirements and e.status == "open" and e.due_t > e.created_t


def test_a_birthday_is_decided_once_never_re_rolled_daily():
    members, ages, kids, _, _ = world(1)
    child = kids[0]
    existing = Errands()
    created = 0
    for d in range(day_with_birthday_in(child, 12), day_with_birthday_in(child, 4) + 1):
        out, existing, _ = run(d, existing)
        for e in out:
            existing.add(e)
        created += sum(1 for e in out if e.beneficiary in kids)
    assert created <= 1                                       # one decision per birthday, however many days the window is open
    again, _, _ = run(day_with_birthday_in(child, 6), existing)
    assert not [e for e in again if e.errand_id in existing.items]


def test_broken_phone_of_a_child_is_replaced_by_an_adult():
    out, _, kids = run(100, cond="cracked", recent=True)
    repl = [e for e in out if e.reason == "replacement"]
    assert len(repl) >= 0.9 * len(kids) and all(e.buyer not in kids for e in repl)   # (a few kids had a birthday errand instead)
    none, _, _ = run(100, cond="ok", recent=True)
    assert not [e for e in none if e.reason == "replacement"]
    stale, _, _ = run(100, cond="cracked", recent=False)
    assert not [e for e in stale if e.reason == "replacement"]


def test_requirements_come_only_from_what_the_beneficiary_said_and_errands_expire():
    errs = Errands()
    errs.add(Errand("e1", buyer=1, beneficiary=2, reason="gift", budget_inr=20000, due_t=1000, created_t=0,
                    requirements=["performance", "camera", "battery"]))
    assert errs.note_requirements(1, 99, ["display"]) is None                 # a different person's wishes don't count
    e = errs.note_requirements(1, 2, ["camera", "display"])
    assert e is not None and e.briefed and e.requirements == ["camera", "display"]
    assert errs.expire(1000 + 2 * DAY) == 0 and errs.expire(1000 + 4 * DAY) == 1 and errs.open_for(1) == []
    back = Errands()
    back.load(errs.to_dict())
    assert back.items["e1"].status == "expired"


OPTS = [{"id": "cheap-cam", "label": "Snap 5", "price_inr": 18000, "specs": {"camera": 0.9, "battery": 0.5, "price_value": 0.8}},
        {"id": "flagship", "label": "Titan X", "price_inr": 95000, "specs": {"camera": 1.0, "battery": 0.9, "price_value": 0.1}},
        {"id": "battery-king", "label": "Volt 6", "price_inr": 15000, "specs": {"camera": 0.3, "battery": 0.95, "price_value": 0.9}}]
MONEY = {"savings_inr": 60000, "credit_card_limit_inr": 0, "emi_eligible": False, "monthly_income_inr": 40000}


def test_best_phone_matches_wants_within_what_can_be_paid():
    assert best_for(["camera"], 20000, OPTS, MONEY)["id"] == "cheap-cam"
    assert best_for(["battery"], 20000, OPTS, MONEY)["id"] == "battery-king"
    assert best_for(["camera"], 120000, OPTS, MONEY)["id"] != "flagship"      # cannot pay 95k from 60k savings
    assert best_for(["camera"], 5000, OPTS, MONEY) is None


def test_visit_hazard_rises_with_need_deadlines_and_sales():
    c = cfg()
    base = dict(need=0.1, curious=False, payday=False, weekend=False, near_store=False, festival=False,
                errand_days_left=None, cfg=c)
    p0 = visit_probability(**base)
    assert p0 < 0.005
    assert visit_probability(**{**base, "need": 0.9}) > p0 + 0.01
    assert visit_probability(**{**base, "festival": True, "weekend": True, "payday": True}) > p0 + 0.02
    assert visit_probability(**{**base, "errand_days_left": 0.5}) >= 0.79
    assert visit_probability(**{**base, "errand_days_left": 9}) < visit_probability(**{**base, "errand_days_left": 2})
    assert visit_probability(**{**base, "need": 1.0, "errand_days_left": 0.1, "festival": True}) <= c["visits"]["cap"]
    assert visit_kind(True) == "errand" and visit_kind(False) == "browse"


def sales(catalog):
    return Salesperson(2, "Ravi", "friendly", "ST-X", "Store X", None, "phones in general", {}, {}, [], catalog)


CAT = [{"product_id": o["id"], "name": o["label"], "price_inr": o["price_inr"], "specs": o["specs"], "stock": 5} for o in OPTS]


def test_budget_is_read_from_what_was_said_aloud():
    assert budget_in("something around 20k please") == 20000
    assert budget_in("my budget is ₹25,000") == 25000
    assert budget_in("under 30000 rupees, no more") == 30000
    assert budget_in("how are you today") is None and budget_in("it has 6000 mAh") == 6000   # (a battery size, only a hint)


def test_salesperson_recommends_from_spoken_wants_and_budget_only():
    said = [Message(session_id="s", seq=0, speaker=1, listener=2, text="I want a good camera, budget around 20k", t=0)]
    text, calls = briefing(sales(CAT), said)
    assert "Snap 5" in text and "Titan X" not in text and any(c.tool == "recommend" for c in calls)
    nothing = [Message(session_id="s", seq=0, speaker=1, listener=2, text="hello", t=0)]
    t2, _ = briefing(sales(CAT), nothing)
    assert "recommended for what they asked" in t2                      # still offers something, with no preference known


def test_social_runtime_learns_requirements_only_from_the_other_persons_debrief():
    from commerce.occasions import Errands as E
    from engine.governor import BudgetGovernor
    from engine.social_rt import SocialRuntime
    from mind.decision import FakeDecision
    from shared.llm import FakeGemini
    from shared.store import MemoryStoreBackend

    s = SocialRuntime(MemoryStoreBackend(), FakeGemini(), FakeDecision(), BudgetGovernor(),
                      [{"a": 1, "b": 2, "kind": "family", "closeness": 0.9, "channel": "both"}])
    s.errands = E()
    s.errands.add(Errand("e1", buyer=1, beneficiary=2, reason="gift", budget_inr=20000, due_t=5000, created_t=0,
                         requirements=["performance"]))
    s.agenda.add(1, "errand_question", 0, target_id=2, weight=0.8)
    s._note_requirements(1, 3, {"requirements": ["a good camera"]})              # a stranger's words: ignored
    assert not s.errands.items["e1"].briefed
    s._note_requirements(1, 2, {"requirements": []})                             # nothing was said: ignored
    assert not s.errands.items["e1"].briefed
    s._note_requirements(1, 2, {"requirements": ["a good camera", "battery that lasts"]})
    e = s.errands.items["e1"]
    assert e.briefed and set(e.requirements) == {"camera", "battery"}
    assert s.agenda.items[1][0].weight == 0.0                                    # the question is answered
