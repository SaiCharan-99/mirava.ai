"""Insights SQL safety (architecture §18): one read-only SELECT over curated views of our dataset only."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

MAX_ROWS = 5000
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Merge, exp.Command,
             exp.TruncateTable, exp.Grant)


class SQLRejected(ValueError):
    """The query is not allowed."""


def views() -> set[str]:
    """Curated view names readable by the analyst account (from the data dictionary)."""
    from insights.dictionary import dictionary

    return set(dictionary()["views"])


def check(sql: str, dataset: str = "mirava", project: str | None = None, allowed: set[str] | None = None) -> str:
    """Validate and normalise; returns SQL with a LIMIT ≤ 5,000. Raises SQLRejected."""
    allowed = allowed if allowed is not None else views()
    try:
        stmts = [s for s in sqlglot.parse(sql, read="bigquery") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SQLRejected(f"could not parse SQL: {str(e)[:200]}") from e
    if len(stmts) != 1:
        raise SQLRejected("exactly one statement is allowed")
    tree = stmts[0]
    if isinstance(tree, FORBIDDEN) or any(isinstance(n, FORBIDDEN) for n in tree.walk()):
        raise SQLRejected("only read-only SELECT queries are allowed")
    if not isinstance(tree, exp.Query):
        raise SQLRejected("only SELECT queries are allowed")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        db = (t.db or "").lower()
        cat = (t.catalog or "").lower()
        if not db and not cat and name in ctes:
            continue
        if db and db != dataset.lower():
            raise SQLRejected(f"cross-dataset access is not allowed: {db}.{name}")
        if cat and project and cat != project.lower():
            raise SQLRejected(f"other projects are not allowed: {cat}")
        if name not in allowed:
            raise SQLRejected(f"`{name}` is not a curated view; use describe_data() for the allowed views")
    for fn in tree.find_all(exp.Anonymous):
        if fn.name.upper() in ("EXTERNAL_QUERY", "ML.PREDICT"):
            raise SQLRejected("external functions are not allowed")
    lim = tree.args.get("limit")
    n = None
    if lim is not None:
        try:
            n = int(lim.expression.name) if lim.expression is not None else None
        except (ValueError, AttributeError):
            n = None
    if n is None or n > MAX_ROWS:
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="bigquery")


def qualify(sql: str, project: str, dataset: str) -> str:
    """Prefix bare view names with `project.dataset` for BigQuery."""
    tree = sqlglot.parse_one(sql, read="bigquery")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not t.db and t.name.lower() not in ctes:
            t.set("db", exp.to_identifier(dataset))
            t.set("catalog", exp.to_identifier(project))
    return tree.sql(dialect="bigquery")
