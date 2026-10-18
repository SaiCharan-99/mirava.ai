-- v_site_daily: hoarding metrics per site × facing × product × day (A-06). Totals equal the sum of exposure events.
CREATE OR REPLACE VIEW `mirava.v_site_daily` AS
WITH ex AS (
  SELECT * FROM `mirava.v_exposures` WHERE channel IN ('hoarding', 'bus_shelter', 'metro_panel')
), th AS (
  SELECT site_id, product_id, day, COUNT(*) AS thoughts,
         AVG(CAST(JSON_VALUE(payload, '$.attitude_delta') AS FLOAT64)) AS sentiment
  FROM `mirava.events`
  WHERE kind = 'thought' AND site_id IS NOT NULL AND rendered
  GROUP BY site_id, product_id, day
)
SELECT
  ex.site_id, ex.facing, ex.product_id, ex.day,
  COUNT(*) AS ots,
  SUM(CASE WHEN ex.glanced THEN 1 ELSE 0 END) AS glances,
  SUM(CASE WHEN ex.noticed THEN 1 ELSE 0 END) AS notices,
  SUM(CASE WHEN ex.glanced THEN 1 ELSE 0 END) / COUNT(*) AS glance_rate,
  SUM(CASE WHEN ex.noticed THEN 1 ELSE 0 END) / COUNT(*) AS notice_rate,
  SUM(CASE WHEN ex.target THEN 1 ELSE 0 END) / COUNT(*) AS target_share,
  MAX(th.thoughts) AS thoughts,
  MAX(th.sentiment) AS sentiment,
  MAX(ex.rate_inr_day) / NULLIF(SUM(CASE WHEN ex.noticed THEN 1 ELSE 0 END), 0) AS cost_per_notice_inr
FROM ex
LEFT JOIN th ON th.site_id = ex.site_id AND th.product_id = ex.product_id AND th.day = ex.day
GROUP BY ex.site_id, ex.facing, ex.product_id, ex.day
