-- v_first_heard: first channel through which each agent became aware of each product (I-03).
CREATE OR REPLACE VIEW `mirava.v_first_heard` AS
WITH touch AS (
  SELECT agent_id, product_id, t, JSON_VALUE(payload, '$.channel') AS channel, event_id
  FROM `mirava.events_current`
  WHERE kind = 'exposure' AND JSON_VALUE(payload, '$.outcome') IN ('notice', 'partial', 'full')
    AND product_id IS NOT NULL AND NOT STARTS_WITH(product_id, 'baseline:')
  UNION ALL
  SELECT agent_id, JSON_VALUE(payload, '$.product_mentions[0]') AS product_id, t, 'friend_chat' AS channel, event_id
  FROM `mirava.events_current`
  WHERE kind = 'conversation' AND JSON_VALUE(payload, '$.product_mentions[0]') IS NOT NULL
    AND JSON_VALUE(payload, '$.kind') != 'store'
  UNION ALL
  SELECT other_id AS agent_id, JSON_VALUE(payload, '$.product_mentions[0]') AS product_id, t, 'friend_chat', event_id
  FROM `mirava.events_current`
  WHERE kind = 'conversation' AND JSON_VALUE(payload, '$.product_mentions[0]') IS NOT NULL
    AND JSON_VALUE(payload, '$.kind') != 'store' AND other_id IS NOT NULL
)
SELECT agent_id, product_id, t, CAST(FLOOR(t / 1440) + 1 AS INT64) AS day, channel, event_id
FROM touch
WHERE channel != 'friend_chat' OR product_id IN (SELECT product_id FROM `mirava.current_products`)
QUALIFY ROW_NUMBER() OVER (PARTITION BY agent_id, product_id ORDER BY t, event_id) = 1
