-- v_inquiries: store inquiries (T-03), one row per visit; first_topic / first_question for grouping.
CREATE OR REPLACE VIEW `mirava.v_inquiries` AS
SELECT
  event_id, t, day, agent_id, other_id AS salesperson_id, product_id, session_id, rendered,
  JSON_VALUE(payload, '$.store_id') AS store_id,
  JSON_VALUE(payload, '$.outcome') AS outcome,
  CAST(JSON_VALUE(payload, '$.satisfaction') AS FLOAT64) AS satisfaction,
  CAST(JSON_VALUE(payload, '$.n_messages') AS INT64) AS n_messages,
  JSON_VALUE(payload, '$.topics[0]') AS first_topic,
  JSON_VALUE(payload, '$.questions[0]') AS first_question
FROM `mirava.events`
WHERE kind = 'inquiry'
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
