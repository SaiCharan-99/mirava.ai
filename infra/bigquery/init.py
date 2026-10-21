"""Create BigQuery dataset, events/texts tables (INTERFACES §9) and views. Usage: python -m infra.bigquery.init PROJECT [DATASET]."""

import json
import sys
from pathlib import Path

import yaml
from google.cloud import bigquery

RETIRED_VIEW = "a0_retired_products.sql"


def retired_sql(ids: list[str]) -> str:
    """`retired_products` view body listing these product ids (empty view when none)."""
    if not ids:
        return (Path("infra/bigquery/views") / RETIRED_VIEW).read_text(encoding="utf-8")
    rows = "\nUNION ALL ".join("SELECT '" + i.replace("'", "") + "' AS product_id" for i in ids)
    return f"CREATE OR REPLACE VIEW `mirava.retired_products` AS\n{rows}\n"


def retired_ids() -> list[str]:
    """Retired product ids from config/retired_products.yaml."""
    return [str(x) for x in (yaml.safe_load(Path("config/retired_products.yaml").read_text()) or {}).get("retired", [])]


def main(project: str, dataset: str = "mirava") -> None:
    """Idempotently create dataset, tables and views."""
    c = bigquery.Client(project=project)
    ds = bigquery.Dataset(f"{project}.{dataset}")
    ds.location = "asia-south1"
    c.create_dataset(ds, exists_ok=True)
    here = Path("infra/bigquery")
    for name, cluster in (("events", ["kind", "product_id", "agent_id"]), ("texts", ["kind", "product_id"])):
        schema = [bigquery.SchemaField(f["name"], f["type"], mode=f["mode"]) for f in json.loads((here / f"{name}.json").read_text())]
        t = bigquery.Table(f"{project}.{dataset}.{name}", schema=schema)
        t.range_partitioning = bigquery.RangePartitioning(field="day", range_=bigquery.PartitionRange(1, 4001, 1))
        t.clustering_fields = cluster
        c.create_table(t, exists_ok=True)
    for v in sorted((here / "views").glob("*.sql")):
        sql = retired_sql(retired_ids()) if v.name == RETIRED_VIEW else v.read_text(encoding="utf-8")
        c.query(sql.replace("`mirava.", f"`{project}.{dataset}.")).result()
    print([t.table_id for t in c.list_tables(f"{project}.{dataset}")])


if __name__ == "__main__":
    main(*sys.argv[1:])
