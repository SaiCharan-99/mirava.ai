"""Survey results for Insights and the Survey Room API (addendum B5, B10): distributions, shift, waves, quotes."""

from __future__ import annotations

from typing import Any


def resolve(runner: Any, ref: str) -> dict[str, Any] | None:
    """Survey row by id, product id or 'latest' (most recent completed)."""
    rows, _ = runner.run("SELECT * FROM v_surveys ORDER BY created_t DESC", None, trusted=True)
    if not rows:
        return None
    if ref and ref != "latest":
        hit = next((r for r in rows if r["survey_id"] == ref), None) or \
            next((r for r in rows if r.get("product_id") == ref and r["status"] == "completed"), None) or \
            next((r for r in rows if ref.lower() in str(r.get("title", "")).lower()), None)
        if hit:
            return hit
    return next((r for r in rows if r["status"] == "completed"), rows[0])


def survey_results(runner: Any, survey_ref: str = "latest", question_id: str | None = None) -> dict[str, Any]:
    """Rows for the assistant: per question distribution + changed counts, the changers with reasons, waves."""
    s = resolve(runner, survey_ref)
    if s is None:
        return {"survey_id": None, "rows": [], "quotes": [], "note": "no surveys have run yet"}
    sid = s["survey_id"]
    p = {"s": sid}
    qf = " AND question_id = @q" if question_id else ""
    if question_id:
        p["q"] = question_id
    dist, _ = runner.run(f"SELECT question_id, answer, COUNT(*) AS n FROM v_survey_answers WHERE survey_id = @s{qf} "
                         "GROUP BY question_id, answer ORDER BY question_id, n DESC", p, trusted=True)
    shift, _ = runner.run(f"SELECT question_id, COUNT(*) AS answers, SUM(CASE WHEN changed THEN 1 ELSE 0 END) AS changed "
                          f"FROM v_survey_shift WHERE survey_id = @s{qf} GROUP BY question_id ORDER BY question_id",
                          p, trusted=True)
    changers, _ = runner.run(
        f"SELECT s.question_id, s.agent_id, a.name, s.prestance, s.final_answer, s.influence_type, s.reason, s.event_id, s.t "
        f"FROM v_survey_shift s LEFT JOIN agents_latest a ON a.agent_id = s.agent_id WHERE s.survey_id = @s AND s.changed{qf} "
        "ORDER BY s.question_id, s.agent_id LIMIT 60", p, trusted=True)
    waves, _ = runner.run("SELECT wave, survey_id, question_id, answer, COUNT(*) AS n FROM v_survey_waves WHERE panel_id = "
                          "(SELECT COALESCE(panel_id, survey_id) FROM v_surveys WHERE survey_id = @s LIMIT 1) "
                          "GROUP BY wave, survey_id, question_id, answer ORDER BY wave, question_id, n DESC", {"s": sid},
                          trusted=True)
    by_inf: dict[str, int] = {}
    for c in changers:
        by_inf[c["influence_type"]] = by_inf.get(c["influence_type"], 0) + 1
    rows = [{"question_id": r["question_id"], "answers": int(r["answers"]), "changed": int(r["changed"] or 0),
             "changed_share": round(int(r["changed"] or 0) / max(1, int(r["answers"])), 3)} for r in shift]
    quotes = [{"text_id": c["event_id"], "agent_id": c["agent_id"], "name": c.get("name"), "kind": "survey_answer",
               "t": c["t"], "text": c["reason"], "private": False} for c in changers if c.get("reason")][:12]
    return {"survey_id": sid, "title": s.get("title"), "mode": s.get("mode"), "wave": s.get("wave"),
            "attended": s.get("attended"), "rows": rows, "distribution": dist, "changers": changers,
            "influence": by_inf, "waves": waves, "quotes": quotes}
