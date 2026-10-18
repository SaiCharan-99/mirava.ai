-- v_thoughts: private thoughts on noticed ads (A-03) — always labelled private when quoted.
CREATE OR REPLACE VIEW `mirava.v_thoughts` AS
SELECT
  event_id, t, day, agent_id, product_id, site_id, rendered,
  JSON_VALUE(payload, '$.channel') AS channel,
  JSON_VALUE(payload, '$.text') AS text,
  CAST(JSON_VALUE(payload, '$.attitude_delta') AS FLOAT64) AS attitude_delta,
  JSON_VALUE(payload, '$.intent_change') AS intent_change,
  JSON_VALUE(payload, '$.trigger_event_id') AS trigger_event_id,
  TRUE AS private
FROM `mirava.events`
WHERE kind = 'thought'
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
