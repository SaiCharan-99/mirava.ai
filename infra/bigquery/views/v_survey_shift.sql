-- v_survey_shift: private prestance → final answer per agent × question (who changed, how, why).
CREATE OR REPLACE VIEW `mirava.v_survey_shift` AS
SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, JSON_VALUE(payload, '$.question_id') AS question_id,
       agent_id, JSON_VALUE(payload, '$.table_id') AS table_id,
       COALESCE(JSON_VALUE(payload, '$.prestance'), TO_JSON_STRING(JSON_QUERY(payload, '$.prestance'))) AS prestance,
       COALESCE(JSON_VALUE(payload, '$.answer'), TO_JSON_STRING(JSON_QUERY(payload, '$.answer'))) AS final_answer,
       JSON_VALUE(payload, '$.changed_from_prestance') = 'true' AS changed,
       JSON_VALUE(payload, '$.influence_type') AS influence_type,
       JSON_VALUE(payload, '$.influenced_by[0]') AS influenced_by_first,
       JSON_VALUE(payload, '$.reason') AS reason, t, event_id
FROM `mirava.events_current`
WHERE kind = 'survey_answer' AND JSON_VALUE(payload, '$.written') != 'true'
QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id'), JSON_VALUE(payload, '$.question_id'),
                                        agent_id ORDER BY t DESC) = 1
