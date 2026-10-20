"""Agenda (what's on my mind) and model-free word of mouth."""

from social.agenda import DAY, Agenda
from social.wom import tell
from tests.test_opinion import engine, person

NAMES = {0: "Meera", 1: "Arjun", 2: "Kavya"}
name_of = lambda a: NAMES.get(a, f"Agent {a}")  # noqa: E731
pname = lambda pid: {"big-battery": "Volt 6000"}.get(pid, pid)  # noqa: E731


def test_add_refreshes_instead_of_duplicating_and_caps_at_eight():
    ag = Agenda()
    ag.add(0, "product_noticed", 10, hint="Volt", product_id="p1", weight=0.3)
    ag.add(0, "product_noticed", 20, hint="Volt", product_id="p1", weight=0.6)
    assert len(ag.items[0]) == 1 and ag.items[0][0].weight == 0.6 and ag.items[0][0].created_t == 20
    for i in range(12):
        ag.add(0, "wants_to_tell", i, target_id=100 + i, weight=0.5 + i / 100)
    assert len(ag.items[0]) == 8
    assert ag.items[0][0].weight >= ag.items[0][-1].weight


def test_pick_respects_told_target_and_expiry():
    ag = Agenda()
    ag.add(0, "wants_to_tell", 0, target_id=1, weight=0.9)
    ag.add(0, "phone_trouble", 0, weight=0.5)
    assert ag.pick_to_tell(0, 2, 5).kind == "phone_trouble"          # the first is only for person 1
    assert ag.pick_to_tell(0, 1, 5).kind == "wants_to_tell"
    ag.pick_to_tell(0, 2, 5).told.append(2)
    assert ag.pick_to_tell(0, 2, 5) is None                          # already told person 2
    assert ag.pick_to_tell(0, 1, 5 * DAY) is None                    # expired


def test_nightly_decays_and_drops():
    ag = Agenda()
    ag.add(0, "opinion", 0, weight=0.3)
    for d in range(1, 12):
        ag.nightly(d * DAY // 10)
    assert 0 not in ag.items
    ag.add(1, "purchase", 0)
    ag.nightly(10)
    assert 0.7 < ag.items[1][0].weight < 0.9


def test_hints_are_tags_only_and_roundtrip():
    ag = Agenda()
    ag.add(0, "phone_trouble", 0, hint="phone slow", about="screen froze in the cab")
    assert ag.hints(0) == ["phone slow"]                              # never the private note
    b = Agenda()
    b.load(ag.to_dict())
    assert b.items[0][0].about == "screen froze in the cab" and b.hints(0) == ["phone slow"]


def test_tell_product_moves_listener_perception_and_marks_told():
    a, b = person(0, interests=("travel",)), person(1)
    e = engine(a, b)
    e.evidence(0, "big-battery", None, "own_use")                    # the teller really knows the phone
    ag = Agenda()
    ag.add(0, "product_noticed", 5, hint="Volt 6000", product_id="big-battery")
    assert not e.aware_of(1, "big-battery")
    told = tell(ag, e, 0, 1, 0.8, 100, name_of=name_of, product_name=pname, seed=7)
    assert told and told.product_id == "big-battery" and told.attrs
    assert "Meera" in told.memory and "Volt 6000" in told.memory
    assert e.aware_of(1, "big-battery")                              # the listener now knows of it
    assert 1 in ag.items[0][0].told
    again = tell(ag, e, 0, 1, 0.8, 101, name_of=name_of, product_name=pname, seed=7)
    assert again.kind == "general" and again.product_id is None      # nothing new to say


def test_close_tellers_are_believed_more_than_acquaintances():
    a, b, c = person(0), person(1), person(2)
    e = engine(a, b, c)
    e.evidence(0, "big-battery", None, "own_use")
    for listener, closeness in ((1, 0.9), (2, 0.1)):
        ag = Agenda()
        ag.add(0, "product_noticed", 5, hint="Volt", product_id="big-battery")
        tell(ag, e, 0, listener, closeness, 100, name_of=name_of, product_name=pname, seed=7)
    top = e.top_claims(0, "big-battery", 1)[0][0]
    assert e.perc[1]["big-battery"][top][1] > e.perc[2]["big-battery"][top][1]


def test_phone_trouble_is_told_without_a_product():
    ag = Agenda()
    ag.add(0, "phone_trouble", 0, hint="phone slow")
    told = tell(ag, None, 0, 1, 0.5, 50, name_of=name_of, product_name=pname, seed=7)
    assert told.kind == "phone_trouble" and told.product_id is None and "Meera" in told.memory
    assert ag.items[1][0].kind == "life_news"                         # the listener now has news to pass on
