-- v_paths: first touch per channel for each agent × product in time order, ending in store / purchase when they happened.
CREATE OR REPLACE VIEW `mirava.v_paths` AS
WITH raw AS (
  SELECT agent_id, product_id, t, JSON_VALUE(payload, '$.channel') AS channel, event_id
  FROM `mirava.events_current`
  WHERE kind = 'exposure' AND JSON_VALUE(payload, '$.outcome') IN ('notice', 'partial', 'full')
    AND product_id IS NOT NULL AND NOT STARTS_WITH(product_id, 'baseline:')
  UNION ALL
  SELECT agent_id, JSON_VALUE(payload, '$.product_mentions[0]'), t, 'friend_chat', event_id
  FROM `mirava.events_current`
  WHERE kind = 'conversation' AND JSON_VALUE(payload, '$.product_mentions[0]') IS NOT NULL
    AND JSON_VALUE(payload, '$.kind') != 'store'
  UNION ALL
  SELECT agent_id, product_id, t, 'store', event_id FROM `mirava.events_current` WHERE kind = 'inquiry'
  UNION ALL
  SELECT agent_id, JSON_VALUE(payload, '$.considered'), t, 'purchase', event_id FROM `mirava.events_current`
  WHERE kind = 'purchase'
), touch AS (
  SELECT agent_id, product_id, channel AS step, MIN(t) AS t FROM raw WHERE product_id IS NOT NULL GROUP BY 1, 2, 3
)
SELECT agent_id, product_id,
       STRING_AGG(step, ' > ' ORDER BY t) AS path,
       COUNT(*) AS n_steps,
       MIN(t) AS first_t,
       MAX(CASE WHEN step = 'store' THEN t END) AS inquiry_t,
       MAX(CASE WHEN step = 'store' THEN t END) - MIN(t) AS minutes_to_inquiry
FROM touch
WHERE step != 'friend_chat' OR product_id IN (SELECT product_id FROM `mirava.current_products`)
GROUP BY agent_id, product_id
