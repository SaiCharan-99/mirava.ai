"""Phase-5 evals → evals/RESULTS.md: Insights faithfulness benchmark + Survey Room realism (addendum B14).

Usage: uv run python -m evals.run [--agents 400] [--days 3]
Builds a seeded local world with the fake backend (or the configured LLM_BACKEND), launches Pulse 5, runs a focus
group, lets a sim day pass, runs wave 2, then scores the assistant and the survey behaviour.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals" / "RESULTS.md"


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson r."""
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)) or 1e-9
    sy = math.sqrt(sum((y - my) ** 2 for y in ys)) or 1e-9
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


async def build_world(n: int, days: float, tmp: str) -> dict[str, Any]:
    """Genesis → launch → days of world → focus group wave 1 → +1 day → wave 2. Returns handles."""
    import api.main as m
    import api.products as ap
    from engine.events import DuckDBSink
    from engine.loop import Engine
    from population.genesis import run_genesis
    from shared.files import LocalFiles
    from shared.settings import Settings
    from shared.store import MemoryStoreBackend
    from tests.test_survey import QS, _survey

    s = Settings(world_agents=n, world_seed=21, checkpoint_every_sim_minutes=10**6, gcs_bucket_worlds="w",
                 local_files_dir=tmp, duckdb_path=str(Path(tmp) / "eval.duckdb"))
    store, files = MemoryStoreBackend(), LocalFiles(tmp)
    sink = DuckDBSink(s)
    from engine.events import NullSink

    await run_genesis(n, 21, store=store, files=files, sink=NullSink(), llm=None, settings=s)
    m.store = ap.store = lambda: store  # type: ignore[assignment]
    m._engine_get = lambda path: None  # type: ignore[assignment]
    ap._cache.clear()
    c = TestClient(m.app)
    pid = c.post("/api/products", json={
        "name": "Pulse 5", "brand": "Voltix", "category": "Smartphone", "price_inr": 18999,
        "features": ["6,000 mAh battery", "120Hz display", "50MP camera"], "claims": ["Two-day battery life."],
        "target_personas": ["Students and young workers"], "strategy": {"intensity": "high", "flight_days": 14}}).json()["product_id"]
    for kind, title, text in (("hoarding", "Hoarding", "TWO DAYS. ONE CHARGE."), ("reel", "Battery", "Game all night."),
                              ("store_display", "Display", "Try the Pulse 5 here")):
        c.post(f"/api/products/{pid}/creatives", json={"kind": kind, "title": title, "text": text})
    for step in ("audience", "understand", "plan", "ready"):
        c.post(f"/api/products/{pid}/{step}", json={} if step == "audience" else None)
    e = Engine(s, store, files, sink)
    e.boot()
    ap._engine_command = lambda cmd: e.command(cmd)  # type: ignore[assignment]
    c.post(f"/api/products/{pid}/launch")
    for _ in range(int(days * 1440)):
        await e.tick()

    async def survey(sid: str, doc: dict[str, Any]) -> None:
        store.set("surveys", sid, doc)
        e.command({"type": "survey_launch", "survey_id": sid})
        for _ in range(12 * 60):
            await e.tick()
            if (store.get("surveys", sid) or {}).get("status") == "completed" and e.surveys.active is None:
                break

    d1 = _survey("sv-eval", n=40)
    d1.update({"product_id": pid, "title": "Pulse 5 — price and battery", "cohort_filter": "phone_age_years > 2"})
    await survey("sv-eval", d1)
    for _ in range(1440):
        await e.tick()
    w1 = store.get("surveys", "sv-eval")
    panel = [p["agent_id"] for p in w1.get("participants", []) if p.get("rsvp") == "attended"]
    d2 = {**d1, "survey_id": "sv-eval-w2", "wave": 2, "panel_id": "sv-eval", "parent_survey_id": "sv-eval",
          "panel_agent_ids": panel, "max_participants": max(1, len(panel))}
    await survey("sv-eval-w2", d2)
    for _ in range(5):
        await asyncio.sleep(0.05)
    await e.bus.flush()
    return {"engine": e, "store": store, "sink": sink, "pid": pid, "qs": QS, "settings": s}


async def eval_insights(w: dict[str, Any]) -> dict[str, Any]:
    """Faithfulness + structure on the 10-question benchmark."""
    from agents.insights_assistant import Assistant
    from insights.tools import DuckRunner, Ledger, Tools
    from shared.llm import get_llm

    db = w["sink"].db
    qs = yaml.safe_load((ROOT / "evals" / "insights_questions.yaml").read_text(encoding="utf-8"))
    llm = get_llm(w["settings"], fresh=True)
    rows, faithful, verbatim, total_q = [], 0, 0, 0
    for item in qs:
        t0 = time.time()
        tools = Tools(DuckRunner(db), Ledger(), llm=llm, store=w["store"],
                      embed=lambda xs: asyncio.get_event_loop().run_until_complete(llm.embed(xs))
                      if False else _sync_embed(llm, xs))
        a = Assistant(tools, llm, products=[{"product_id": w["pid"], "name": "Pulse 5", "price_inr": 18999}])
        ans = None
        async for x in a.ask(item["q"]):
            ans = x.get("answer", ans)
        dt = time.time() - t0
        exp = item.get("expect", {})
        from insights import faithfulness

        errs = faithfulness.check(ans, tools.ledger)
        ok_f = not errs
        faithful += ok_f
        nq = len(ans.get("quotes", []))
        total_q += nq
        verbatim += nq - sum(1 for e in errs if e.startswith("quote"))
        checks = {"faithful": ok_f}
        if exp.get("numbers"):
            checks["numbers"] = bool(ans.get("numbers"))
        if exp.get("quotes"):
            checks["quotes"] = nq >= int(exp["quotes"])
        if exp.get("private_quotes"):
            checks["private_labelled"] = all(q["private"] for q in ans.get("quotes", [])) and nq > 0
        if exp.get("sql"):
            checks["sql"] = bool(ans.get("sql"))
        if exp.get("chart"):
            checks["chart"] = bool(ans.get("charts"))
        if exp.get("decline"):
            checks["declined"] = not ans.get("numbers") and "can't" in ans.get("answer_md", "")
        rows.append({"id": item["id"], "pass": all(checks.values()), "checks": checks, "seconds": round(dt, 2),
                     "cost_usd": ans.get("cost_usd", 0.0), "answer": ans.get("answer_md", "")[:160]})
    return {"rows": rows, "faithfulness": faithful / len(qs), "verbatim": (verbatim / total_q) if total_q else 1.0,
            "pass_rate": sum(r["pass"] for r in rows) / len(rows), "backend": type(llm).__name__}


def _sync_embed(llm: Any, texts: list[str]) -> list[list[float]]:
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(llm.embed(texts))).result()


def eval_survey(w: dict[str, Any]) -> dict[str, Any]:
    """B14 realism metrics from the logged survey events."""
    from engine.survey.recruit import cfg

    db = w["sink"].db
    ans = db.query("SELECT * FROM v_survey_answers WHERE survey_id = 'sv-eval'")
    msgs = db.query("SELECT speaker_id, COUNT(*) AS n FROM v_survey_messages WHERE survey_id = 'sv-eval' "
                    "AND speaker_id IS NOT NULL GROUP BY speaker_id")
    e = w["engine"]
    attended = sorted({int(a["agent_id"]) for a in ans})
    said = {int(r["speaker_id"]): int(r["n"]) for r in msgs}
    ext = [float(e.world.profiles[a].persona.big5.get("E", 0.5)) for a in attended]
    cnt = [said.get(a, 0) for a in attended]
    r_ext = pearson(ext, cnt)
    # conformity: high-A low-confidence minority vs low-A
    def conform_rate(sel: Any) -> tuple[float, int]:
        rows = [a for a in ans if a["prestance"] and a["table_majority"] and a["prestance"] != a["table_majority"]
                and sel(a)]
        ch = [a for a in rows if a["changed_from_prestance"] and str(a["answer"]) == str(a["table_majority"])]
        return (len(ch) / len(rows) if rows else 0.0), len(rows)
    big5 = {a: e.world.profiles[a].persona.big5 for a in attended}
    hi, n_hi = conform_rate(lambda a: float(big5[int(a["agent_id"])].get("A", .5)) > 0.6)
    lo, n_lo = conform_rate(lambda a: float(big5[int(a["agent_id"])].get("A", .5)) < 0.4)
    # experience dominance
    exp_ids = set()
    if e.commerce is not None:
        exp_ids = {int(k.split("|")[0]) for k, p in e.commerce.pairs.items() if k.endswith(f"|{w['pid']}")
                   and (p.stage == "purchased" or p.inquired)}
    ex_rows = [a for a in ans if int(a["agent_id"]) in exp_ids and a["prestance"]]
    kept = [a for a in ex_rows if not a["changed_from_prestance"]]
    exp_dom = len(kept) / len(ex_rows) if ex_rows else None
    # shift realism
    focus = [a for a in ans if a["prestance"]]
    changed = [a for a in focus if a["changed_from_prestance"]]
    share = len(changed) / len(focus) if focus else 0.0
    cited = all(a["influenced_by_first"] or a["reason"] for a in changed)
    lo_b, hi_b = cfg()["shift_target_band"]
    # waves
    import api.surveys as sv
    from insights.tools import DuckRunner

    sv.default_runner = lambda: DuckRunner(db)  # type: ignore[assignment]
    sv.store = lambda: w["store"]  # type: ignore[assignment]
    asyncio.run(sv.explain_changes("sv-eval-w2"))
    wv = sv.waves("sv-eval-w2")
    # a change is explained when it cites the agent's own events, or honestly says there were none to cite
    cited_ev = [c for c in wv["changes"] if c.get("why") and c.get("why_event_ids")]
    no_cause = [c for c in wv["changes"] if c.get("why") and not c.get("why_event_ids")
                and c["why"].startswith("no clear cause")]
    wave_ok = ((len(cited_ev) + len(no_cause)) / len(wv["changes"])) if wv["changes"] else None
    # satisficing
    qorder = {q["question_id"]: i for i, q in enumerate(w["qs"])}
    late = [a for a in ans if qorder.get(a["question_id"], 0) >= 1]
    early = [a for a in ans if qorder.get(a["question_id"], 0) == 0]
    sat = lambda rows: sum(1 for a in rows if a["effort"] == "satisficed") / max(1, len(rows))  # noqa: E731
    low_c = [a for a in ans if float(big5[int(a["agent_id"])].get("C", .5)) < 0.35]
    high_c = [a for a in ans if float(big5[int(a["agent_id"])].get("C", .5)) >= 0.35]
    return {"attended": len(attended), "r_extraversion": round(r_ext, 3), "conform_highA": round(hi, 3), "n_highA": n_hi,
            "conform_lowA": round(lo, 3), "n_lowA": n_lo, "experience_dominance": exp_dom, "n_experienced": len(ex_rows),
            "shift_share": round(share, 3), "band": [lo_b, hi_b], "changes_cited": cited,
            "wave_changes": len(wv["changes"]), "wave_explained": wave_ok, "wave_no_cause": len(no_cause),
            "satisfice_late": round(sat(late), 3), "satisfice_early": round(sat(early), 3),
            "satisfice_lowC": round(sat(low_c), 3), "satisfice_highC": round(sat(high_c), 3)}


def eval_opinion(w: dict[str, Any]) -> dict[str, Any]:
    """Phase-1 opinion engine checks on the finished world: diversity, income divergence, ego gap, reference effect.

    Adds one synthetic premium phone (better display and software, far pricier) to the catalog and shows it to every
    agent as a review, then measures what each person now thinks."""
    from statistics import mean, pstdev

    from shared.schemas.product import Product

    e, pid = w["engine"], w["pid"]
    op = e.opinion
    profiles = e.world.profiles
    base = next(lp.p for lp in e.media.live.values() if lp.p.product_id == pid)
    lumen = Product(product_id="lumen-pro", name="Lumen Pro", brand="Lumen", category="Smartphone", price_inr=92000,
                    launch_offer=None, features=["6.7\" 144 Hz LTPO display", "Snapdragon 8 Gen 3",
                                                 "7 years of OS updates", "5,000 mAh battery"], claims=[],
                    target_personas=[], audience=[], strategy={}, creatives=[], plan=None, status="live", color="#fff")
    op.set_catalog([base, lumen])
    ids = [p.agent_id for p in profiles if p.special_role == "none"]
    aware = [a for a in ids if op.aware_of(a, pid)]
    for a in ids:                                    # everyone gets to know Pulse 5 as it is advertised …
        if not op.aware_of(a, pid):
            op.evidence(a, pid, ["battery", "camera", "display"], "ad")
    before = {a: op.attitude(a, pid) for a in ids}
    std_before = pstdev(list(before.values())) if len(before) > 2 else 0.0
    for a in ids:                                    # … then a better, pricier phone
        op.evidence(a, "lumen-pro", None, "review")
    after = {a: op.attitude(a, pid) for a in ids}
    from commerce.need import affordability

    top: dict[str, dict[str, int]] = {}
    for a in ids:                                    # what they would actually buy: only what they can pay for, by liking
        band = profiles[a].income_band
        money = profiles[a].money.model_dump()
        can = {p: price for p, price in ((pid, base.price_inr), ("lumen-pro", lumen.price_inr))
               if affordability(price, money)[1] is not None}      # same rule as commerce.purchase.gate
        if not can:
            continue
        pick = max(can, key=lambda p: (op.attitude(a, p) + 1) / 2 * (0.6 + 0.4 * affordability(can[p], money)[0]))
        top.setdefault(band, {}).setdefault(pick, 0)
        top[band][pick] += 1
    lead = {b: max(c, key=lambda k: c[k]) for b, c in top.items() if sum(c.values()) >= 5}
    lows = [a for a in ids if profiles[a].income_band in ("<25k", "25-50k")]
    gap = [a for a in lows if (lambda pub_priv: pub_priv[0] < pub_priv[1] - 0.1)(
        (op.expressed(a, "lumen-pro")[0], op.private_attitude(a, "lumen-pro")))]
    care = [a for a in ids if op.W[a, op.attrs.index("display")] > sorted(op.W[:, op.attrs.index("display")])[len(ids) // 2]]
    drop = mean(after[a] - before[a] for a in care) if care else 0.0
    return {"n": len(ids), "n_aware_from_run": len(aware), "att_std": round(std_before, 3),
            "leader_by_income": lead, "gap_share_low_income": round(len(gap) / max(1, len(lows)), 3),
            "drop_after_better_phone": round(drop, 3), "n_care_display": len(care)}


def write(ins: dict[str, Any], sv: dict[str, Any], meta: dict[str, Any], op: dict[str, Any] | None = None) -> None:
    """Append a dated section to evals/RESULTS.md."""
    ok = lambda b: "PASS" if b else "FAIL"  # noqa: E731
    lines = [f"\n## Evals · {time.strftime('%Y-%m-%d %H:%M')} · backend {ins['backend']} · {meta}\n",
             "### Insights benchmark (evals/insights_questions.yaml)",
             f"- Faithfulness: **{ins['faithfulness']:.0%}** (target ≥ 95%) — {ok(ins['faithfulness'] >= 0.95)}",
             f"- Quotes verbatim: **{ins['verbatim']:.0%}** · structure pass rate {ins['pass_rate']:.0%}", "",
             "| id | pass | checks | s | $ |", "|---|---|---|---|---|"]
    for r in ins["rows"]:
        lines.append(f"| {r['id']} | {ok(r['pass'])} | {', '.join(f'{k}={v}' for k, v in r['checks'].items())} | "
                     f"{r['seconds']} | {r['cost_usd']} |")
    e = sv
    lines += ["", "### Survey realism (evals/run.py · addendum B14)",
              f"- Attended: {e['attended']}",
              f"- Extraversion ↔ messages: r = {e['r_extraversion']} (target > 0.3) — {ok(e['r_extraversion'] > 0.3)}",
              f"- Conformity toward majority: high-A {e['conform_highA']} (n={e['n_highA']}) vs low-A {e['conform_lowA']} "
              f"(n={e['n_lowA']}) — {ok(e['conform_highA'] >= e['conform_lowA'])}",
              f"- Experience dominance: {e['experience_dominance']} (n={e['n_experienced']}, target ≥ 0.8) — "
              + ("INCONCLUSIVE (n < 5)" if e['n_experienced'] < 5 else ok(e['experience_dominance'] >= 0.8)),
              f"- Shift realism: {e['shift_share']} changed (band {e['band']}) · every change cited: {e['changes_cited']} — "
              f"{ok(e['band'][0] <= e['shift_share'] <= e['band'][1] and e['changes_cited'])}",
              f"- Wave changes explained by own events (or 'no clear cause' when none, n={e['wave_no_cause']}): "
              f"{e['wave_explained']} of {e['wave_changes']} — "
              f"{ok(e['wave_explained'] is None or e['wave_explained'] >= 0.99)}",
              f"- Satisficing: late {e['satisfice_late']} vs first {e['satisfice_early']}; low-C {e['satisfice_lowC']} vs "
              f"high-C {e['satisfice_highC']} — {ok(e['satisfice_late'] >= e['satisfice_early'] and e['satisfice_lowC'] >= e['satisfice_highC'])}"]
    if op is not None:
        lines += ["", "### Opinion engine (evals/run.py · phase 1)",
                  f"- Attitude spread across {op['n']} residents (std): {op['att_std']} (target ≥ 0.2) — {ok(op['att_std'] >= 0.2)}",
                  f"- Phone they would buy (only what they can pay for, by liking), by income band: {op['leader_by_income']} (target: not the same "
                  f"everywhere) — "
                  f"{ok(len(set(op['leader_by_income'].values())) >= 2)}",
                  f"- Low-income residents who talk down an unaffordable premium phone: {op['gap_share_low_income']:.0%} "
                  f"(band 5–25%) — {ok(0.05 <= op['gap_share_low_income'] <= 0.25)}",
                  f"- Attitude to the first phone after a better one appears, for people who care about display: "
                  f"{op['drop_after_better_phone']:+} (target < 0) — {ok(op['drop_after_better_phone'] < 0)}"]
    OUT.parent.mkdir(exist_ok=True)
    prev = OUT.read_text(encoding="utf-8") if OUT.exists() else "# Eval results\n"
    OUT.write_text(prev + "\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Run all phase-5 evals."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=400)
    ap.add_argument("--days", type=float, default=2.0)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        w = asyncio.run(build_world(a.agents, a.days, tmp))
        ins = asyncio.run(eval_insights(w))
        sv = eval_survey(w)
        op = eval_opinion(w)
        write(ins, sv, {"agents": a.agents, "days": a.days}, op)
        print(json.dumps({"insights": {k: v for k, v in ins.items() if k != "rows"}, "survey": sv, "opinion": op},
                         indent=1, default=str))


if __name__ == "__main__":
    main()
