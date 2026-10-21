-- beliefs_latest: current belief per agent × subject; stage = the latest consideration transition when there is one.
CREATE OR REPLACE VIEW `mirava.beliefs_latest` AS
WITH b AS (
  SELECT agent_id, t,
         JSON_VALUE(payload, '$.subject') AS subject,
         JSON_VALUE(payload, '$.after.awareness') AS awareness,
         CAST(JSON_VALUE(payload, '$.after.attitude') AS FLOAT64) AS attitude,
         CAST(JSON_VALUE(payload, '$.after.confidence') AS FLOAT64) AS confidence,
         JSON_VALUE(payload, '$.after.stage') AS stage
  FROM `mirava.events_current`
  WHERE kind = 'belief_change'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY agent_id, JSON_VALUE(payload, '$.subject') ORDER BY t DESC, event_id DESC) = 1
), c AS (
  SELECT agent_id, JSON_VALUE(payload, '$.subject') AS subject, JSON_VALUE(payload, '$.to') AS stage, t
  FROM `mirava.events_current`
  WHERE kind = 'consideration'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY agent_id, JSON_VALUE(payload, '$.subject') ORDER BY t DESC, event_id DESC) = 1
)
SELECT
  COALESCE(b.agent_id, c.agent_id) AS agent_id,
  COALESCE(b.subject, c.subject) AS subject,
  CASE WHEN STARTS_WITH(COALESCE(b.subject, c.subject), 'product:')
       THEN SUBSTR(COALESCE(b.subject, c.subject), 9) END AS product_id,
  COALESCE(b.awareness, 'aware') AS awareness,
  COALESCE(b.attitude, 0.0) AS attitude,
  COALESCE(b.confidence, 0.0) AS confidence,
  COALESCE(c.stage, b.stage, 'aware') AS stage,
  GREATEST(COALESCE(b.t, 0), COALESCE(c.t, 0)) AS updated_t
FROM b FULL OUTER JOIN c ON b.agent_id = c.agent_id AND b.subject = c.subject
