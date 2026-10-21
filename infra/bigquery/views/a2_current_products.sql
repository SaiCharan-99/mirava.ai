-- current_products: launched product ids that are not retired (fix-E). Free-text chat mentions are matched against it.
CREATE OR REPLACE VIEW `mirava.current_products` AS
SELECT DISTINCT product_id
FROM `mirava.events_current`
WHERE kind = 'launch' AND product_id IS NOT NULL
