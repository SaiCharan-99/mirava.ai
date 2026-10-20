"""Phase 2b: stop decisions, held routes and the live replace frame."""

import math
from types import SimpleNamespace

from engine.live import tick_frames
from engine.movement import Seg
from engine.world import Agent, World
from social.stop import StopCtx, decide_stop, urgency


def ctx(**kw):
    base = {"closeness": 0.7, "hurry": 0.2, "agenda": 0.6, "social_need": 0.6, "mood": 0.6, "days_since_met": 5.0}
    return StopCtx(**{**base, **kw})


def test_urgency_by_destination_and_vehicle():
    assert urgency("work", "commute", "walk") > urgency("cafe", "commute", "walk")
    assert urgency("park", "commute", "car") >= 0.9
    assert urgency("roam", "roam", "walk") > urgency("home", "commute", "walk")


def test_late_for_work_means_a_nod_not_a_chat():
    assert decide_stop(ctx(hurry=0.85)) == "nod"
    assert decide_stop(ctx(hurry=0.85, closeness=0.1, agenda=0.0, social_need=0.2)) == "ignore"


def test_free_close_friends_with_news_stop_and_talk():
    assert decide_stop(ctx(hurry=0.2, closeness=0.9, agenda=0.9, social_need=0.8, days_since_met=7)) == "long"
    assert decide_stop(ctx(hurry=0.2, closeness=0.55, agenda=0.4)) in ("quick", "long")
    assert decide_stop(ctx(hurry=0.35, closeness=0.55, agenda=0.4)) in ("nod", "quick")   # a bit pressed: shorter


def test_distant_acquaintances_with_nothing_to_say_walk_on():
    assert decide_stop(ctx(closeness=0.15, agenda=0.0, social_need=0.2, mood=0.4, days_since_met=0.1)) in ("ignore", "nod")


def test_more_willing_when_closer_and_longer_apart():
    assert ctx(closeness=0.9).__class__ is StopCtx
    from social.stop import stop_score

    assert stop_score(ctx(closeness=0.9)) > stop_score(ctx(closeness=0.2))
    assert stop_score(ctx(days_since_met=7)) > stop_score(ctx(days_since_met=0.1))
    assert stop_score(ctx(hurry=0.9)) < stop_score(ctx(hurry=0.1))


def walker(aid=7):
    a = Agent(id=aid, x=0.0, y=0.0)
    a.route = [Seg(0, 0, 100, 0, 10.0, 20.0, "walk"), Seg(100, 0, 100, 60, 20.0, 26.0, "walk")]
    a.mode = "walk"
    return a


def stub():
    return SimpleNamespace(replaced=set(), new_segs=[])


def test_hold_stops_in_place_then_continues_later():
    w, a = stub(), walker()
    assert World.hold(w, a, 15, 12)                       # halfway through the first segment
    assert (round(a.x, 3), round(a.y, 3)) == (50.0, 0.0)  # the agent stays where it stopped
    assert a.talk_until == 27
    assert a.route[-1].t1 == 26.0 + 12                    # the whole rest of the trip is 12 min later
    first_after = next(s for s in a.route if s.t1 > 15)
    assert first_after.t0 == 27 and (first_after.x0, first_after.y0) == (50.0, 0.0)
    assert math.isclose(first_after.t1 - first_after.t0, 5.0)    # the remaining half takes as long as before
    assert w.replaced == {7} and all(s["a"] == 7 for s in w.new_segs) and w.new_segs[0]["t0"] == 27


def test_position_during_the_hold_is_the_stopping_point():
    w, a = stub(), walker()
    World.hold(w, a, 15, 12)
    fake = SimpleNamespace()
    for t in (15.0, 20.0, 26.9):
        assert World.position(fake, a, t)[:2] == (50.0, 0.0)
    x, y, _ = World.position(fake, a, 30.0)               # walking again
    assert x > 50.0 and y == 0.0


def test_hold_refuses_agents_that_are_not_travelling():
    w, a = stub(), Agent(id=1, x=3.0, y=4.0)
    assert not World.hold(w, a, 10, 5) and not w.replaced and (a.x, a.y) == (3.0, 4.0)
    b = walker()
    assert not World.hold(w, b, 27, 5)                    # past the end of the route


def test_live_frame_tells_viewers_which_agents_were_re_timed():
    w, a = stub(), walker()
    World.hold(w, a, 15, 12)
    frames = tick_frames(SimpleNamespace(new_segs=w.new_segs, replaced=w.replaced, live_evts=[], t=15),
                         SimpleNamespace(paused=False, speed=1.0))
    seg = next(f for f in frames if f["type"] == "seg")
    assert seg["replace"] == [7] and seg["items"]
    plain = tick_frames(SimpleNamespace(new_segs=w.new_segs, replaced=set(), live_evts=[], t=16),
                        SimpleNamespace(paused=False, speed=1.0))
    assert "replace" not in next(f for f in plain if f["type"] == "seg")
