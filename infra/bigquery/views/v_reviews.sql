-- v_reviews: reviewer private opinion (private) vs the published review, per review.
CREATE OR REPLACE VIEW `mirava.v_reviews` AS
WITH pub AS (
  SELECT JSON_VALUE(payload, '$.review_id') AS review_id, agent_id AS reviewer, product_id, t AS t_published,
         day, JSON_VALUE(payload, '$.title') AS title, JSON_VALUE(payload, '$.summary') AS summary,
         CAST(JSON_VALUE(payload, '$.rating') AS FLOAT64) AS rating
  FROM `mirava.events_current` WHERE kind = 'review_published'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.review_id') ORDER BY t) = 1
), priv AS (
  SELECT JSON_VALUE(payload, '$.review_id') AS review_id, agent_id AS reviewer, product_id, t AS t_private,
         JSON_VALUE(payload, '$.private_opinion') AS private_opinion,
         CAST(JSON_VALUE(payload, '$.rating') AS FLOAT64) AS private_rating
  FROM `mirava.events_current` WHERE kind = 'review_private'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.review_id') ORDER BY t) = 1
)
SELECT priv.review_id, priv.reviewer, priv.product_id, priv.t_private, pub.t_published,
       pub.day, pub.title, pub.summary, pub.rating, priv.private_opinion, priv.private_rating
FROM priv LEFT JOIN pub ON pub.review_id = priv.review_id
