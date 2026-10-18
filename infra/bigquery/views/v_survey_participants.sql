-- v_survey_participants: invitations and RSVPs (reason is PRIVATE — label it when quoted).
CREATE OR REPLACE VIEW `mirava.v_survey_participants` AS
SELECT JSON_VALUE(payload, '$.survey_id') AS survey_id, agent_id, t,
       JSON_VALUE(payload, '$.rsvp') AS rsvp, JSON_VALUE(payload, '$.status') AS status,
       JSON_VALUE(payload, '$.reason') AS rsvp_reason_private,
       EXISTS (SELECT 1 FROM `mirava.events` a WHERE a.kind = 'survey_answer' AND a.agent_id = r.agent_id
               AND JSON_VALUE(a.payload, '$.survey_id') = JSON_VALUE(r.payload, '$.survey_id')) AS attended
FROM `mirava.events` r
WHERE kind = 'survey_rsvp'
QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(payload, '$.survey_id'), agent_id ORDER BY t DESC) = 1
