-- events_current: events minus anything about a retired product (by product_id, first product mention or purchase option).
CREATE OR REPLACE VIEW `mirava.events_current` AS
SELECT *
FROM `mirava.events`
WHERE COALESCE(product_id, '') NOT IN (SELECT product_id FROM `mirava.retired_products`)
  AND COALESCE(JSON_VALUE(payload, '$.product_mentions[0]'), '') NOT IN (SELECT product_id FROM `mirava.retired_products`)
  AND COALESCE(JSON_VALUE(payload, '$.option'), '') NOT IN (SELECT product_id FROM `mirava.retired_products`)
  AND COALESCE(JSON_VALUE(payload, '$.considered'), '') NOT IN (SELECT product_id FROM `mirava.retired_products`)
