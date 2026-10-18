-- v_survey_messages: public focus-group messages (moderator included), ordered per table and question.
CREATE OR REPLACE VIEW `mirava.v_survey_messages` AS
SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, JSON_VALUE(payload, '$.table_id') AS table_id,
       JSON_VALUE(payload, '$.question_id') AS question_id, session_id,
       CAST(JSON_VALUE(payload, '$.seq') AS INT64) AS seq, JSON_VALUE(payload, '$.message_id') AS message_id,
       agent_id AS speaker_id, COALESCE(CAST(agent_id AS STRING), 'moderator') AS speaker,
       JSON_VALUE(payload, '$.text') AS text, CAST(JSON_VALUE(payload, '$.addressed_to') AS INT64) AS addressed_to,
       t, day, event_id
FROM `mirava.events`
WHERE kind = 'message' AND JSON_VALUE(payload, '$.conv_kind') = 'focus_group'
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
