-- DROP DATABASE IF EXISTS COBALT_MOBILITY;
--CREATE DATABASE IF NOT EXISTS COBALT_MOBILITY;
--CREATE SCHEMA IF NOT EXISTS COBALT_MOBILITY.RAW;
--CREATE SCHEMA IF NOT EXISTS COBALT_MOBILITY.DEV_JUMOKE;

--SHOW SCHEMAS IN DATABASE COBALT_MOBILITY;
--SHOW WAREHOUSES;
--SELECT * FROM COBALT_MOBILITY.RAW.RAW_RIDERS;
--SELECT * FROM COBALT_MOBILITY.RAW.RAW_DRIVERS;
--SELECT * FROM COBALT_MOBILITY.RAW.RAW_TRIPS;
--SELECT * FROM COBALT_MOBILITY.RAW.RAW_PAYMENTS;
--SELECT * FROM COBALT_MOBILITY.RAW.RAW_DRIVER_INCENTIVES;

DESCRIBE TABLE COBALT_MOBILITY.RAW.RAW_RIDERS;
DESCRIBE TABLE COBALT_MOBILITY.RAW.RAW_DRIVERS;
DESCRIBE TABLE COBALT_MOBILITY.RAW.RAW_TRIPS;
DESCRIBE TABLE COBALT_MOBILITY.RAW.RAW_PAYMENTS;
DESCRIBE TABLE COBALT_MOBILITY.RAW.RAW_DRIVER_INCENTIVES;

SELECT * FROM COBALT_MOBILITY.DEV_JUMOKE.STG_RIDERS LIMIT 10;
SELECT * FROM COBALT_MOBILITY.DEV_JUMOKE.STG_DRIVERS LIMIT 10;
SELECT * FROM COBALT_MOBILITY.DEV_JUMOKE.STG_TRIPS LIMIT 10;
SELECT * FROM COBALT_MOBILITY.DEV_JUMOKE.STG_PAYMENTS LIMIT 10;
SELECT * FROM COBALT_MOBILITY.DEV_JUMOKE.STG_DRIVER_INCENTIVES LIMIT 10;

SHOW VIEWS IN SCHEMA COBALT_MOBILITY.DEV_JUMOKE;

-- Confirm row counts
SELECT 'int_trips_enriched' AS model, COUNT(*) AS rowss FROM COBALT_MOBILITY.DEV_JUMOKE.INT_TRIPS_ENRICHED
UNION ALL
SELECT 'int_driver_metrics', COUNT(*) FROM COBALT_MOBILITY.DEV_JUMOKE.INT_DRIVER_METRICS
UNION ALL
SELECT 'int_rider_activity', COUNT(*) FROM COBALT_MOBILITY.DEV_JUMOKE.INT_RIDER_ACTIVITY;

-- Expected:
-- int_trips_enriched:  80,000 (one per trip)
-- int_driver_metrics:   4,000 (one per driver, deduped)
-- int_rider_activity:  20,000 (one per rider)

-- Validate the GMV-to-net bridge components from int_trips_enriched
SELECT
  SUM(CASE WHEN is_completed THEN gross_fare_usd ELSE 0 END) AS gmv_usd,
  SUM(CASE WHEN is_revenue_eligible THEN captured_amount_usd ELSE 0 END) AS revenue_captured_usd,
  SUM(CASE WHEN is_revenue_eligible THEN processor_fee_usd ELSE 0 END) AS fees_usd,
  SUM(CASE WHEN is_fraud_flagged THEN captured_amount_usd ELSE 0 END) AS fraud_captured_usd,
  SUM(incentive_amount_usd) AS total_incentives_usd
FROM COBALT_MOBILITY.DEV_JUMOKE.INT_TRIPS_ENRICHED;

-- Verify driver incentive reconciliation
-- This must match: SUM(bonus_amount) from RAW_DRIVER_INCENTIVES per driver
SELECT
  d.driver_id,
  d.total_incentive_paid AS mart_total,
  r.raw_total,
  d.total_incentive_paid - r.raw_total AS diff
FROM COBALT_MOBILITY.DEV_JUMOKE.INT_DRIVER_METRICS d
JOIN (
  SELECT driver_id, SUM(bonus_amount) AS raw_total
  FROM COBALT_MOBILITY.RAW.RAW_DRIVER_INCENTIVES
  GROUP BY driver_id
) r ON d.driver_id = r.driver_id
WHERE ABS(d.total_incentive_paid - r.raw_total) > 0.01
LIMIT 5;
-- Expected: 0 rows (perfect reconciliation)

-- Row counts
SELECT 'mart_drivers' AS model, COUNT(*) AS rowss FROM COBALT_MOBILITY.DEV_JUMOKE.MART_DRIVERS
UNION ALL
SELECT 'mart_riders', COUNT(*) FROM COBALT_MOBILITY.DEV_JUMOKE.MART_RIDERS
UNION ALL
SELECT 'mart_marketplace_kpis', COUNT(*) FROM COBALT_MOBILITY.DEV_JUMOKE.MART_MARKETPLACE_KPIS
UNION ALL
SELECT 'mart_reconciliation', COUNT(*) FROM COBALT_MOBILITY.DEV_JUMOKE.MART_RECONCILIATION;

-- Expected:
-- mart_drivers:            4,000
-- mart_riders:            20,000
-- mart_marketplace_kpis:      12 (one per month, Jan-Dec 2024)
-- mart_reconciliation:         1 (single summary row)

-- The reconciliation bridge — the deliverable the COO needs
SELECT * FROM COBALT_MOBILITY.DEV_JUMOKE.MART_RECONCILIATION;

-- Active rider counts by definition — shows the 10-15% variance
SELECT
  COUNT(CASE WHEN is_active_account THEN 1 END) AS active_by_crm,
  COUNT(CASE WHEN is_active_30d THEN 1 END) AS active_30d_completed,
  COUNT(CASE WHEN is_active_90d THEN 1 END) AS active_90d_completed,
  COUNT(CASE WHEN is_active_any_trip_30d THEN 1 END) AS active_30d_any_trip
FROM COBALT_MOBILITY.DEV_JUMOKE.MART_RIDERS;


-- Driver incentive reconciliation check (must return 0 rows)
SELECT d.driver_id, d.total_incentive_paid, r.raw_total
FROM COBALT_MOBILITY.DEV_JUMOKE.MART_DRIVERS d
JOIN (
  SELECT driver_id, SUM(bonus_amount) AS raw_total
  FROM COBALT_MOBILITY.RAW.RAW_DRIVER_INCENTIVES
  GROUP BY driver_id
) r ON d.driver_id = r.driver_id
WHERE ABS(d.total_incentive_paid - r.raw_total) > 0.01;