-- v_exposures: every exposure outcome (A-01/A-04), one row per event, deduplicated by event_id.
CREATE OR REPLACE VIEW `mirava.v_exposures` AS
SELECT
  event_id, t, day, CAST(FLOOR(MOD(t, 1440) / 60) AS INT64) AS hour, agent_id, product_id, site_id,
  JSON_VALUE(payload, '$.channel') AS channel,
  JSON_VALUE(payload, '$.creative_id') AS creative_id,
  JSON_VALUE(payload, '$.outcome') AS outcome,
  JSON_VALUE(payload, '$.outcome') IN ('notice', 'partial', 'full') AS noticed,
  JSON_VALUE(payload, '$.outcome') NOT IN ('pass', 'scroll') AS glanced,
  CAST(JSON_VALUE(payload, '$.distance_m') AS FLOAT64) AS distance_m,
  CAST(JSON_VALUE(payload, '$.angle_deg') AS FLOAT64) AS angle_deg,
  CAST(JSON_VALUE(payload, '$.dwell_s') AS FLOAT64) AS dwell_s,
  CAST(JSON_VALUE(payload, '$.facing') AS FLOAT64) AS facing,
  JSON_VALUE(payload, '$.mode') AS mode,
  JSON_VALUE(payload, '$.lit') = 'true' AS lit,
  JSON_VALUE(payload, '$.target') = 'true' AS target,
  CAST(JSON_VALUE(payload, '$.rate_inr_day') AS INT64) AS rate_inr_day
FROM `mirava.events`
WHERE kind = 'exposure'
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
