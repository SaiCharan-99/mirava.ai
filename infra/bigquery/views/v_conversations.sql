-- v_conversations: one row per conversation (rendered) or unrendered interaction, deduplicated by session_id.
CREATE OR REPLACE VIEW `mirava.v_conversations` AS
SELECT
  session_id,
  kind = 'conversation' AS rendered,
  COALESCE(JSON_VALUE(payload, '$.kind'), JSON_VALUE(payload, '$.conv_kind')) AS conv_kind,
  agent_id AS agent_a,
  other_id AS agent_b,
  t,
  day,
  CAST(JSON_VALUE(payload, '$.n_messages') AS INT64) AS n_messages,
  JSON_VALUE(payload, '$.model') AS model,
  ARRAY(SELECT JSON_VALUE(x) FROM UNNEST(JSON_QUERY_ARRAY(payload, '$.topics')) x) AS topics,
  ARRAY(SELECT JSON_VALUE(x) FROM UNNEST(JSON_QUERY_ARRAY(payload, '$.product_mentions')) x) AS product_mentions,
  JSON_VALUE(payload, '$.topic') AS interaction_topic
FROM `mirava.events`
WHERE kind IN ('conversation', 'interaction')
QUALIFY ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY t_real) = 1
