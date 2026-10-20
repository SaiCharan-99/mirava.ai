-- v_messages: every spoken message exactly as logged (T-04), one row per message, deduplicated by event_id.
CREATE OR REPLACE VIEW `mirava.v_messages` AS
SELECT
  session_id,
  CAST(JSON_VALUE(payload, '$.seq') AS INT64) AS seq,
  SAFE_CAST(JSON_VALUE(payload, '$.speaker') AS INT64) AS speaker,          -- 'moderator' (focus groups) → NULL
  SAFE_CAST(JSON_VALUE(payload, '$.listener') AS INT64) AS listener,
  JSON_VALUE(payload, '$.text') AS text,
  JSON_VALUE(payload, '$.conv_kind') AS conv_kind,
  t,
  day,
  event_id
FROM `mirava.events`
WHERE kind = 'message'
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
