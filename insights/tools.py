"""Insights tools (INTERFACES §3): describe_data, run_sql, semantic_search, cohort, likely_buyers, poll, interview, chart.

Every tool result is registered in a `Ledger` under a `ref`; the faithfulness check (I-09) matches answer numbers and
quotes against these results.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import sqlglot
from sqlglot import exp

from insights.dictionary import columns, dictionary
from insights.sqlguard import MAX_ROWS, SQLRejected, check, qualify
from shared.settings import Settings, get_settings

MAX_BYTES = 2 * 1024**3       # maximum_bytes_billed per Insights query (2 GiB)


class Runner(Protocol):
    """Executes already-validated read-only SQL over the curated views."""

    def run(self, sql: str, params: dict | None = None, trusted: bool = False) -> tuple[list[dict], int]: ...
    def texts(self, where: str, params: dict) -> list[dict]: ...


# ---------------------------------------------------------------- runners

class DuckRunner:
    """Local DuckDB twin (views created from infra/bigquery/views); bytes reported as 0."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def run(self, sql: str, params: dict | None = None, trusted: bool = False) -> tuple[list[dict], int]:
        """Run with the BigQuery → DuckDB translation."""
        if not trusted and "@" not in sql:
            sql = sqlglot.transpile(sql, read="bigquery", write="duckdb")[0]
        return self.db.query(sql, params), 0

    def texts(self, where: str, params: dict) -> list[dict]:
        """`texts` rows (with embeddings) matching a trusted filter."""
        return self.db.query(f"SELECT text_id, event_id, t, day, kind, agent_id, product_id, session_id, private, text, "
                             f"embedding FROM texts WHERE {where}", params)


class BigQueryRunner:
    """BigQuery as the read-only analyst account (impersonated); dry-run first, byte cap, row cap."""

    def __init__(self, s: Settings) -> None:
        import google.auth
        from google.auth import impersonated_credentials
        from google.cloud import bigquery

        self.bq = bigquery
        self.s = s
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        sa = s.analyst_sa or f"mirava-analyst-ro@{s.gcp_project_id}.iam.gserviceaccount.com"
        try:
            creds = impersonated_credentials.Credentials(source_credentials=creds, target_principal=sa,
                                                         target_scopes=["https://www.googleapis.com/auth/cloud-platform"])
        except Exception:  # noqa: BLE001 — fall back to the service's own (still read-only by the SQL guard)
            pass
        self.client = bigquery.Client(project=s.gcp_project_id, credentials=creds)

    def _params(self, params: dict | None) -> list[Any]:
        out: list[Any] = []
        for k, v in (params or {}).items():
            if isinstance(v, list):
                out.append(self.bq.ArrayQueryParameter(k, "INT64" if v and isinstance(v[0], int) else "STRING", v))
            else:
                t = "BOOL" if isinstance(v, bool) else "INT64" if isinstance(v, int) else \
                    "FLOAT64" if isinstance(v, float) else "STRING"
                out.append(self.bq.ScalarQueryParameter(k, t, v))
        return out

    def run(self, sql: str, params: dict | None = None, trusted: bool = False) -> tuple[list[dict], int]:
        """Dry run (bytes) then the real query with maximum_bytes_billed."""
        sql = qualify(sql, self.s.gcp_project_id, self.s.bq_dataset) if "`" not in sql else sql
        qp = self._params(params)
        dry = self.client.query(sql, job_config=self.bq.QueryJobConfig(dry_run=True, use_query_cache=False,
                                                                        query_parameters=qp), location=self.s.gcp_region)
        nbytes = int(dry.total_bytes_processed or 0)
        if nbytes > MAX_BYTES:
            raise SQLRejected(f"query would scan {nbytes / 1e9:.1f} GB (cap {MAX_BYTES / 1e9:.1f} GB); filter by day")
        job = self.client.query(sql, job_config=self.bq.QueryJobConfig(maximum_bytes_billed=MAX_BYTES,
                                                                        query_parameters=qp), location=self.s.gcp_region)
        return [dict(r.items()) for r in job.result(max_results=MAX_ROWS)], nbytes

    def dry_run_error(self, sql: str) -> str | None:
        """None when BigQuery accepts the SQL in a dry run, else a short error message."""
        try:
            q = qualify(sql, self.s.gcp_project_id, self.s.bq_dataset) if "`" not in sql else sql
            self.client.query(q, job_config=self.bq.QueryJobConfig(dry_run=True, use_query_cache=False),
                              location=self.s.gcp_region)
            return None
        except Exception as e:  # noqa: BLE001 — returned as data for a retry
            return str(getattr(e, "message", e))[:300]

    def texts(self, where: str, params: dict) -> list[dict]:
        """Not used on BigQuery (VECTOR_SEARCH runs server-side)."""
        raise NotImplementedError


class EngineRunner:
    """Local dev: the engine holds the DuckDB file lock, so the api asks the engine (`POST /analytics/query`)."""

    def __init__(self, engine_url: str) -> None:
        self.url = engine_url.rstrip("/")

    def run(self, sql: str, params: dict | None = None, trusted: bool = False) -> tuple[list[dict], int]:
        """Query on the engine's DuckDB (guarded unless `trusted`, i.e. a fixed dashboard query)."""
        import httpx

        r = httpx.post(f"{self.url}/analytics/query", json={"sql": sql, "params": params or {}, "trusted": trusted},
                       timeout=60)
        if r.status_code != 200:
            raise SQLRejected(f"engine analytics error {r.status_code}: {r.text[:200]}")
        return r.json()["rows"], 0

    def texts(self, where: str, params: dict) -> list[dict]:
        """Texts rows from the engine's DuckDB."""
        import httpx

        r = httpx.post(f"{self.url}/analytics/query", json={"texts": where, "params": params}, timeout=60)
        r.raise_for_status()
        return r.json()["rows"]


def default_runner(settings: Settings | None = None) -> Runner:
    """BigQuery in the cloud; locally the engine's DuckDB (read-only file fallback when the engine is down)."""
    s = settings or get_settings()
    if s.bq_backend == "bigquery":
        return BigQueryRunner(s)
    import httpx

    try:
        httpx.get(f"{s.engine_url}/health", timeout=2)
        return EngineRunner(s.engine_url)
    except httpx.HTTPError:
        import duckdb

        from shared.bq import DuckDBShim

        db = DuckDBShim.__new__(DuckDBShim)
        db.dataset = s.bq_dataset
        db.con = duckdb.connect(s.duckdb_path, read_only=True)
        return DuckRunner(db)


# ---------------------------------------------------------------- ledger

def _ref(prefix: str, *parts: Any) -> str:
    return f"{prefix}:" + hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:10]


def _numbers(v: Any, out: list[float]) -> None:
    if isinstance(v, bool):
        return
    if isinstance(v, int | float) and math.isfinite(float(v)):
        out.append(float(v))
    elif isinstance(v, dict):
        for x in v.values():
            _numbers(x, out)
    elif isinstance(v, list | tuple):
        for x in v:
            _numbers(x, out)


@dataclass
class Ledger:
    """Tool results of one answer, by ref."""

    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    texts: dict[str, dict[str, Any]] = field(default_factory=dict)   # text_id → row (quotes must come from here)

    def add(self, ref: str, tool: str, args: dict[str, Any], result: Any) -> str:
        """Register a result."""
        self.results[ref] = {"tool": tool, "args": args, "result": result}
        return ref

    def numbers(self, ref: str) -> list[float]:
        """All numbers in one result."""
        out: list[float] = []
        r = self.results.get(ref)
        if r is not None:
            _numbers(r["result"], out)
        return out

    def has_number(self, ref: str, value: float) -> bool:
        """`value` appears in result `ref` (rounding and % conversions allowed)."""
        for n in self.numbers(ref):
            for cand in (n, n * 100):
                if abs(cand - value) <= max(0.051, abs(cand) * 0.005) or round(cand) == round(value) and \
                        abs(cand - value) < 1:
                    return True
        return False


# ---------------------------------------------------------------- tools

class Tools:
    """The tool set bound to one runner, ledger, engine command sender and LLM (for interviews)."""

    def __init__(self, runner: Runner, ledger: Ledger | None = None, *, settings: Settings | None = None,
                 llm: Any = None, store: Any = None, engine: Any = None, embed: Any = None) -> None:
        self.r = runner
        self.ledger = ledger or Ledger()
        self.s = settings or get_settings()
        self.llm, self.store, self.engine, self.embed = llm, store, engine, embed
        self.cohorts: dict[str, list[int]] = {}

    # -- describe_data
    def describe_data(self) -> dict[str, Any]:
        """The data dictionary (views, columns, notes, examples)."""
        return dictionary()

    # -- run_sql
    def run_sql(self, sql: str) -> dict[str, Any]:
        """Read-only SQL over curated views (guarded); ≤ 5,000 rows."""
        safe = check(sql, self.s.bq_dataset, self.s.gcp_project_id)
        if isinstance(self.r, BigQueryRunner):
            safe = self._bigquery_sql(sql, safe)
        rows, nbytes = self.r.run(safe)
        rows = [{k: _plain(v) for k, v in r.items()} for r in rows[:MAX_ROWS]]
        cols = list(rows[0].keys()) if rows else []
        ref = _ref("sql", safe)
        out = {"columns": cols, "rows": rows, "bytes": nbytes, "ref": ref, "sql": safe}
        self.ledger.add(ref, "run_sql", {"sql": safe}, rows)
        return out

    def _bigquery_sql(self, raw: str, safe: str) -> str:
        """Guarded SQL that BigQuery accepts: as written, else transpiled from DuckDB style; validated by dry run."""
        err = self.r.dry_run_error(safe)  # type: ignore[attr-defined]
        if err is None:
            return safe
        try:
            alt = check(sqlglot.transpile(raw, read="duckdb", write="bigquery")[0], self.s.bq_dataset,
                        self.s.gcp_project_id)
        except Exception:  # noqa: BLE001 — not DuckDB SQL either
            alt = None
        if alt is not None and alt != safe and self.r.dry_run_error(alt) is None:  # type: ignore[attr-defined]
            return alt
        raise SQLRejected(f"BigQuery rejected the SQL: {err}")

    # -- cohort
    def cohort(self, filter_expr: str) -> dict[str, Any]:
        """Agent ids matching a boolean expression over agents_latest columns (e.g. `phone_age_years > 5`)."""
        cols = set(columns("agents_latest"))
        try:
            node = sqlglot.parse_one(filter_expr, read="bigquery", into=exp.Condition)
        except sqlglot.errors.ParseError as e:
            raise SQLRejected(f"bad cohort filter: {e}") from e
        for c in node.find_all(exp.Column):
            if c.name not in cols:
                raise SQLRejected(f"unknown agents_latest column `{c.name}`")
        if any(isinstance(n, exp.Subquery | exp.Select) for n in node.walk()):
            raise SQLRejected("subqueries are not allowed in cohort filters")
        where = node.sql(dialect="bigquery")
        rows, _ = self.r.run(check(f"SELECT agent_id FROM agents_latest WHERE {where}", self.s.bq_dataset))
        ids = sorted(int(r["agent_id"]) for r in rows)
        ref = _ref("cohort", where)
        self.cohorts[ref] = ids
        out = {"agent_ids": ids, "size": len(ids), "ref": ref, "filter": where}
        self.ledger.add(ref, "cohort", {"filter_expr": where}, {"size": len(ids)})
        return out

    # -- semantic_search
    def semantic_search(self, text: str, filters: dict[str, Any] | None = None, k: int = 20) -> list[dict[str, Any]]:
        """Nearest texts by embedding (VECTOR_SEARCH on BigQuery; cosine on DuckDB), with filters."""
        f = dict(filters or {})
        k = max(1, min(50, int(k)))
        conds, params = ["ARRAY_LENGTH(embedding) > 0" if isinstance(self.r, BigQueryRunner) else "len(embedding) > 0"], {}
        if f.get("product_id"):
            conds.append("product_id = @product_id")
            params["product_id"] = str(f["product_id"])
        kinds = f.get("kinds") or ([f["kind"]] if f.get("kind") else None)
        if kinds:
            conds.append("kind IN (" + ",".join(f"'{re.sub(r'[^a-z_]', '', str(x))}'" for x in kinds) + ")")
        if f.get("private") is not None:
            conds.append("private = " + ("TRUE" if f["private"] else "FALSE"))
        for key, op in (("from_day", ">="), ("to_day", "<=")):
            if f.get(key) is not None:
                conds.append(f"day {op} {int(f[key])}")
        ids = self.cohorts.get(str(f.get("cohort_ref", "")))
        if ids is None and f.get("agent_ids"):
            ids = [int(x) for x in f["agent_ids"]]
        if ids is not None:
            conds.append("agent_id IN (" + ",".join(str(int(i)) for i in ids[:5000] or [-1]) + ")")
        try:
            qv = self.embed([text])[0] if self.embed is not None else None
            rows = self._vector(qv, " AND ".join(conds), params, k) if qv is not None else []
            if not rows:                                   # no vectors (or none match): fall back to the words
                rows = self._keyword(text, conds, params, k)
        except Exception:
            logging.getLogger(__name__).warning("Vector search unavailable; using keyword search", exc_info=True)
            rows = self._keyword(text, conds, params, k)
        logging.getLogger(__name__).info("semantic_search %r filters=%s where=%s -> %d rows", text[:80],
                                         {k: v for k, v in f.items() if k != "agent_ids"}, " AND ".join(conds)[:300],
                                         len(rows))
        names = self._names([int(r["agent_id"]) for r in rows if r.get("agent_id") is not None])
        out = []
        for r in rows:
            row = {"text_id": r["text_id"], "agent_id": r.get("agent_id"), "name": names.get(int(r["agent_id"])) if r.get("agent_id") is not None else None,
                   "kind": r["kind"], "t": r["t"], "text": r["text"], "private": bool(r["private"]),
                   "product_id": r.get("product_id"), "score": round(float(r.get("score", 0.0)), 4)}
            self.ledger.texts[row["text_id"]] = row
            out.append(row)
        self.ledger.add(_ref("search", text, f), "semantic_search", {"text": text, "filters": f}, {"n": len(out)})
        return out

    def _vector(self, qv: list[float], where: str, params: dict, k: int) -> list[dict]:
        if isinstance(self.r, BigQueryRunner):
            ds = f"`{self.s.gcp_project_id}.{self.s.bq_dataset}.texts`"
            sql = (f"SELECT base.text_id, base.agent_id, base.kind, base.t, base.text, base.private, base.product_id, "
                   f"1 - distance AS score FROM VECTOR_SEARCH((SELECT * FROM {ds} WHERE {where}), 'embedding', "
                   f"(SELECT @qv AS embedding), top_k => {k}, distance_type => 'COSINE')")
            q = self.r.bq.ArrayQueryParameter("qv", "FLOAT64", qv)
            pq = [*self.r._params(params), q]
            job = self.r.client.query(sql, job_config=self.r.bq.QueryJobConfig(query_parameters=pq,
                                                                                maximum_bytes_billed=MAX_BYTES),
                                      location=self.s.gcp_region)
            return [dict(r.items()) for r in job.result()]
        rows = self.r.texts(where, params)
        nq = math.sqrt(sum(x * x for x in qv)) or 1.0
        for r in rows:
            e = list(r["embedding"] or [])
            ne = math.sqrt(sum(x * x for x in e)) or 1.0
            r["score"] = sum(a * b for a, b in zip(qv, e, strict=False)) / (nq * ne)
        rows.sort(key=lambda r: (-r["score"], r["text_id"]))
        seen, out = set(), []
        for r in rows:
            if r["text"] in seen:
                continue
            seen.add(r["text"])
            out.append(r)
            if len(out) >= k:
                break
        return out

    def _keyword(self, text: str, conds: list[str], params: dict, k: int) -> list[dict]:
        """Word-stem match over thoughts/messages; relaxes the product filter when nothing matches."""
        stems = keyword_stems(text)
        if not stems:
            return []
        rows = self._keyword_rows(stems, conds[1:], params)
        if not rows and "product_id = @product_id" in conds:
            rest = [c for c in conds[1:] if c != "product_id = @product_id"]
            rows = self._keyword_rows(stems, rest, {x: v for x, v in params.items() if x != "product_id"})
        for r in rows:
            words = re.findall(r"[a-z0-9]+", str(r["text"]).lower())
            r["score"] = sum(any(w.startswith(st) for w in words) for st in stems) / len(stems)
        rows.sort(key=lambda r: (-r["score"], -int(r.get("t") or 0), r["text_id"]))
        seen, out = set(), []
        for r in rows:
            if r["score"] <= 0 or r["text"] in seen:
                continue
            seen.add(r["text"])
            out.append(r)
            if len(out) >= k:
                break
        return out

    def _keyword_rows(self, stems: list[str], conds: list[str], params: dict) -> list[dict]:
        where = " AND ".join(conds) or "TRUE"
        if isinstance(self.r, BigQueryRunner):
            # Keep all cohort/product/privacy filters and search texts even when vectors are missing.
            params = {**params, "terms": r"\b(" + "|".join(stems) + ")"}
            rows, _ = self.r.run("SELECT text_id, agent_id, kind, t, text, private, product_id FROM texts WHERE "
                                 + where + " AND REGEXP_CONTAINS(LOWER(text), @terms) ORDER BY t DESC LIMIT 500",
                                 params, trusted=True)
            return rows
        return self.r.texts(where, params)

    def _names(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows, _ = self.r.run("SELECT agent_id, name FROM agents_latest WHERE agent_id IN (" +
                             ",".join(str(i) for i in sorted(set(ids))) + ")")
        return {int(r["agent_id"]): r["name"] for r in rows}

    # -- likely_buyers
    def likely_buyers(self, product_id: str, group_by: list[str] | None = None) -> dict[str, Any]:
        """Segment table of L = need × interest × affordability × stage_weight (no per-person prediction)."""
        from insights.likely_buyers import segments

        doc = self.store.get("products", product_id) if self.store is not None else None
        rows = segments(self.r, product_id, group_by or ["age_band", "income_band"],
                        int(doc["price_inr"]) if doc else None)
        ref = _ref("lb", product_id, group_by)
        self.ledger.add(ref, "likely_buyers", {"product_id": product_id, "group_by": group_by}, rows)
        return {"rows": rows, "ref": ref}

    # -- poll (engine command; estimate first)
    def poll(self, question: str, options: list[str], cohort_ref: str | None = None,
             confirm: bool = False) -> dict[str, Any]:
        """Estimate (and with confirm=True start) a poll of all agents or a cohort."""
        from insights.polls import estimate_usd, poll_id

        ids = self.cohorts.get(cohort_ref or "") if cohort_ref else None
        n = len(ids) if ids is not None else 1000
        pid = poll_id(question, options, ids)
        out = {"poll_id": pid, "estimate_usd": estimate_usd(n), "n": n, "started": False}
        if confirm and self.engine is not None:
            res = self.engine({"type": "poll", "poll_id": pid, "question": question, "options": options,
                               "agent_ids": ids})
            out["started"] = bool(res and res.get("ok"))
        self.ledger.add(_ref("poll", pid), "poll", {"question": question, "options": options}, out)
        return out

    # -- interview
    async def interview(self, agent_id: int, question: str) -> dict[str, Any]:
        """Interviewer agent answering as agent X, grounded only in X's memory."""
        from agents.interviewer import interview

        out = await interview(int(agent_id), question, store=self.store, llm=self.llm)
        self.ledger.add(_ref("iv", agent_id, question), "interview", {"agent_id": agent_id}, out)
        return out

    # -- survey_results (Survey Room, addendum B10)
    def survey_results(self, survey_ref: str = "latest", question_id: str | None = None) -> dict[str, Any]:
        """Distributions, prestance → final shift, waves and quotes of a survey (by id, product id or 'latest')."""
        from insights.surveys import survey_results

        out = survey_results(self.r, survey_ref, question_id)
        for q in out.get("quotes", []):
            self.ledger.texts[q["text_id"]] = q
        out["ref"] = _ref("survey", survey_ref, question_id, out.get("survey_id"))
        self.ledger.add(out["ref"], "survey_results", {"survey_ref": survey_ref}, {k: v for k, v in out.items()
                                                                                   if k != "quotes"})
        return out

    # -- chart
    def chart(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Normalise a small chart spec {type, title, x, series:[{name, data}], source_ref} into an ECharts option."""
        return chart_option(spec)


STOPWORDS = frozenset("""about after again also and are any because been before being but can could did does doing
each for from had has have how into its just like many more most much not now our out over own people person said same
should some such than that the their them then there these they this those through very was were what when where which
while who whom why will with would you your our products product think thought thoughts say says""".split())


def keyword_stems(text: str) -> list[str]:
    """Content-word stems (first 5 letters) for keyword search; stopwords and short words dropped."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS]
    return sorted({w[:5] for w in words})


def chart_option(spec: dict[str, Any]) -> dict[str, Any]:
    """ECharts option from {type: bar|line|pie|hbar, title, x, series, source_ref}."""
    kind = str(spec.get("type", "bar"))
    x = [str(v) for v in spec.get("x", [])]
    series = [{"name": str(s.get("name", "")), "data": [float(v) if v is not None else None for v in s.get("data", [])]}
              for s in spec.get("series", [])][:6]
    if kind == "pie":
        data = [{"name": n, "value": v} for n, v in zip(x, (series[0]["data"] if series else []), strict=False)]
        opt: dict[str, Any] = {"series": [{"type": "pie", "radius": ["40%", "70%"], "data": data}]}
    else:
        horiz = kind == "hbar"
        cat = {"type": "category", "data": x}
        val = {"type": "value"}
        opt = {"xAxis": val if horiz else cat, "yAxis": cat if horiz else val,
               "series": [{"type": "line" if kind == "line" else "bar", **s} for s in series]}
    opt["title"] = {"text": str(spec.get("title", ""))}
    opt["tooltip"] = {"trigger": "item" if kind == "pie" else "axis"}
    opt["_unit"] = spec.get("unit", "count")
    opt["_source_ref"] = spec.get("source_ref")
    return opt


def _plain(v: Any) -> Any:
    """JSON-safe scalar."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, int | float | str | bool) or v is None:
        return v
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)
