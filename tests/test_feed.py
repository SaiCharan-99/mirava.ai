"""Phase 3: feed ranking, affinity learning."""

from media.feed import Candidate, FeedAffinity, rank, score
from shared.schemas.product import StimulusRecord

STIM = StimulusRecord(creative_id="c", salience=0.5, clarity=0.5, hook="h", claims_carried=[], tone="t",
                      readable_at_distance=True, description="d")


def cand(source, pid="p", cid=None, topic="phones", closeness=0.0):
    return Candidate(pid, cid or f"{source}-{pid}", "reel", STIM, 0.5, source, topic, closeness)


def sc(c, **kw):
    base = {"affinity": 0.1, "need": 0.0, "in_audience": False, "curious": False, "n_seen": 0}
    return score(c, **{**base, **kw})


def test_paid_reach_targets_the_audience_not_everyone():
    assert sc(cand("paid"), in_audience=True) > sc(cand("paid"), in_audience=False) + 0.6


def test_need_and_curiosity_pull_phone_content_up_but_not_other_topics():
    assert sc(cand("paid"), need=0.9) > sc(cand("paid"), need=0.0) + 0.4
    assert sc(cand("paid"), curious=True) == sc(cand("paid")) + 0.2
    other = cand("baseline", topic="food")
    assert sc(other, need=0.9, curious=True) == sc(other)


def test_close_friends_shares_beat_acquaintances_and_ads():
    close, far = cand("share", closeness=0.9), cand("share", closeness=0.1)
    assert sc(close) > sc(far) > sc(cand("baseline", topic="food"))
    assert sc(close) > sc(cand("paid"))                       # a friend's reel outranks an ad for a stranger


def test_repeats_fade():
    assert sc(cand("paid"), n_seen=4) < sc(cand("paid"), n_seen=0)
    assert sc(cand("paid"), n_seen=50) == sc(cand("paid"), n_seen=5)


def test_rank_is_by_score_and_stable():
    cs = [cand("baseline", "a", topic="x"), cand("paid", "b"), cand("share", "c", closeness=0.8)]
    out = rank(cs, [0.1, 0.9, 1.2], 2)
    assert [c.pid for c in out] == ["c", "b"]
    tie = rank([cand("paid", "z"), cand("paid", "a")], [0.5, 0.5], 2)
    assert [c.pid for c in tie] == ["a", "z"]


def test_feed_learns_what_you_watch_and_forgets_slowly():
    f = FeedAffinity()
    base = f.get(1, "phones", ["cooking"])
    assert base == 0.1 and f.get(2, "phones", ["gadgets"]) == 0.4
    for _ in range(5):
        f.learn(1, "phones", "full", ["cooking"])
    assert f.get(1, "phones", ["cooking"]) > 0.65
    for _ in range(20):
        f.learn(1, "phones", "scroll", ["cooking"])
    assert f.get(1, "phones", ["cooking"]) < 0.2 and f.get(1, "phones", ["cooking"]) >= 0.0
    f.learn(3, "phones", "full", [])
    before = f.get(3, "phones", [])
    for _ in range(30):
        f.decay()
    assert 0.1 < f.get(3, "phones", []) < before
    g = FeedAffinity()
    g.load(f.to_dict())
    assert abs(g.get(3, "phones", []) - f.get(3, "phones", [])) < 1e-3
