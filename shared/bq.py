"""Analytics store: BigQuery in the cloud, DuckDB locally — same `query`/`insert` API."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from shared.settings import Settings, get_settings

EVENTS_DDL = """CREATE TABLE IF NOT EXISTS events (
  event_id VARCHAR PRIMARY KEY, t BIGINT, day BIGINT, t_real TIMESTAMP, kind VARCHAR, agent_id BIGINT,
  other_id BIGINT, product_id VARCHAR, site_id VARCHAR, session_id VARCHAR, rendered BOOLEAN, private BOOLEAN,
  payload JSON)"""
TEXTS_DDL = """CREATE TABLE IF NOT EXISTS texts (
  text_id VARCHAR PRIMARY KEY, event_id VARCHAR, t BIGINT, day BIGINT, kind VARCHAR, agent_id BIGINT,
  product_id VARCHAR, session_id VARCHAR, private BOOLEAN, text VARCHAR, embedding DOUBLE[])"""


class Analytics(Protocol):
    """Query + insert interface shared by both backends."""

    def query(self, sql: str, params: dict | None = None) -> list[dict]: ...
    def insert(self, table: str, rows: list[dict]) -> int: ...


class DuckDBShim:
    """Local DuckDB with BigQuery-like tables `events` and `texts`."""

    def __init__(self, path: str = ":memory:", dataset: str | None = None) -> None:
        import duckdb

        self.dataset = dataset if dataset is not None else get_settings().bq_dataset
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.con = duckdb.connect(path)
        self.con.execute(EVENTS_DDL)
        self.con.execute(TEXTS_DDL)

    @staticmethod
    def translate(sql: str, dataset: str = "") -> str:
        """Strip BigQuery `project.dataset.` qualifiers and backticks so the same SQL runs on DuckDB."""
        sql = sql.replace("`", "")
        if dataset:
            sql = re.sub(rf"\b(?:[\w-]+\.)?{re.escape(dataset)}\.", "", sql)
        sql = re.sub(r"ARRAY\(SELECT JSON_VALUE\((\w+)\) FROM UNNEST\(JSON_QUERY_ARRAY\((\w+), '([^']+)'\)\) \1\)",
                     r"json_extract_string(\2, '\3[*]')", sql)          # BigQuery JSON array → DuckDB list
        sql = re.sub(r"\bJSON_VALUE\(", "json_extract_string(", sql)   # BigQuery JSON_VALUE returns unquoted text
        sql = re.sub(r"\bFLOAT64\b", "DOUBLE", sql)
        return re.sub(r"\bINT64\b", "BIGINT", sql)

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        """Run SQL; `@name` params are bound as `$name`."""
        sql = self.translate(sql, self.dataset)
        sql = re.sub(r"@(\w+)", r"$\1", sql)
        cur = self.con.execute(sql, params or {})
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def insert(self, table: str, rows: list[dict]) -> int:
        """Insert rows (idempotent on primary key); returns rows written."""
        if not rows:
            return 0
        cols = list(rows[0].keys())
        ph = ",".join("?" for _ in cols)
        vals = [[json.dumps(r[c]) if isinstance(r[c], dict) else r[c] for c in cols] for r in rows]
        self.con.executemany(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({ph})", vals)
        return len(rows)


class BigQueryBackend:
    """google-cloud-bigquery client bound to the dataset."""

    def __init__(self, settings: Settings) -> None:
        from google.cloud import bigquery

        self._bq: Any = bigquery
        self.client = bigquery.Client(project=settings.gcp_project_id)
        self.dataset = f"{settings.gcp_project_id}.{settings.bq_dataset}"

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        """Run a parameterised query."""
        qp = [self._bq.ScalarQueryParameter(k, _bq_type(v), v) for k, v in (params or {}).items()]
        job = self.client.query(sql, job_config=self._bq.QueryJobConfig(query_parameters=qp))
        return [dict(r.items()) for r in job.result()]

    def insert(self, table: str, rows: list[dict]) -> int:
        """Streaming insert (Pub/Sub subscriptions are the normal writer)."""
        errors = self.client.insert_rows_json(f"{self.dataset}.{table}", rows)
        if errors:
            raise RuntimeError(f"BigQuery insert errors: {errors[:3]}")
        return len(rows)


def _bq_type(v: Any) -> str:
    return "BOOL" if isinstance(v, bool) else "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) \
        else "STRING"


def get_analytics(settings: Settings | None = None) -> Analytics:
    """DuckDB (BQ_BACKEND=duckdb) or BigQuery."""
    s = settings or get_settings()
    return DuckDBShim(s.duckdb_path, s.bq_dataset) if s.bq_backend == "duckdb" else BigQueryBackend(s)
