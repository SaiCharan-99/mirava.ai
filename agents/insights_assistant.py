"""Insights assistant (I-01, I-09): Gemini 3.1 Pro plans tool calls, then writes a typed AskAnswer that is checked
for faithfulness (numbers ↔ tool results by source_ref, verbatim quotes, private labels); regenerate once, else drop.

Offline (fake backend) a deterministic rule planner + template composer stands in, so the pipeline, the SSE steps
and the faithfulness checks run without a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
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
STARTER_QUESTIONS = (
    "How many people are considering each product?",
    "Where did people first hear about our products?",
    "How many purchases were of our products versus other phones?",
)
MAX_ROUNDS = 3
CALL_TIMEOUT_S = 20.0            # one slow model call can't eat the whole budget
log = logging.getLogger(__name__)


def ask_budget_s() -> float:
    """Seconds an Ask may take end to end (Firebase Hosting cuts proxied requests at 60 s)."""
    try:
        return float(os.environ.get("ASK_BUDGET_S", "52"))
    except ValueError:
        return 45.0
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
    unit: Literal["count", "fraction", "percent", "value"] = "count"


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
                 window: str = "", budget_s: float | None = None, clock: Any = time.monotonic) -> None:
        self.tools, self.llm = tools, llm
        self.budget_s = ask_budget_s() if budget_s is None else budget_s
        self.clock = clock
        self.products = products or []
        self.window = window
        self.offline = isinstance(llm, FakeGemini)
        self.cost_usd = 0.0
        self.sql: list[str] = []
        self.last_cohort: str | None = None
        self.known_ids: set[str] = set()         # every product id/name ever seen (to filter stale ones out)

    # ------------------------------------------------------------------ tool dispatch
    async def call(self, c: Call) -> tuple[str, Any]:
        return await asyncio.wait_for(asyncio.to_thread(self._call_sync, c), 12)

    def _call_sync(self, c: Call) -> tuple[str, Any]:
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
        t0 = self.clock()
        left = lambda: self.budget_s - (self.clock() - t0)  # noqa: E731
        failure: str | None = None
        ans: dict[str, Any] | None = None
        try:
            if self.offline:
                for c in self._rule_plan(question):
                    yield {"step": _label(c)}
                    ref, res = await self.call(c)
                    results.append({"tool": c.tool, "args": c.args.model_dump(exclude_none=True), "ref": ref,
                                    "result": res})
                ans = self._compose_offline(question, results)
            else:
                direct = question.strip() in STARTER_QUESTIONS
                if direct:
                    for c in self._rule_plan(question):
                        yield {"step": _label(c)}
                        ref, res = await self.call(c)
                        results.append({"tool": c.tool, "args": c.args.model_dump(exclude_none=True),
                                        "ref": ref, "result": res})
                seen_calls: set[str] = set()
                for _ in range(0 if direct else MAX_ROUNDS):
                    if left() < 28:                      # keep enough time to compose (slower providers need ~20 s)
                        yield {"step": "Time budget reached; answering from what I have"}
                        break
                    step = await self._plan(question, results, timeout=min(CALL_TIMEOUT_S, left() - 20))
                    if step.thought:
                        yield {"step": step.thought[:160]}
                    for c in step.calls:
                        key = c.model_dump_json()
                        if key in seen_calls or left() < 24:
                            continue
                        seen_calls.add(key)
                        yield {"step": _label(c)}
                        ref, res = await self.call(c)
                        results.append({"tool": c.tool, "args": c.args.model_dump(exclude_none=True), "ref": ref,
                                        "result": res})
                    if step.done or not step.calls:
                        break
                yield {"step": "Writing the answer"}
                ans = await self._compose(question, results, None, timeout=max(0.1, min(30.0, left() - 1)))
                errs = faithfulness.check(ans, self.tools.ledger)
                if errs and left() > 15:
                    yield {"step": f"Faithfulness check failed ({len(errs)}); regenerating once"}
                    ans = await self._compose(question, results, errs, timeout=min(30.0, left() - 2))
        except Exception as e:  # noqa: BLE001 — the stream must always end with an answer
            log.exception("insights ask failed")
            failure = _reason(e)
        if ans is None:
            ans = self._compose_offline(question, results) if results else {
                "answer_md": "I couldn't answer that question right now.", "numbers": [], "charts": [], "quotes": [],
                "sql": [], "caveats": [], "suggestions": []}
            ans["caveats"] = [c for c in ans.get("caveats", []) if not c.startswith("Offline mode")]
            if failure:
                ans["caveats"].insert(0, f"Partial answer: the model call failed ({failure})." if results else
                                      f"The model call failed ({failure}).")
                if not results:
                    ans["error"] = failure
        errs = faithfulness.check(ans, self.tools.ledger)
        if errs:
            ans, _ = faithfulness.drop_unfaithful(ans, self.tools.ledger)
        ans["sql"] = list(dict.fromkeys([*self.sql, *ans.get("sql", [])]))
        ans["charts"] = [chart_option(c) if "series" in c and "xAxis" not in c else c for c in ans.get("charts", [])]
        ans = self._only_active(ans)
        ans.setdefault("caveats", [])
        ans["caveats"] = [*ans["caveats"], f"Simulated data{(' · ' + self.window) if self.window else ''}."]
        ans["faithful"] = not faithfulness.check(ans, self.tools.ledger)
        ans["cost_usd"] = round(self.cost_usd, 5)
        yield {"step": "Checked numbers and quotes against the data"}
        yield {"answer": ans}

    def _only_active(self, ans: dict[str, Any]) -> dict[str, Any]:
        """Drop numbers and charts that name a product that is not active any more."""
        if not self.products:
            return ans
        active = {p["product_id"] for p in self.products} | {p.get("name", "") for p in self.products}
        known = self.known_ids - active

        def stale(text: str) -> bool:
            return any(k and k in text for k in known)

        ans["numbers"] = [n for n in ans.get("numbers", []) if not stale(str(n.get("label", "")))]
        ans["charts"] = [c for c in ans.get("charts", []) if not stale(json.dumps(c, default=str))]
        return ans

    def _products_json(self) -> str:
        return _compact([{k: p.get(k) for k in ("product_id", "name", "price_inr", "status")} for p in self.products])

    async def _plan(self, question: str, results: list[dict[str, Any]], timeout: float = CALL_TIMEOUT_S) -> Step:
        prompt = (_p("insights_plan").replace("{dictionary}", _compact(self.tools.describe_data(), 9000))
                  .replace("{products}", self._products_json())
                  .replace("{results}", _compact(results, 12000)).replace("{question}", wrap(question, "question")))
        res = await asyncio.wait_for(self.llm.generate(MODEL_PRO, prompt, Step, purpose="insights_plan",
                                                       reasoning="low", max_tokens=1200,
                                                       priority_class="interactive"), timeout)
        self.cost_usd += res.usage.cost_usd
        return res.data

    async def _compose(self, question: str, results: list[dict[str, Any]], errs: list[str] | None,
                       timeout: float = CALL_TIMEOUT_S) -> dict[str, Any]:
        prompt = (_p("insights_answer").replace("{results}", _compact(results, 16000))
                  .replace("{products}", self._products_json())
                  .replace("{errors}", "\n".join(errs or []) or "(none)").replace("{question}", wrap(question, "question")))
        res = await asyncio.wait_for(self.llm.generate(MODEL_PRO, prompt, AskAnswer, purpose="insights_answer",
                                                       reasoning="low", max_tokens=2000,
                                                       priority_class="interactive"), timeout)
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
        if "considering" in ql:
            return [Call(tool="run_sql", args=ToolArgs(sql=(
                "SELECT product_id, COUNT(DISTINCT agent_id) AS considering_count FROM beliefs_latest "
                "WHERE stage IN ('curious','researching','inquiring','deciding') AND product_id IS NOT NULL "
                "GROUP BY product_id ORDER BY considering_count DESC")))]
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
                rows = [row for row in rows if "product_id" not in row or not names or row["product_id"] in names]
                if not rows:
                    continue
                top = rows[:6]
                for row in top[:4]:
                    nums.append({"label": f"{names.get(row[label_col], row[label_col])} · {val_col}",
                                 "value": float(row[val_col] or 0), "source_ref": ref})
                for row in top[:4]:
                    label = str(names.get(row[label_col], row[label_col]))
                    value = _fmt(row[val_col])
                    if val_col == "considering_count":
                        lines.append(f"**{value} people** are considering **{label}** (interested or deciding, but not yet purchased).")
                    elif "channel" in row and val_col == "agents":
                        lines.append(f"**{value} people** first heard about **{label}** through {str(row["channel"]).replace("_", " " )}.")
                    elif val_col == "purchases":
                        lines.append(f"**{label.capitalize()}** accounted for **{value} purchases**.")
                    else:
                        metric = {"n": "total", "curious_plus": "number of interested people", "aware": "number of aware people"}.get(val_col, val_col.replace("_", " "))
                        lines.append(f"For **{label}**, the recorded {metric} is **{value}**.")
                charts.append({"type": "bar", "title": val_col.replace("_", " "),
                               "x": [str(names.get(row[label_col], row[label_col])) for row in top],
                               "series": [{"name": val_col, "data": [float(row[val_col] or 0) for row in top]}],
                               "source_ref": ref})
            elif r["tool"] == "semantic_search" and isinstance(res, list):
                for row in res[:4]:
                    quotes.append({"agent_id": row["agent_id"], "name": row["name"], "kind": row["kind"],
                                   "t": row["t"], "text": row["text"], "private": row["private"]})
            elif r["tool"] in ("run_sql", "cohort", "survey_results") and isinstance(res, dict) and res.get("error"):
                lines.append("Some requested data could not be retrieved. This answer covers only the available records.")
        if not results:
            lines.append("I can't answer that from the simulated world's data — Insights only knows what the agents in "
                         "Indiranagar saw, thought, said and bought.")
        elif not lines and not quotes:
            lines.append("There isn't enough data in the simulated world yet to answer that.")
        if any(w in q.lower() for w in ("why", "reason")) and not quotes:
            lines.append("These counts do not establish why; no supporting comments were retrieved.")
        md = " ".join(lines[:5])
        sugg = list(STARTER_QUESTIONS)
        return {"answer_md": md, "numbers": nums[:8], "charts": charts[:1], "quotes": quotes[:4], "sql": [],
                "caveats": ["Small simulated samples; differences of a few agents are noise.",
                            "Offline mode: deterministic template answer (no model)."],
                "suggestions": sugg}


def _reason(e: BaseException) -> str:
    """Short, key-free reason for a failed model call."""
    if isinstance(e, asyncio.TimeoutError | TimeoutError):
        return "timed out"
    msg = str(e)
    if "Key limit exceeded" in msg or "HTTP 402" in msg or "HTTP 403" in msg:
        return "model provider credit exhausted"
    if "did not validate" in msg:
        return "model output did not validate"
    return type(e).__name__


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
