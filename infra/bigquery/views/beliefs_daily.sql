-- beliefs_daily: the last belief state per agent × subject × sim day on which it changed (from belief_change events).
CREATE OR REPLACE VIEW `mirava.beliefs_daily` AS
SELECT
  agent_id, day, t,
  JSON_VALUE(payload, '$.subject') AS subject,
  CASE WHEN STARTS_WITH(JSON_VALUE(payload, '$.subject'), 'product:')
       THEN SUBSTR(JSON_VALUE(payload, '$.subject'), 9) END AS product_id,
  JSON_VALUE(payload, '$.after.awareness') AS awareness,
  CAST(JSON_VALUE(payload, '$.after.attitude') AS FLOAT64) AS attitude,
  CAST(JSON_VALUE(payload, '$.after.confidence') AS FLOAT64) AS confidence,
  JSON_VALUE(payload, '$.after.stage') AS stage,
  JSON_VALUE(payload, '$.cause_event_id') AS cause_event_id
FROM `mirava.events`
WHERE kind = 'belief_change'
QUALIFY ROW_NUMBER() OVER (PARTITION BY agent_id, JSON_VALUE(payload, '$.subject'), day ORDER BY t DESC, event_id DESC) = 1
