-- v_surveys: one row per survey / focus group (wave, panel, counts, cost) — Survey Room (phase-5 addendum).
CREATE OR REPLACE VIEW `mirava.v_surveys` AS
WITH c AS (
  SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, t AS created_t, day AS created_day,
         JSON_VALUE(payload, '$.title') AS title, JSON_VALUE(payload, '$.mode') AS mode,
         CAST(JSON_VALUE(payload, '$.n_questions') AS INT64) AS n_questions, JSON_VALUE(payload, '$.cohort') AS cohort,
         CAST(JSON_VALUE(payload, '$.wave') AS INT64) AS wave, JSON_VALUE(payload, '$.panel_id') AS panel_id,
         JSON_VALUE(payload, '$.parent_survey_id') AS parent_survey_id, product_id,
         CAST(JSON_VALUE(payload, '$.start_at_t') AS INT64) AS start_at_t
  FROM `mirava.events` WHERE kind = 'survey_created'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id') ORDER BY t) = 1
), f AS (
  SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, t AS completed_t,
         CAST(JSON_VALUE(payload, '$.counts.invited') AS INT64) AS invited,
         CAST(JSON_VALUE(payload, '$.counts.attended') AS INT64) AS attended,
         CAST(JSON_VALUE(payload, '$.counts.answers') AS INT64) AS answers,
         CAST(JSON_VALUE(payload, '$.counts.changed') AS INT64) AS changed,
         CAST(JSON_VALUE(payload, '$.actual_usd') AS FLOAT64) AS actual_usd,
         CAST(JSON_VALUE(payload, '$.estimate_usd') AS FLOAT64) AS estimate_usd,
         JSON_VALUE(payload, '$.discussion_skipped') = 'true' AS discussion_skipped
  FROM `mirava.events` WHERE kind = 'survey_completed'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id') ORDER BY t DESC) = 1
)
SELECT c.*, f.completed_t, f.invited, f.attended, f.answers, f.changed, f.actual_usd, f.estimate_usd,
       f.discussion_skipped, CASE WHEN f.completed_t IS NULL THEN 'running' ELSE 'completed' END AS status
FROM c LEFT JOIN f ON f.survey_id = c.survey_id
