-- v_survey_answers: one private ballot per agent × question (answer as text; scale as number too).
CREATE OR REPLACE VIEW `mirava.v_survey_answers` AS
SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, JSON_VALUE(payload, '$.table_id') AS table_id,
       JSON_VALUE(payload, '$.question_id') AS question_id, agent_id, t, day, event_id,
       COALESCE(JSON_VALUE(payload, '$.answer'), TO_JSON_STRING(JSON_QUERY(payload, '$.answer'))) AS answer,
       SAFE_CAST(JSON_VALUE(payload, '$.answer') AS FLOAT64) AS answer_value,
       CAST(JSON_VALUE(payload, '$.confidence') AS FLOAT64) AS confidence,
       JSON_VALUE(payload, '$.reason') AS reason,
       JSON_VALUE(payload, '$.changed_from_prestance') = 'true' AS changed_from_prestance,
       JSON_VALUE(payload, '$.influence_type') AS influence_type,
       JSON_VALUE(payload, '$.influenced_by[0]') AS influenced_by_first,
       JSON_VALUE(payload, '$.public_private_gap') = 'true' AS public_private_gap,
       JSON_VALUE(payload, '$.effort') AS effort,
       COALESCE(JSON_VALUE(payload, '$.prestance'), TO_JSON_STRING(JSON_QUERY(payload, '$.prestance'))) AS prestance,
       JSON_VALUE(payload, '$.majority') AS table_majority,
       CAST(JSON_VALUE(payload, '$.susceptibility') AS FLOAT64) AS susceptibility
FROM `mirava.events`
WHERE kind = 'survey_answer'
QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id'), JSON_VALUE(payload, '$.question_id'),
                                        agent_id ORDER BY t DESC) = 1
