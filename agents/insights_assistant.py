"""Insights assistant (I-01, I-09): Gemini 3.1 Pro plans tool calls, then writes a typed AskAnswer that is checked
for faithfulness (numbers ↔ tool results by source_ref, verbatim quotes, private labels); regenerate once, else drop.

Offline (fake backend) a deterministic rule planner + template composer stands in, so the pipeline, the SSE steps
and the faithfulness checks run without a model.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from insights import faithfulness
from insights.sqlguard import SQLRejected
from insights.tools import Tools, chart_option
from media.screen import get_screener, wrap
from shared.llm import FakeGemini, LLMClient
from shared.models import MODEL_PRO

PROMPTS = Path(__file__).resolve().parents[1] / "shared" / "prompts"
MAX_ROUNDS = 5
ToolName = Literal["describe_data", "run_sql", "semantic_search", "cohort", "likely_buyers", "chart",
                   "survey_results"]


class ToolArgs(BaseModel):
    """Flat argument bag (each tool reads its own fields)."""

    sql: str | None = None
    filter_expr: str | None = None
    text: str | None = None
    product_id: str | None = None
    kinds: list[str] | None = None
    cohort_ref: str | None = None
    private: bool | None = None
    k: int | None = None
    group_by: list[str] | None = None
    survey_ref: str | None = None
    question_id: str | None = None
    chart_type: Literal["bar", "hbar", "line", "pie"] | None = None
    title: str | None = None
    x: list[str] | None = None
    series_name: str | None = None
    series_data: list[float] | None = None
    source_ref: str | None = None


class Call(BaseModel):
    """One tool call."""

    tool: ToolName
    args: ToolArgs = Field(default_factory=ToolArgs)


class Step(BaseModel):
    """Planner output for one round."""

    thought: str
    calls: list[Call] = Field(default_factory=list, max_length=4)
    done: bool = False


class Number(BaseModel):
    """A key number with its source."""

    label: str
    value: float
    source_ref: str


class Quote(BaseModel):
    """A verbatim quote."""

    agent_id: int | None = None
    name: str | None = None
    kind: str | None = None
    t: int | None = None
    text: str
    private: bool = False


class Series(BaseModel):
    """Chart series."""

    name: str
    data: list[float]


class ChartSpec(BaseModel):
    """Small chart spec turned into an ECharts option."""

    type: Literal["bar", "hbar", "line", "pie"] = "bar"
    title: str = ""
    x: list[str] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    source_ref: str | None = None


class AskAnswer(BaseModel):
    """INTERFACES §5 AskAnswer (+ suggestions)."""

    answer_md: str
    numbers: list[Number] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)
    sql: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


def _p(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def _compact(v: Any, n: int = 3500) -> str:
    s = json.dumps(v, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …(truncated)"


class Assistant:
    """One question → streamed steps + a faithful AskAnswer."""

    def __init__(self, tools: Tools, llm: LLMClient, *, products: list[dict[str, Any]] | None = None,
                 window: str = "") -> None:
        self.tools, self.llm = tools, llm
        self.products = products or []
        self.window = window
        self.offline = isinstance(llm, FakeGemini)
        self.cost_usd = 0.0
        self.sql: list[str] = []
        self.last_cohort: str | None = None

    # ------------------------------------------------------------------ tool dispatch
    async def call(self, c: Call) -> tuple[str, Any]:
        """Run one tool; returns (ref or tool name, result) — errors come back as data for the planner."""
        a = c.args
        t = self.tools
        try:
            if c.tool == "describe_data":
                d = t.describe_data()
                return "describe_data", {v: list(x["columns"]) for v, x in d["views"].items()}
            if c.tool == "run_sql":
                r = t.run_sql(a.sql or "")
                self.sql.append(r["sql"])
                return r["ref"], {"ref": r["ref"], "columns": r["columns"], "rows": r["rows"][:60],
                                  "n_rows": len(r["rows"])}
            if c.tool == "cohort":
                r = t.cohort(a.filter_expr or "")
                self.last_cohort = r["ref"]
                return r["ref"], {"ref": r["ref"], "size": r["size"], "filter": r["filter"]}
            if c.tool == "semantic_search":
                cref = self.last_cohort if a.cohort_ref == "@cohort" else a.cohort_ref
                f = {"product_id": a.product_id, "kinds": a.kinds, "cohort_ref": cref, "private": a.private}
                rows = t.semantic_search(a.text or "", {k: v for k, v in f.items() if v is not None}, a.k or 12)
                return "search", [{"text_id": r["text_id"], "agent_id": r["agent_id"], "name": r["name"],
                                   "kind": r["kind"], "t": r["t"], "private": r["private"], "text": r["text"]}
                                  for r in rows]
            if c.tool == "likely_buyers":
                r = t.likely_buyers(a.product_id or "", a.group_by)
                return r["ref"], {"ref": r["ref"], "rows": r["rows"][:40]}
            if c.tool == "survey_results":
                r = t.survey_results(a.survey_ref or "latest", a.question_id)
                return r["ref"], r
            if c.tool == "chart":
                spec = {"type": a.chart_type or "bar", "title": a.title or "", "x": a.x or [],
                        "series": [{"name": a.series_name or "", "data": a.series_data or []}],
                        "source_ref": a.source_ref}
                return "chart", t.chart(spec)
        except SQLRejected as e:
            return "error", {"error": str(e)}
        except Exception as e:  # noqa: BLE001 — tool errors are returned to the planner as data
            return "error", {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        return "error", {"error": "unknown tool"}

    # ------------------------------------------------------------------ main
    async def ask(self, question: str) -> AsyncIterator[dict[str, Any]]:
        """Yield {"step": …} items, then {"answer": AskAnswer dict}."""
        sc = get_screener().screen(question)
        if not sc.ok or "prompt_injection" in sc.flagged:
            yield {"step": "Question screened: refused"}
            yield {"answer": AskAnswer(answer_md="I can't help with that question here. Insights answers questions "
                                                 "about the simulated world's data only.",
                                       caveats=["Question refused by screening."]).model_dump()}
            return
        yield {"step": "Reading the data dictionary"}
        results: list[dict[str, Any]] = []
        if self.offline:
            plan = self._rule_plan(question)
            for c in plan:
                yield {"step": _label(c)}
                ref, res = await self.call(c)
                results.append({"tool": c.tool, "args": c.args.model_dump(exclude_none=True), "ref": ref,
                                "result": res})
            ans = self._compose_offline(question, results)
        else:
            for _ in range(MAX_ROUNDS):
                step = await self._plan(question, results)
                if step.thought:
                    yield {"step": step.thought[:160]}
                for c in step.calls:
                    yield {"step": _label(c)}
                    ref, res = await self.call(c)
                    results.append({"tool": c.tool, "args": c.args.model_dump(exclude_none=True), "ref": ref,
                                    "result": res})
                if step.done or not step.calls:
                    break
            yield {"step": "Writing the answer"}
            ans = await self._compose(question, results, None)
            errs = faithfulness.check(ans, self.tools.ledger)
            if errs:
                yield {"step": f"Faithfulness check failed ({len(errs)}); regenerating once"}
                ans = await self._compose(question, results, errs)
        errs = faithfulness.check(ans, self.tools.ledger)
        if errs:
            ans, _ = faithfulness.drop_unfaithful(ans, self.tools.ledger)
        ans["sql"] = list(dict.fromkeys([*self.sql, *ans.get("sql", [])]))
        ans["charts"] = [chart_option(c) if "series" in c and "xAxis" not in c else c for c in ans.get("charts", [])]
        ans.setdefault("caveats", [])
        ans["caveats"] = [*ans["caveats"], f"Simulated data{(' · ' + self.window) if self.window else ''}."]
        ans["faithful"] = not faithfulness.check(ans, self.tools.ledger)
        ans["cost_usd"] = round(self.cost_usd, 5)
        yield {"step": "Checked numbers and quotes against the data"}
        yield {"answer": ans}

    async def _plan(self, question: str, results: list[dict[str, Any]]) -> Step:
        prompt = (_p("insights_plan").replace("{dictionary}", _compact(self.tools.describe_data(), 9000))
                  .replace("{products}", _compact([{k: p.get(k) for k in ("product_id", "name", "price_inr", "status")}
                                                   for p in self.products]))
                  .replace("{results}", _compact(results, 12000)).replace("{question}", wrap(question, "question")))
        res = await self.llm.generate(MODEL_PRO, prompt, Step, purpose="insights_plan", reasoning="low",
                                      max_tokens=1200, priority_class="interactive")
        self.cost_usd += res.usage.cost_usd
        return res.data

    async def _compose(self, question: str, results: list[dict[str, Any]], errs: list[str] | None) -> dict[str, Any]:
        prompt = (_p("insights_answer").replace("{results}", _compact(results, 16000))
                  .replace("{errors}", "\n".join(errs or []) or "(none)").replace("{question}", wrap(question, "question")))
        res = await self.llm.generate(MODEL_PRO, prompt, AskAnswer, purpose="insights_answer", reasoning="low",
                                      max_tokens=2000, priority_class="interactive")
        self.cost_usd += res.usage.cost_usd
        out = res.data.model_dump()
        out["charts"] = [c for c in out["charts"]]
        return out

    # ------------------------------------------------------------------ offline planner + composer
    def _product_in(self, q: str) -> dict[str, Any] | None:
        ql = q.lower()
        for p in self.products:
            if p.get("name", "").lower() in ql or p.get("product_id", "") in ql:
                return p
        return None

    def _rule_plan(self, q: str) -> list[Call]:
        ql = q.lower()
        p = self._product_in(q)
        domain = ("phone", "product", "hoarding", "billboard", "store", "survey", "focus", "people", "agent", "buy", "bought",
                  "aware", "segment", "inquir", "review", "community", "poll", "thought", "chat", "talk", "site", "purchase")
        if p is None and not any(w in ql for w in domain):
            return []
        pid = p["product_id"] if p else None
        if re.search(r"older than (\d+)", ql) or "old phone" in ql:
            m = re.search(r"older than (\d+)", ql)
            yrs = int(m.group(1)) if m else 5
            return [Call(tool="cohort", args=ToolArgs(filter_expr=f"phone_age_years > {yrs}")),
                    Call(tool="run_sql", args=ToolArgs(sql=(
                        "SELECT b.product_id, COUNT(*) AS agents, "
                        "SUM(CASE WHEN b.stage IN ('curious','researching','inquiring','deciding','purchased') "
                        "THEN 1 ELSE 0 END) AS curious_plus FROM beliefs_latest b JOIN agents_latest a "
                        f"ON a.agent_id = b.agent_id WHERE a.phone_age_years > {yrs} AND b.product_id IS NOT NULL "
                        "GROUP BY b.product_id ORDER BY curious_plus DESC"))),
                    Call(tool="semantic_search", args=ToolArgs(text="why interested in a new phone battery price camera",
                                                               cohort_ref="@cohort", k=8))]
        if any(w in ql for w in ("hoarding", "billboard", "facing", "site")):
            return [Call(tool="run_sql", args=ToolArgs(sql=(
                        "SELECT site_id, SUM(ots) AS ots, SUM(notices) AS notices, SUM(notices) / SUM(ots) AS notice_rate "
                        "FROM v_site_daily GROUP BY site_id HAVING SUM(ots) >= 20 ORDER BY notice_rate DESC LIMIT 10"))),
                    Call(tool="run_sql", args=ToolArgs(sql=(
                        "SELECT site_id, facing, SUM(ots) AS ots, SUM(notices) / SUM(ots) AS notice_rate FROM v_site_daily "
                        "WHERE site_id IN (SELECT site_id FROM v_site_daily GROUP BY site_id "
                        "HAVING COUNT(DISTINCT facing) > 1) GROUP BY site_id, facing ORDER BY site_id, facing"))),
                    Call(tool="semantic_search", args=ToolArgs(text="noticed the billboard", kinds=["thought"], k=6))]
        if any(w in ql for w in ("focus group", "survey", "changed their mind", "wave", "panel")):
            return [Call(tool="survey_results", args=ToolArgs(survey_ref=pid or "latest"))]
        if any(w in ql for w in ("privately", "private", "not say", "really think")):
            return [Call(tool="semantic_search", args=ToolArgs(text=f"{p['name'] if p else 'phone'} worry doubt price",
                                                               product_id=pid, private=True, k=6)),
                    Call(tool="semantic_search", args=ToolArgs(text=f"{p['name'] if p else 'phone'}",
                                                               kinds=["message"], k=6))]
        if any(w in ql for w in ("first hear", "source", "channel", "path")):
            return [Call(tool="run_sql", args=ToolArgs(sql="SELECT product_id, channel, COUNT(*) AS agents FROM "
                                                           "v_first_heard GROUP BY product_id, channel ORDER BY agents DESC"))]
        if any(w in ql for w in ("segment", "likely", "who will buy", "buyers")) and pid:
            return [Call(tool="likely_buyers", args=ToolArgs(product_id=pid, group_by=["age_band", "income_band"]))]
        if any(w in ql for w in ("bought", "purchase", "sales", "baseline")):
            return [Call(tool="run_sql", args=ToolArgs(sql=(
                "SELECT 'our products' AS choice, (SELECT COUNT(*) FROM v_purchases WHERE is_ours) AS purchases "
                "UNION ALL SELECT 'baseline market' AS choice, (SELECT COUNT(*) FROM v_purchases WHERE NOT is_ours) "
                "AS purchases")))]
        if any(w in ql for w in ("store", "inquir", "salesperson")):
            return [Call(tool="run_sql", args=ToolArgs(sql="SELECT product_id, outcome, COUNT(*) AS inquiries, "
                                                           "AVG(satisfaction) AS satisfaction FROM v_inquiries "
                                                           "GROUP BY product_id, outcome ORDER BY inquiries DESC"))]
        return [Call(tool="run_sql", args=ToolArgs(sql="SELECT product_id, MAX(aware) AS aware, SUM(inquiries) AS "
                                                       "inquiries, SUM(purchases) AS purchases FROM v_funnel_daily "
                                                       "GROUP BY product_id ORDER BY aware DESC"))]

    def _compose_offline(self, q: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Template answer built only from tool results (faithful by construction)."""
        nums: list[dict[str, Any]] = []
        quotes: list[dict[str, Any]] = []
        charts: list[dict[str, Any]] = []
        lines: list[str] = []
        names = {p["product_id"]: p["name"] for p in self.products}
        for r in results:
            res, ref = r["result"], r["ref"]
            if r["tool"] == "cohort" and isinstance(res, dict) and "size" in res:
                nums.append({"label": f"agents with {res['filter']}", "value": res["size"], "source_ref": ref})
                lines.append(f"**{res['size']}** agents match `{res['filter']}`.")
            elif r["tool"] in ("run_sql", "likely_buyers", "survey_results") and isinstance(res, dict) and res.get("rows"):
                rows = res["rows"]
                cols = list(rows[0].keys())
                label_col = cols[0]
                val_col = next((c for c in reversed(cols) if isinstance(rows[0][c], int | float)
                                and not isinstance(rows[0][c], bool)), None)
                if val_col is None:
                    continue
                top = rows[:6]
                for row in top[:4]:
                    nums.append({"label": f"{names.get(row[label_col], row[label_col])} · {val_col}",
                                 "value": float(row[val_col] or 0), "source_ref": ref})
                lines.append("; ".join(f"{names.get(row[label_col], row[label_col])}: {_fmt(row[val_col])} {val_col}"
                                       for row in top[:4]) + ".")
                charts.append({"type": "bar", "title": val_col.replace("_", " "),
                               "x": [str(names.get(row[label_col], row[label_col])) for row in top],
                               "series": [{"name": val_col, "data": [float(row[val_col] or 0) for row in top]}],
                               "source_ref": ref})
            elif r["tool"] == "semantic_search" and isinstance(res, list):
                for row in res[:4]:
                    quotes.append({"agent_id": row["agent_id"], "name": row["name"], "kind": row["kind"],
                                   "t": row["t"], "text": row["text"], "private": row["private"]})
            elif r["tool"] in ("run_sql", "cohort", "survey_results") and isinstance(res, dict) and res.get("error"):
                lines.append(f"(A query failed: {res['error'][:120]})")
        if not results:
            lines.append("I can't answer that from the simulated world's data — Insights only knows what the agents in "
                         "Indiranagar saw, thought, said and bought.")
        elif not lines and not quotes:
            lines.append("There isn't enough data in the simulated world yet to answer that.")
        md = " ".join(lines)
        sugg = ["Which hoarding gets noticed most and does facing matter?",
                "What do people privately think but not say about Pulse 5?",
                "Who is most likely to buy Pulse 5, by age and income?"]
        return {"answer_md": md, "numbers": nums[:8], "charts": charts[:1], "quotes": quotes[:4], "sql": [],
                "caveats": ["Small simulated samples; differences of a few agents are noise.",
                            "Offline mode: deterministic template answer (no model)."],
                "suggestions": sugg}


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v < 1:
        return f"{v:.1%}"
    return f"{v:,.0f}" if isinstance(v, int | float) else str(v)


def _label(c: Call) -> str:
    a = c.args
    return {"run_sql": "Running SQL on the curated views", "cohort": f"Building cohort `{a.filter_expr}`",
            "semantic_search": f"Searching thoughts and messages: “{(a.text or '')[:40]}”",
            "likely_buyers": f"Scoring likely-buyer segments for {a.product_id}",
            "survey_results": "Reading survey results", "chart": "Drawing a chart",
            "describe_data": "Reading the data dictionary"}.get(c.tool, c.tool)
