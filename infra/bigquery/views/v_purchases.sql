-- v_purchases: purchases (S-05/S-06); option is one of our product ids or a baseline id (baseline:<tier>).
CREATE OR REPLACE VIEW `mirava.v_purchases` AS
SELECT
  event_id, t, day, agent_id,
  JSON_VALUE(payload, '$.option') AS option,
  NOT STARTS_WITH(JSON_VALUE(payload, '$.option'), 'baseline:') AS is_ours,
  JSON_VALUE(payload, '$.considered') AS considered_product_id,
  JSON_VALUE(payload, '$.store_id') AS store_id,
  CAST(JSON_VALUE(payload, '$.price_inr') AS INT64) AS price_inr,
  JSON_VALUE(payload, '$.method') AS method,
  CAST(JSON_VALUE(payload, '$.need') AS FLOAT64) AS need,
  JSON_VALUE(payload, '$.life_event') = 'true' AS life_event,
  JSON_VALUE(payload, '$.reason') AS reason
FROM `mirava.events_current`
WHERE kind = 'purchase'
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
