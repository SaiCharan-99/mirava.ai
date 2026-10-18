-- v_funnel_daily: per product × sim day — aware, positive, considering+ (states at the end of the day) and that
-- day's inquiries and purchases (I-02). States come from first notices, belief changes and consideration transitions.
CREATE OR REPLACE VIEW `mirava.v_funnel_daily` AS
WITH days AS (
  SELECT DISTINCT day FROM `mirava.events`
), tr AS (
  SELECT agent_id, product_id, day, t, JSON_VALUE(payload, '$.to') AS stage
  FROM `mirava.events` WHERE kind = 'consideration' AND product_id IS NOT NULL
), aw AS (
  SELECT agent_id, product_id, MIN(day) AS day FROM (
    SELECT agent_id, product_id, day FROM `mirava.events`
    WHERE kind = 'exposure' AND JSON_VALUE(payload, '$.outcome') IN ('notice', 'partial', 'full')
      AND product_id IS NOT NULL AND NOT STARTS_WITH(product_id, 'baseline:')
    UNION ALL SELECT agent_id, product_id, day FROM tr
  ) x GROUP BY agent_id, product_id
), att AS (
  SELECT agent_id, SUBSTR(JSON_VALUE(payload, '$.subject'), 9) AS product_id, day, t,
         CAST(JSON_VALUE(payload, '$.after.attitude') AS FLOAT64) AS attitude
  FROM `mirava.events`
  WHERE kind = 'belief_change' AND STARTS_WITH(JSON_VALUE(payload, '$.subject'), 'product:')
), st AS (
  SELECT d.day, tr.agent_id, tr.product_id, tr.stage
  FROM days d JOIN tr ON tr.day <= d.day
  QUALIFY ROW_NUMBER() OVER (PARTITION BY d.day, tr.agent_id, tr.product_id ORDER BY tr.t DESC) = 1
), pos AS (
  SELECT d.day, att.agent_id, att.product_id, att.attitude
  FROM days d JOIN att ON att.day <= d.day
  QUALIFY ROW_NUMBER() OVER (PARTITION BY d.day, att.agent_id, att.product_id ORDER BY att.t DESC) = 1
), prods AS (
  SELECT DISTINCT product_id FROM aw
), a1 AS (SELECT d.day, aw.product_id, COUNT(*) AS n FROM days d JOIN aw ON aw.day <= d.day GROUP BY 1, 2
), a2 AS (SELECT day, product_id, COUNT(*) AS n FROM pos WHERE attitude > 0.2 GROUP BY 1, 2
), a3 AS (SELECT day, product_id, COUNT(*) AS n FROM st
          WHERE stage IN ('curious', 'researching', 'inquiring', 'deciding', 'postponed', 'purchased') GROUP BY 1, 2
), a4 AS (SELECT day, product_id, COUNT(*) AS n FROM `mirava.events` WHERE kind = 'inquiry' GROUP BY 1, 2
), a5 AS (SELECT day, product_id, COUNT(*) AS n FROM `mirava.events` WHERE kind = 'purchase' GROUP BY 1, 2
)
SELECT d.day, p.product_id,
       COALESCE(a1.n, 0) AS aware, COALESCE(a2.n, 0) AS positive, COALESCE(a3.n, 0) AS considering,
       COALESCE(a4.n, 0) AS inquiries, COALESCE(a5.n, 0) AS purchases
FROM days d CROSS JOIN prods p
LEFT JOIN a1 ON a1.day = d.day AND a1.product_id = p.product_id
LEFT JOIN a2 ON a2.day = d.day AND a2.product_id = p.product_id
LEFT JOIN a3 ON a3.day = d.day AND a3.product_id = p.product_id
LEFT JOIN a4 ON a4.day = d.day AND a4.product_id = p.product_id
LEFT JOIN a5 ON a5.day = d.day AND a5.product_id = p.product_id
