-- v_survey_waves: answer per agent per wave for a panel (root survey id = the first wave).
CREATE OR REPLACE VIEW `mirava.v_survey_waves` AS
WITH s AS (
  SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, CAST(JSON_VALUE(payload, '$.wave') AS INT64) AS wave,
         COALESCE(JSON_VALUE(payload, '$.panel_id'), JSON_VALUE(payload, '$.survey_id')) AS panel_id
  FROM `mirava.events` WHERE kind = 'survey_created'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id') ORDER BY t) = 1
), a AS (
  SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, JSON_VALUE(payload, '$.question_id') AS question_id,
         agent_id, COALESCE(JSON_VALUE(payload, '$.answer'), TO_JSON_STRING(JSON_QUERY(payload, '$.answer'))) AS answer,
         JSON_VALUE(payload, '$.reason') AS reason, t, event_id
  FROM `mirava.events` WHERE kind = 'survey_answer'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id'), JSON_VALUE(payload, '$.question_id'),
                                          agent_id ORDER BY t DESC) = 1
)
SELECT s.panel_id, s.wave, a.survey_id, a.question_id, a.agent_id, a.answer, a.reason, a.t, a.event_id
FROM a JOIN s ON s.survey_id = a.survey_id
