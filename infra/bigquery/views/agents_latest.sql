-- agents_latest: one row per agent from the newest agent_snapshot event (deduplicated by event_id).
CREATE OR REPLACE VIEW `mirava.agents_latest` AS
SELECT
  agent_id,
  t,
  day,
  JSON_VALUE(payload, '$.name') AS name,
  CAST(JSON_VALUE(payload, '$.age') AS INT64) AS age,
  JSON_VALUE(payload, '$.gender') AS gender,
  JSON_VALUE(payload, '$.occupation') AS occupation,
  JSON_VALUE(payload, '$.income_band') AS income_band,
  JSON_VALUE(payload, '$.special_role') AS special_role,
  JSON_VALUE(payload, '$.lifestyle') AS lifestyle,
  JSON_VALUE(payload, '$.phone.brand') AS phone_brand,
  JSON_VALUE(payload, '$.phone.tier') AS phone_tier,
  JSON_VALUE(payload, '$.phone.condition') AS phone_condition,
  CAST(JSON_VALUE(payload, '$.phone.age_years') AS FLOAT64) AS phone_age_years
FROM `mirava.events`
WHERE kind = 'agent_snapshot'
QUALIFY ROW_NUMBER() OVER (PARTITION BY agent_id ORDER BY t DESC, event_id DESC) = 1
