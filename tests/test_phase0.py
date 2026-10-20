"""Phase 0: canonical belief subjects, belief cleanup merge, counters (unit rules)."""

import pytest

from shared.subjects import canonical, slug
from tools.clean_beliefs import merge, plan_for_agent

CATALOG = {"pixel-10a": "Pixel 10a", "galaxy-a57": "Galaxy A57", "iphone-17": "iPhone 17"}


@pytest.mark.parametrize("raw,want", [
    ("product:pixel-10a", "product:pixel-10a"),
    ("product:Pixel 10a", "product:pixel-10a"),
    ("product:Pixel-10a", "product:pixel-10a"),
    ("product:pixel_10a", "product:pixel-10a"),
    ("product:iPhone 17", "product:iphone-17"),
    ("product:Galaxy A 57", "product:galaxy-a57"),        # fuzzy
    ("product:temple_visit", None),                        # junk is dropped
    ("product:Pulse 5", None),                             # deleted demo product
    ("brand:Google", "brand:google"),
    ("category:Smartphones", "category:phone"),
    ("category:coffee", "category:coffee"),
    ("temple_visit", None),
    ("person:ravi", None),
])
def test_canonical_subject(raw, want):
    assert canonical(raw, CATALOG) == want


def test_slug():
    assert slug("  Pixel 10a! ") == "pixel-10a"


def _belief(subject, stage, att, t, **kw):
    return {"agent_id": 1, "subject": subject, "awareness": "aware", "attitude": att, "confidence": 0.5,
            "reasons_for": kw.get("rf", []), "reasons_against": [], "open_questions": [],
            "first_heard": kw.get("fh"), "sources_seen": kw.get("ss", {}), "stage": stage, "updated_t": t}


def test_merge_keeps_best_stage_latest_attitude_and_union():
    a = _belief("product:Pixel 10a", "researching", 0.1, 10, rf=["camera"], fh={"t": 5, "channel": "hoarding"},
                ss={"hoarding": 1})
    b = _belief("product:pixel-10a", "curious", 0.4, 20, rf=["battery"], fh={"t": 9, "channel": "reel"},
                ss={"hoarding": 2, "reel": 1})
    m = merge([a, b], "product:pixel-10a")
    assert m["stage"] == "researching" and m["attitude"] == 0.4 and m["updated_t"] == 20
    assert m["reasons_for"] == ["battery", "camera"]
    assert m["first_heard"]["t"] == 5
    assert m["sources_seen"] == {"hoarding": 3, "reel": 1}


def test_plan_merges_duplicates_and_drops_junk():
    rows = [_belief("product:Pixel 10a", "curious", 0.2, 5), _belief("product:pixel-10a", "aware", 0.3, 6),
            _belief("product:temple_visit", "unaware", 0.0, 1), _belief("product:galaxy-a57", "aware", 0.1, 2)]
    write, drop = plan_for_agent(rows, CATALOG)
    assert set(write) == {"product:pixel-10a"}
    assert sorted(drop) == ["product:Pixel 10a", "product:temple_visit"]


def test_plan_noop_when_clean():
    assert plan_for_agent([_belief("product:galaxy-a57", "aware", 0.1, 2)], CATALOG) == ({}, [])
