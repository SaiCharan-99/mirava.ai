"""Create BigQuery dataset, events/texts tables (INTERFACES §9) and views. Usage: python -m infra.bigquery.init PROJECT [DATASET]."""

import json
import sys
from pathlib import Path

from google.cloud import bigquery


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
        c.query(v.read_text().replace("`mirava.", f"`{project}.{dataset}.")).result()
    print([t.table_id for t in c.list_tables(f"{project}.{dataset}")])


if __name__ == "__main__":
    main(*sys.argv[1:])
