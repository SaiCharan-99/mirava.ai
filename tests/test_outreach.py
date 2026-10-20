"""Phase 5: how a survey reaches people and who comes (pure rules)."""

import pytest

from engine.rng import stream
from engine.survey.outreach import (
    DAY,
    attend_propensity,
    eta_minutes,
    incentive_value,
    leave_buffer,
    next_session_start,
    no_show_probability,
    reach_share,
    sample_panel,
)
from shared.schemas.survey import Goodie, Incentive, Question, Survey

FEED = [[7 * 60 + 30, 20, "instagram"], [13 * 60, 15, "community"], [21 * 60, 40, "youtube"]]


def test_a_message_is_read_at_the_next_phone_session_not_instantly():
    t = 2 * DAY + 8 * 60                                      # day 3, 08:00
    assert next_session_start(FEED, t) == 2 * DAY + 13 * 60
    assert next_session_start(FEED, t, app="community") == 2 * DAY + 13 * 60
    assert next_session_start(FEED, 2 * DAY + 21 * 60 + 1) == 3 * DAY + 7 * 60 + 30       # tomorrow morning
    assert next_session_start(FEED, 2 * DAY + 7 * 60 + 28) == 2 * DAY + 13 * 60            # needs ≥ 5 min of notice
    assert next_session_start([], t) == 3 * DAY + 8 * 60                                   # no phone habit: tomorrow 08:00


def test_panel_sample_is_stratified_seeded_and_excludes_the_already_reached():
    pool = list(range(200))
    ages = {a: 20 if a < 120 else 55 for a in pool}
    s1 = sample_panel(pool, 40, ages, 7, "sv", set())
    assert s1 == sample_panel(pool, 40, ages, 7, "sv", set()) and len(s1) == 40
    young = sum(1 for a in s1 if ages[a] == 20)
    assert 20 <= young <= 28                                  # ≈ 60% of the sample, like the pool
    s2 = sample_panel(pool, 40, ages, 7, "sv", set(s1))
    assert not set(s1) & set(s2)
    assert sample_panel(pool, 500, ages, 7, "sv", set(s1)) == sorted(set(pool) - set(s1))


def inc(cash=0, *g):
    return Incentive(cash_inr=cash, goodies=list(g), note="")


def test_the_same_reward_means_more_to_someone_with_less_money():
    low, high = 15000, 200000
    assert incentive_value(inc(500), low, [], 0.5) > 3 * incentive_value(inc(500), high, [], 0.5)
    assert incentive_value(inc(0), low, [], 0.5) == 0.0
    assert 0 <= incentive_value(inc(5000, Goodie(kind="voucher", label="v", value_inr=2000)), low, [], 0.5) <= 1.0


def test_goodies_appeal_by_interests_and_personality():
    ear = Goodie(kind="accessory", label="earbuds", value_inr=1500)
    assert incentive_value(inc(0, ear), 40000, ["gadgets"], 0.5) > incentive_value(inc(0, ear), 40000, ["gardening"], 0.5)
    merch = Goodie(kind="merch", label="tote", value_inr=400)
    assert incentive_value(inc(0, merch), 40000, [], 0.9) > incentive_value(inc(0, merch), 40000, [], 0.1)
    trial = Goodie(kind="product_trial", label="try it", value_inr=800)
    assert incentive_value(inc(0, trial), 40000, [], 0.5, interested_in_product=True) > incentive_value(inc(0, trial), 40000, [], 0.5)


BASE = dict(interest=0.4, free=0.8, extraversion=0.5, openness=0.5, incentive=0.3, channel="panel", closeness=0.0,
            dist_m=600, fatigue=False, job_high=False)


def p(**kw):
    return attend_propensity(**{**BASE, **kw})


def test_who_says_yes():
    assert p(incentive=0.9) > p(incentive=0.0) + 0.2
    assert p(interest=0.9) > p(interest=0.1)
    assert p(free=1.0) > p(free=0.25)
    assert p(dist_m=2400) < p(dist_m=100)
    assert p(fatigue=True) < p() - 0.2 and p(job_high=True) < p()
    assert p(channel="word_of_mouth", closeness=0.9) > p(channel="store_flyer")
    assert p(channel="word_of_mouth", closeness=0.9) > p(channel="word_of_mouth", closeness=0.1)
    assert 0.02 <= p(interest=0, free=0, incentive=0, fatigue=True, dist_m=9000) and p(interest=1, incentive=1, free=1) <= 0.95


def test_getting_there_takes_the_time_their_transport_takes():
    assert eta_minutes(500, "car") == eta_minutes(500, "walk")              # short trips are walked
    assert eta_minutes(3000, "two_wheeler") < eta_minutes(3000, "bus") < eta_minutes(1000, "walk") * 4
    assert eta_minutes(3000, "metro") < eta_minutes(3000, "walk") + 1000 and eta_minutes(1, "walk") >= 1


def test_careful_people_leave_early_careless_ones_cut_it_fine():
    careful = [leave_buffer(0.9, stream(1, "b", i)) for i in range(40)]
    careless = [leave_buffer(0.1, stream(1, "b", i)) for i in range(40)]
    assert min(careful) >= 5 and max(careful) <= 10
    assert max(careless) <= 0 and min(careless) >= -10 and min(careless) < 0


def test_no_show_odds():
    base = no_show_probability(0.06, 0.9, False, 200)
    assert no_show_probability(0.06, 0.1, False, 200) > base
    assert no_show_probability(0.06, 0.9, True, 200) > base + 0.1
    assert no_show_probability(0.06, 0.9, False, 3000) > base
    assert no_show_probability(0.5, 0.0, True, 9000) <= 0.6


def test_reach_grows_with_channels():
    assert reach_share(["panel"], 40, 300) == pytest.approx(0.4, abs=0.01)
    assert reach_share(["panel", "community", "word_of_mouth", "store_flyer"], 40, 300) > 0.6
    assert reach_share([], 40, 300) == 0.0 and reach_share(["panel"], 100, 50) == 1.0


def test_survey_schema_keeps_legacy_fields_in_step():
    q = [Question.model_validate({"question_id": "q1", "text": "Which one?", "type": "single", "options": ["a", "b"]})]
    s = Survey(survey_id="s", title="t", mode="survey", product_id="pixel-10a", questions=q, max_participants=5,
               incentive_inr=300)
    # an old doc's bare incentive_inr is ignored: people get the default goodies, no cash
    assert s.product_ids == ["pixel-10a"] and s.incentive.cash_inr == 0 and set(s.channels) >= {"panel", "community"}
    assert [g.label for g in s.incentive.goodies] == ["Mirava goodie bag", "Coffee at a café nearby", "Snacks at the lounge"]
    s2 = Survey(survey_id="s", title="t", mode="survey", product_ids=["a", "b"], questions=q, max_participants=5,
                incentive=Incentive(cash_inr=700, goodies=[Goodie(kind="food", label="lunch", value_inr=250)], note=""))
    assert s2.product_id == "a" and s2.incentive_inr == 700
    with pytest.raises(ValueError):
        Survey(survey_id="s", title="t", mode="survey", product_ids=list("abcdef"), questions=q, max_participants=5)
