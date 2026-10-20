"""Phase 2d: who texts whom, and planned meetups."""

from population.config import load
from social.meetups import FREE_ACTS, Meetup, is_free, plan_meetups
from social.remote import friends_online, pick_partner, wants_to_text

R = load("social")["remote"]
M = load("social")["meetups"]


def test_only_online_ties_can_text_strongest_first():
    rel = {(1, 2): {"kind": "friend", "channel": "both", "closeness": 0.4},
           (1, 3): {"kind": "family", "channel": "online", "closeness": 0.9},
           (1, 4): {"kind": "neighbour", "channel": "in_person", "closeness": 0.5},
           (1, 5): {"kind": "follower", "channel": "online", "closeness": 0.2},
           (2, 6): {"kind": "colleague", "channel": "in_person", "closeness": 0.5}}
    f = friends_online(rel)
    assert [o for o, _ in f[1]] == [3, 2] and 4 not in dict(f[1]) and 5 not in dict(f[1]) and 6 not in dict(f.get(2, []))


def test_texting_needs_a_reason_and_the_right_type():
    assert wants_to_text(0.8, 0.9, 0.9, 0.05, R)                # lots to say, chatty
    assert not wants_to_text(0.2, 0.9, 0.9, 0.05, R)            # nothing on my mind and not lonely
    assert wants_to_text(0.0, 0.1, 0.9, 0.05, R)                # lonely counts as a reason
    assert not wants_to_text(0.8, 0.9, 0.1, 0.6, R)             # reserved and the draw says no


def test_partner_choice_is_weighted_by_closeness_and_availability():
    opts = [(1, 0.9), (2, 0.1), (3, 0.5)]
    assert pick_partner(opts, {2}, 0.5) == 2 and pick_partner(opts, set(), 0.5) is None
    picks = [pick_partner(opts, {1, 2, 3}, i / 200) for i in range(200)]
    assert picks.count(1) > picks.count(3) > picks.count(2)


def plan(*blocks):
    return [{"s": s, "e": e, "act": act, "place": place} for s, e, act, place in blocks]


def test_free_check_blocks_work_and_offmap():
    p = plan((0, 1110, "work", "P-1"), (1110, 1300, "home", "H"), (1300, 1440, "sleep", "H"))
    assert is_free(p, 1130, 1190) and not is_free(p, 1000, 1190) and not is_free(p, 1280, 1340)
    assert not is_free(plan((0, 1440, "home", "offmap")), 100, 160)
    assert "work" not in FREE_ACTS


def run(extraversion=0.9, pairs=None, plans=None, haunts=None, weekend=True, n_days=40):
    pairs = pairs or [(1, 2, 0.9)]
    plans = plans or {1: plan((0, 700, "home", "H1"), (700, 1440, "home", "H1")),
                      2: plan((0, 900, "home", "H2"), (900, 1440, "home", "H2"))}
    haunts = haunts or (lambda a, k: ["C-1", "C-2"] if k == "cafe" else ["P-1"])
    got: list[Meetup] = []
    for d in range(1, n_days + 1):
        got += plan_meetups(pairs, day=d, weekend=weekend, seed=7, cfg=M, extraversion=lambda x: extraversion,
                            satisfaction=lambda x: 0.5, plan_of=lambda x: plans[x], haunts=haunts)
    return got


def test_friends_meet_sometimes_in_free_time_at_a_shared_haunt():
    got = run()
    assert 2 <= len(got) <= 35                                   # a minority of days, not never and not always
    for m in got:
        lo, hi = M["weekend_window"]
        assert lo <= m.start <= hi and m.start % 5 == 0 and m.act in ("cafe", "park") and m.minutes == M["minutes"]
        assert m.place_id in ("C-1", "C-2", "P-1")


def test_no_meetup_without_free_time_or_a_haunt():
    busy = {1: plan((0, 1440, "work", "W")), 2: plan((0, 1440, "home", "H"))}
    assert run(plans=busy) == []
    assert run(haunts=lambda a, k: []) == []


def test_reserved_pairs_meet_less_and_weekdays_less_than_weekends():
    assert len(run(extraversion=0.2)) < len(run(extraversion=0.9))
    assert len(run(weekend=False)) < len(run(weekend=True))


def test_meetups_are_deterministic_and_capped():
    assert run() == run()
    many = [(i, i + 1000, 0.9) for i in range(300)]
    plans = {x: plan((0, 1440, "home", "H")) for p in many for x in p[:2]}
    got = plan_meetups(many, day=6, weekend=True, seed=7, cfg={**M, "base_p_weekend": 5.0}, extraversion=lambda x: 1.0,
                       satisfaction=lambda x: 0.0, plan_of=lambda x: plans[x], haunts=lambda a, k: ["C-1"])
    assert len(got) == M["max_per_day"] and len({x for m in got for x in (m.a, m.b)}) == 2 * len(got)
