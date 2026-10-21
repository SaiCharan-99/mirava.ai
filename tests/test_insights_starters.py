"""Fix-B: every Ask starter question answers (non-fallback) offline; units, keyword search, SQL retry, prose."""

import asyncio
import json

import pytest

from agents.insights_assistant import STARTER_QUESTIONS, Assistant, _fmt, _unit
from engine.events import create_views
from insights.tools import DuckRunner, Ledger, Tools, keyword_stems
from shared.bq import DuckDBShim
from shared.llm import FakeGemini
from tests.test_insights import _ev

PID = "zen-7"
PRODUCTS = [{"product_id": PID, "name": "Zen 7", "price_inr": 21999}]


@pytest.fixture(scope="module")
def zdb():
    d = DuckDBShim(":memory:", "mirava")
    evs, texts = [], []
    for a in range(40):
        evs.append(_ev("agent_snapshot", 180, a, {"name": f"Agent {a}", "age": 20 + a, "gender": "f", "occupation": "x",
                                                  "income_band": "25-50k", "special_role": "none", "lifestyle": "student_life",
                                                  "phone": {"brand": "B", "tier": "mid", "condition": "ok",
                                                            "age_years": 1.0 + (a % 8)}}))
        if a % 2 == 0:
            evs.append(_ev("consideration", 2000 + a, a, {"subject": f"product:{PID}", "from": "aware", "to": "curious",
                                                          "cause_event_id": "x"}, product_id=PID))
        for f in (180.0, 0.0):
            evs.append(_ev("exposure", 1500 + a, a, {"channel": "hoarding", "creative_id": "c", "outcome":
                                                     "notice" if a % 10 < 3 else "glance", "facing": f, "lit": True,
                                                     "rate_inr_day": 7000, "target": True},
                           product_id=PID, site_id=f"S-{a % 2}", seq=int(f)))
        txt = f"My old phone dies by lunch, the Zen 7 battery sounds good ({a})."
        evs.append(_ev("thought", 1600 + a, a, {"text": txt, "attitude_delta": 0.1, "channel": "hoarding"},
                       product_id=PID, site_id="S-1"))
        texts.append({"text_id": f"t{a}", "event_id": f"thought:{1600 + a}:{a}:0", "t": 1600 + a, "day": 2,
                      "kind": "thought", "agent_id": a, "product_id": PID, "session_id": None, "private": True,
                      "text": txt, "embedding": []})
        if a % 5 == 0:
            evs.append(_ev("inquiry", 2500 + a, a, {"store_id": "st-1", "outcome": "will_think", "satisfaction": 0.7,
                                                    "n_messages": 4}, product_id=PID, other_id=900))
        if a % 10 == 0:
            evs.append(_ev("purchase", 2600 + a, a, {"option": PID if a % 20 == 0 else "baseline:mid",
                                                     "price_inr": 21999, "method": "upi"}))
    d.insert("events", [{**e, "payload": json.dumps(e["payload"])} for e in evs])
    d.insert("texts", texts)
    create_views(d)
    return d


def _ask(db, q):
    t = Tools(DuckRunner(db), Ledger(), embed=None)
    a = Assistant(t, FakeGemini(), products=PRODUCTS)

    async def go():
        ans = None
        async for item in a.ask(q):
            ans = item.get("answer", ans)
        return ans

    return asyncio.run(go())


@pytest.mark.parametrize("q", STARTER_QUESTIONS)
def test_every_starter_question_answers(zdb, q):
    ans = _ask(zdb, q)
    md = ans["answer_md"]
    assert ans["numbers"], (q, md)
    assert "error" not in ans and ans["faithful"]
    for bad in ("isn't enough data", "can't answer", "couldn't answer", "SELECT", "Error", "_count"):
        assert bad not in md, (q, md)
    assert ans["suggestions"] and q not in ans["suggestions"]
    assert 1 <= md.count(". ") + 1 <= 6


def test_why_question_quotes_keyword_fallback(zdb):
    ans = _ask(zdb, "Are people with phones older than 5 years interested in our phones, and why?")
    assert ans["quotes"] and "As for why" in ans["answer_md"]


def test_units_never_guess_percent():
    assert "%" not in _fmt(0.5)
    assert _fmt(163) == "163" and _fmt(0.072, _unit("notice_rate")) == "7.2%"
    assert _unit("considering_count") == "count" and _unit("satisfaction") == "value"


def test_keyword_stems_drop_stopwords():
    assert keyword_stems("How many are considering buying Pixel products and why?") == ["buyin", "consi", "pixel"]


def test_sql_retry_feeds_error_back(zdb):
    from agents.insights_assistant import Call, SqlFix, ToolArgs
    from shared.llm import LLMResult

    seen = {}

    class Fixer(FakeGemini):
        async def generate(self, model, prompt, schema, **kw):
            seen["prompt"] = prompt
            return LLMResult(data=SqlFix(sql="SELECT COUNT(*) AS n FROM agents_latest"))

    a = Assistant(Tools(DuckRunner(zdb), Ledger()), Fixer(), products=PRODUCTS)
    c = Call(tool="run_sql", args=ToolArgs(sql="SELECT nope FROM agents_latest"))
    ref, res = asyncio.run(a.call(c))
    assert ref == "error"
    c2, ref2, res2 = asyncio.run(a._retry_sql("how many?", c, res, timeout=5))
    assert ref2.startswith("sql:") and res2["rows"][0]["n"] == 40 and "nope" in seen["prompt"]



def test_web_starters_match_backend():
    from pathlib import Path

    ts = (Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "sampleQuestions.ts").read_text(encoding="utf-8")
    block = ts[ts.index("ASK_STARTERS"):ts.index("];")]
    assert all(f'"{q}"' in block for q in STARTER_QUESTIONS) and block.count('",') == len(STARTER_QUESTIONS)


def test_normalise_kinds_maps_model_plurals():
    from insights.tools import normalise_kinds

    assert normalise_kinds(["thoughts", "messages", "comments"]) == sorted(
        {"thought", "message", "community_comment", "community_post", "review"})
    assert normalise_kinds(["store_thought"]) == ["store_thought"]
    assert normalise_kinds(["nonsense"]) is None and normalise_kinds(None) is None
