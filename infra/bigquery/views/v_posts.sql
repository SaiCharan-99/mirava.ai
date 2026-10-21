-- v_posts: community threads and comments (C-05) with upvote counts per thread.
CREATE OR REPLACE VIEW `mirava.v_posts` AS
WITH up AS (
  SELECT JSON_VALUE(payload, '$.target') AS thread_id, COUNT(*) AS upvotes
  FROM `mirava.events_current` WHERE kind = 'upvote' GROUP BY 1
), p AS (
  SELECT event_id, t, day, agent_id AS author, product_id, kind,
         JSON_VALUE(payload, '$.thread_id') AS thread_id,
         JSON_VALUE(payload, '$.forum') AS forum,
         JSON_VALUE(payload, '$.title') AS title,
         COALESCE(JSON_VALUE(payload, '$.body'), JSON_VALUE(payload, '$.text')) AS text
  FROM `mirava.events_current`
  WHERE kind IN ('thread', 'comment')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY t_real) = 1
)
SELECT p.*, CASE WHEN p.kind = 'thread' THEN COALESCE(up.upvotes, 0) ELSE 0 END AS upvotes
FROM p LEFT JOIN up ON up.thread_id = p.thread_id
