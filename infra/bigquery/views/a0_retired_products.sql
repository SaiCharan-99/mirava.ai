-- retired_products: product ids from earlier demo runs (fix-E). Every curated view reads events_current, which drops them.
-- The file ships empty (local DuckDB, tests); `python -m infra.bigquery.init` fills it from config/retired_products.yaml.
CREATE OR REPLACE VIEW `mirava.retired_products` AS
SELECT '' AS product_id FROM (SELECT 1 AS x) WHERE FALSE
