"""Survey Room (addendum B13): recruitment + travel, tables, discussion, private ballots, isolation, caps, determinism."""

import asyncio
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from engine.events import NullSink
from engine.loop import Engine
from engine.survey import recruit
from engine.survey.session import Budget, Person, TableRunner
from mind.decision import FakeDecision
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.llm import FakeGemini
from shared.schemas.survey import Question, Survey
from shared.settings import Settings
from shared.store import MemoryStoreBackend

N = 240
QS = [{"question_id": "q1", "text": "Which matters most in your next phone?", "type": "single",
       "options": ["Battery", "Camera", "Price", "Brand"]},
      {"question_id": "q2", "text": "How likely are you to buy a new phone this year?", "type": "scale",
       "scale": {"min": 1, "max": 5, "low_label": "not at all", "high_label": "certainly"}},
      {"question_id": "q3", "text": "What would make you switch phones?", "type": "open"}]


def _survey(sid: str, mode: str = "focus_group", n: int = 20, qs=QS) -> dict:
    return Survey(survey_id=sid, title="Phones — battery and price", mode=mode, topic="phones",
                  questions=[Question.model_validate(q) for q in qs], cohort_filter="phone_age_years > 1",
                  max_participants=n, table_size=8).model_dump(mode="json")


async def _run_until(e: Engine, sid: str, max_ticks: int) -> int:
    for i in range(max_ticks):
        await e.tick()
        doc = e.store.get("surveys", sid) or {}
        if doc.get("status") == "completed" and e.surveys.active is None:
            for _ in range(5):
                await asyncio.sleep(0.02)
            await e.bus.flush()
            return i
    raise AssertionError(f"survey did not complete: {e.store.get('surveys', sid)}")


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("survey")
    s = Settings(world_agents=N, world_seed=11, checkpoint_every_sim_minutes=10**6, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp))
    store, files, sink = MemoryStoreBackend(), LocalFiles(str(tmp)), NullSink()
    asyncio.run(run_genesis(N, 11, store=store, files=files, sink=NullSink(), llm=None, settings=s))

    async def go():
        e = Engine(s, store, files, sink)
        e.boot()
        for _ in range(8 * 60 - e.world.t % 1440):         # start the morning at 08:00
            await e.tick()
        store.set("surveys", "sv-fg", _survey("sv-fg"))
        assert e.command({"type": "survey_launch", "survey_id": "sv-fg"})["ok"]
        await _run_until(e, "sv-fg", 6 * 60)
        store.set("surveys", "sv-one", _survey("sv-one", n=1))
        e.command({"type": "survey_launch", "survey_id": "sv-one"})
        await _run_until(e, "sv-one", 6 * 60)
        return e

    e = asyncio.run(go())
    return e, sink, store


def _k(sink, kind, sid="sv-fg"):
    return [x for x in sink.events if x["kind"] == kind and (x["payload"] or {}).get("survey_id") == sid]


def test_recruitment_rsvp_and_travel(ran):
    e, sink, store = ran
    inv, rsvp = _k(sink, "survey_invite"), _k(sink, "survey_rsvp")
    assert inv and len(rsvp) == len(inv) and all(r["private"] for r in rsvp)
    acc = {r["agent_id"] for r in rsvp if r["payload"]["status"] == "accepted"}
    assert 1 <= len(acc) <= 20
    venue = recruit.cfg()["venue"]["place_id"]
    arrived = {x["agent_id"] for x in sink.events if x["kind"] == "arrive" and x["payload"]["place_id"] == venue}
    assert len(arrived & acc) >= max(1, int(0.6 * len(acc)))           # accepted agents actually walk there
    doc = store.get("surveys", "sv-fg")
    att = [p for p in doc["participants"] if p["rsvp"] == "attended"]
    assert len(doc["tables"]) == math.ceil(len(att) / 8)               # tables are made from who actually turned up
    assert att


def test_ballots_valid_one_per_question(ran):
    _, sink, store = ran
    doc = store.get("surveys", "sv-fg")
    att = {p["agent_id"] for p in doc["participants"] if p["rsvp"] == "attended"}
    ans = _k(sink, "survey_answer")
    qs = {q["question_id"]: Question.model_validate(q) for q in QS}
    per = {}
    for a in ans:
        q = qs[a["payload"]["question_id"]]
        assert q.valid(a["payload"]["answer"]), a["payload"]
        per[(a["agent_id"], q.question_id)] = per.get((a["agent_id"], q.question_id), 0) + 1
    assert set(per.values()) == {1} and {k[0] for k in per} == att and len(per) == 3 * len(att)
    pre = _k(sink, "survey_prestance")
    assert pre and all(p["private"] for p in pre)


def test_discussion_messages_and_texts(ran):
    _, sink, _ = ran
    msgs = [m for m in sink.events if m["kind"] == "message" and m["payload"].get("conv_kind") == "focus_group"
            and m["payload"]["survey_id"] == "sv-fg"]
    assert msgs and any(m["payload"]["speaker"] == "moderator" for m in msgs)
    spoken = [m for m in msgs if m["payload"]["speaker"] != "moderator"]
    per = {}
    for m in spoken:
        per[m["agent_id"]] = per.get(m["agent_id"], 0) + 1
    assert spoken and max(per.values()) <= 10
    ids = {m["event_id"] for m in msgs}
    texts = {t["event_id"] for t in sink.texts if t["kind"] == "message"}
    assert ids <= texts                                            # every public utterance has a text row
    assert all(m["session_id"] for m in msgs)
    assert _k(sink, "survey_summary") and _k(sink, "survey_completed")


def test_one_participant_runs_without_discussion(ran):
    _, sink, store = ran
    doc = store.get("surveys", "sv-one")
    att = [p for p in doc["participants"] if p["rsvp"] == "attended"]
    assert len(att) <= 1
    msgs = [m for m in sink.events if m["kind"] == "message" and m["payload"].get("survey_id") == "sv-one"
            and m["payload"]["speaker"] != "moderator"]
    assert msgs == []
    if att:
        assert len(_k(sink, "survey_answer", "sv-one")) == 3


def test_cap_100_enforced():
    with pytest.raises(ValidationError):
        Survey(survey_id="x", title="t", mode="survey", questions=[Question.model_validate(QS[0])], max_participants=101)
    rows = list(range(300))
    chosen, wait = recruit.select(rows, rows, 500, [type("P", (), {"age": 30})()] * 300, 1, "x")
    assert len(chosen) == 100 and len(wait) == 200


def _people(n=6, marker_for=None):
    out = []
    for i in range(n):
        out.append(Person(agent_id=i, name=f"P{i}", age=25 + i, occupation="x", income_band="25-50k",
                          big5={"O": 0.5, "C": 0.6, "E": 0.2 + 0.12 * i, "A": 0.5, "N": 0.4}, style="plain",
                          card=f"card {i}" + (" SECRET-MARKER-91" if i == marker_for else ""), phone="B mid, 5 years, ok",
                          attitude=0.1 * (i - 3), memories=[f"memory {i}" + (" SECRET-MARKER-91" if i == marker_for else "")],
                          briefs="Pixel 10a: I like it — good: battery beats my phone" + (" BRIEF-MARKER-77" if i == marker_for else "")))
    return out


class Echo(FakeGemini):
    """Fake that writes the prompt's own private context into its outputs (worst case for leaks)."""

    async def generate(self, model, prompt, schema=None, **kw):
        res = await super().generate(model, prompt, schema, **kw)
        if hasattr(res.data, "thought"):
            res.data.thought = str(prompt)[-300:]
        if hasattr(res.data, "gut_reason"):
            res.data.gut_reason = str(prompt)[:200]
        return res


def test_marker_fact_isolation():
    async def go():
        r = TableRunner(_survey("iso"), "T1", "s1", _people(marker_for=2), llm=Echo(), decider=FakeDecision(),
                        cfg=recruit.cfg(), seed=3, budget=Budget(left=10.0))
        r.offline = False                                          # exercise the model prompts
        await r.run()
        return r

    r = asyncio.run(go())
    mine = 0
    for purpose, owner, prompt in r.prompts:
        if owner != 2:
            assert "SECRET-MARKER-91" not in prompt, (purpose, owner)
            assert "BRIEF-MARKER-77" not in prompt, (purpose, owner)           # my opinions of the products stay mine
        elif "BRIEF-MARKER-77" in prompt:
            mine += 1
    assert mine > 0                                                           # …and are in my own prompts
    for it in r.items:
        if it["kind"] == "message":
            assert "SECRET-MARKER-91" not in it["payload"]["text"]


def test_ballot_context_only_own_retained_messages():
    async def go():
        r = TableRunner(_survey("ctx"), "T1", "s1", _people(), llm=FakeGemini(), decider=FakeDecision(),
                        cfg=recruit.cfg(), seed=5, budget=Budget(left=10.0))
        r.offline = False
        await r.run()
        return r

    r = asyncio.run(go())
    msgs = {it["payload"]["message_id"]: it["payload"]["text"] for it in r.items if it["kind"] == "message"}
    heard = {}
    for it in r.items:
        if it["kind"] == "survey_heard":
            heard[(it["agent_id"], it["payload"]["question_id"])] = {h["message_id"] for h in it["payload"]["items"]}
    ballots = [(o, p) for pu, o, p in r.prompts if pu == "survey_ballot"]
    assert ballots
    q_of = {}
    for pu, o, p in r.prompts:
        if pu == "survey_ballot":
            q = next(q["question_id"] for q in QS if q["text"] in p)
            keep = heard.get((o, q), set())
            for mid, _txt in msgs.items():
                if f"[{mid}]" in p:
                    assert mid in keep
            q_of[o] = q


def test_determinism_same_survey_same_answers():
    async def go():
        r = TableRunner(_survey("det"), "T1", "s1", _people(), llm=FakeGemini(), decider=FakeDecision(),
                        cfg=recruit.cfg(), seed=9, budget=Budget(left=10.0))
        await r.run()
        return [(it["kind"], it["agent_id"], str(it["payload"].get("text") or it["payload"].get("answer")))
                for it in r.items]

    assert asyncio.run(go()) == asyncio.run(go())


def test_extraversion_drives_talk():
    async def go():
        r = TableRunner(_survey("ext"), "T1", "s1", _people(8), llm=FakeGemini(), decider=FakeDecision(),
                        cfg=recruit.cfg(), seed=2, budget=Budget(left=10.0))
        await r.run()
        return r

    r = asyncio.run(go())
    xs = [p.big5["E"] for p in r.people]
    ys = [r.spoken[p.agent_id] for p in r.people]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs)) or 1
    sy = math.sqrt(sum((b - my) ** 2 for b in ys)) or 1
    assert cov / (sx * sy) > 0.3


def test_budget_refusal_and_estimate(monkeypatch):
    import api.main as m
    import api.surveys as sv

    store = MemoryStoreBackend()
    monkeypatch.setattr(sv, "store", lambda: store)
    monkeypatch.setattr(sv, "_eligible", lambda c, i: 300)
    monkeypatch.setattr(sv, "remaining_interactive", lambda: 0.01)
    monkeypatch.setattr(sv, "_engine_state", lambda: {"t": 1})
    sent = []
    monkeypatch.setattr(sv, "_engine", lambda cmd: sent.append(cmd) or {"ok": True})
    c = TestClient(m.app)
    r = c.post("/api/surveys", json={"title": "Pulse 5 — price and battery", "mode": "focus_group", "questions": QS,
                                     "cohort_filter": "phone_age_years > 5", "max_participants": 40})
    assert r.status_code == 200 and r.json()["eligible"] == 300 and r.json()["tables"] == 5
    assert r.json()["estimate_usd"] > 0
    sid = r.json()["survey_id"]
    assert c.post(f"/api/surveys/{sid}/launch").status_code == 402 and not sent
    monkeypatch.setattr(sv, "remaining_interactive", lambda: 5.0)
    assert c.post(f"/api/surveys/{sid}/launch").json()["status"] == "recruiting" and sent
    assert c.post("/api/surveys", json={"title": "x too big", "questions": QS, "max_participants": 101}).status_code == 422
    monkeypatch.setattr(sv, "_eligible", lambda c, i: 0)
    r0 = c.post("/api/surveys", json={"title": "Nobody", "questions": QS, "max_participants": 5})
    assert r0.json()["message"].startswith("No agents match")
    assert c.post(f"/api/surveys/{r0.json()['survey_id']}/launch").status_code == 422


def test_estimate_within_25pct_of_actual_calls():
    """Estimate vs the calls a real run makes (counted on the model path with token proxies)."""
    s = Survey.model_validate(_survey("est", n=8))
    est = recruit.estimate(s, 8)

    async def go():
        llm = FakeGemini()
        r = TableRunner(s.model_dump(), "T1", "s1", _people(8), llm=llm, decider=FakeDecision(), cfg=recruit.cfg(),
                        seed=4, budget=Budget(left=10.0))
        r.offline = False
        await r.run()
        return r

    r = asyncio.run(go())
    from shared.models import cost_usd

    tok = recruit.cfg()["tokens"]
    kinds = {"survey_prestance": "prestance", "survey_think": "think", "survey_speak": "speak",
             "survey_moderator": "moderator", "survey_ballot": "ballot"}
    actual = sum(cost_usd("lite", *tok[kinds[p]]) for p, _, _ in r.prompts)
    actual += cost_usd("flash", *tok["summary"]) * 2 + est["calls"]["rsvp"] * cost_usd("lite", tok["rsvp"][0] * 32,
                                                                                         tok["rsvp"][1] * 32)
    assert abs(est["usd"] - actual) <= 0.25 * actual, (est, actual)


def test_live_protocol_subscriptions():
    from engine.live import LiveHub

    sent = []

    class WS:
        async def send_text(self, s):
            sent.append(s)

    hub, ws, old = LiveHub(), WS(), WS()
    hub.clients |= {ws, old}
    hub.on_client_message(ws, '{"type":"sub","survey_id":"sv-1"}')
    hub.on_client_message(old, "not json")
    asyncio.run(hub.send_survey("sv-1", [{"type": "survey_msg", "survey_id": "sv-1", "text": "hi"}]))
    assert len(sent) == 1 and '"survey_msg"' in sent[0]


def test_estimate_endpoint_never_writes_and_gives_friendly_errors(monkeypatch):
    import api.main as m
    import api.surveys as sv

    store = MemoryStoreBackend()
    monkeypatch.setattr(sv, "store", lambda: store)
    monkeypatch.setattr(sv, "_eligible", lambda c, i: 120)
    monkeypatch.setattr(sv, "remaining_interactive", lambda: 5.0)
    monkeypatch.setattr(sv, "_engine_state", lambda: {"t": 1})
    c = TestClient(m.app)
    body = {"title": "Draft survey", "mode": "survey", "questions": QS, "max_participants": 30}
    r = c.post("/api/surveys/estimate", json=body)
    assert r.status_code == 200 and r.json()["eligible"] == 120 and r.json()["estimate_usd"] > 0
    assert "survey_id" not in r.json()
    assert store.list("surveys") == []                                   # editing never creates drafts
    blank = {**body, "questions": [*QS, {"text": "", "type": "open", "discuss": True}]}
    bad = c.post("/api/surveys/estimate", json=blank)
    assert bad.status_code == 422 and bad.json()["detail"] == f"Question {len(QS) + 1} needs text"
    assert store.list("surveys") == []
    assert c.post("/api/surveys", json=body).status_code == 200          # create (on Launch) does write
    assert len(store.list("surveys")) == 1


def _api(monkeypatch, eligible=300):
    import api.main as m
    import api.surveys as sv

    store = MemoryStoreBackend()
    monkeypatch.setattr(sv, "store", lambda: store)
    monkeypatch.setattr(sv, "_eligible", lambda c, i: eligible)
    monkeypatch.setattr(sv, "remaining_interactive", lambda: 5.0)
    monkeypatch.setattr(sv, "_engine_state", lambda: {"t": 1})
    return TestClient(m.app), store


def test_builder_allows_two_to_four_options_only(monkeypatch):
    c, store = _api(monkeypatch)
    base = {"title": "Options check", "mode": "survey", "max_participants": 20}

    def q(n):
        return [{"question_id": "q1", "text": "Which would you pick?", "type": "single", "options": [f"Option {i}" for i in range(n)]}]

    assert c.post("/api/surveys/estimate", json={**base, "questions": q(2)}).status_code == 200
    assert c.post("/api/surveys/estimate", json={**base, "questions": q(4)}).status_code == 200
    five = c.post("/api/surveys/estimate", json={**base, "questions": q(5)})
    assert five.status_code == 422 and "more than 4 options" in five.json()["detail"]
    assert c.post("/api/surveys/estimate", json={**base, "questions": q(1)}).status_code == 422     # needs at least 2
    assert store.list("surveys") == []


def test_estimate_reflects_reward_and_channels(monkeypatch):
    c, _ = _api(monkeypatch, eligible=120)
    body = {"title": "Reward check", "mode": "survey", "questions": QS, "max_participants": 100}
    none = c.post("/api/surveys/estimate", json={**body, "incentive": {"cash_inr": 0, "goodies": [], "note": ""}}).json()
    rich = c.post("/api/surveys/estimate", json={**body, "incentive": {"cash_inr": 1000, "goodies": [
        {"kind": "voucher", "label": "shopping voucher", "value_inr": 1000}], "note": ""}}).json()
    assert rich["expected_attendance"] > none["expected_attendance"] >= 1
    panel_only = c.post("/api/surveys/estimate", json={**body, "channels": ["panel"]}).json()
    everything = c.post("/api/surveys/estimate", json={**body}).json()
    assert everything["reach"] >= panel_only["reach"] and everything["expected_attendance"] >= panel_only["expected_attendance"]
    assert everything["expected_attendance"] <= 100 and everything["reach"] <= 120


def test_products_incentive_and_channels_are_stored_on_launch(monkeypatch):
    c, store = _api(monkeypatch)
    r = c.post("/api/surveys", json={"title": "Two phones head to head", "mode": "focus_group", "questions": QS,
                                     "max_participants": 20, "product_ids": ["pixel-10a", "galaxy-a57"],
                                     "incentive": {"cash_inr": 300, "goodies": [{"kind": "food", "label": "lunch", "value_inr": 250}],
                                                   "note": ""}, "channels": ["panel", "word_of_mouth"],
                                     "start_at_t": 5000})
    assert r.status_code == 200
    doc = store.get("surveys", r.json()["survey_id"])
    assert doc["product_ids"] == ["pixel-10a", "galaxy-a57"] and doc["product_id"] == "pixel-10a"
    assert doc["incentive"]["goodies"][0]["label"] == "lunch" and doc["incentive_inr"] == 300
    assert doc["channels"] == ["panel", "word_of_mouth"] and doc["start_at_t"] == 5000
