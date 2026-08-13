
-- CREATE DATABASE IF NOT EXISTS NORTHWIND_ATLAS;
-- CREATE SCHEMA IF NOT EXISTS NORTHWIND_ATLAS.RAW;
-- CREATE SCHEMA IF NOT EXISTS NORTHWIND_ATLAS.DEV_JUMOKE;

-- SHOW SCHEMAS IN DATABASE NORTHWIND_ATLAS;
-- SHOW WAREHOUSES;

SELECT * FROM NORTHWIND_ATLAS.RAW.RAW_DEPARTMENTS;
SELECT * FROM NORTHWIND_ATLAS.RAW.RAW_EMPLOYEES;
SELECT * FROM NORTHWIND_ATLAS.RAW.RAW_PERFORMANCE_REVIEWS;
SELECT * FROM NORTHWIND_ATLAS.RAW.RAW_PAYROLL;

DESCRIBE TABLE NORTHWIND_ATLAS.RAW.RAW_DEPARTMENTS;
DESCRIBE TABLE NORTHWIND_ATLAS.RAW.RAW_EMPLOYEES;
DESCRIBE TABLE NORTHWIND_ATLAS.RAW.RAW_PERFORMANCE_REVIEWS;
DESCRIBE TABLE NORTHWIND_ATLAS.RAW.RAW_PAYROLL;

--expects stg_departments:10,stg_employees:13773,stg_payroll:602677,stg_performance_reviews:35286
SELECT 'stg_employees' AS model, COUNT(*) AS rowss FROM NORTHWIND_ATLAS.DEV_JUMOKE.STG_EMPLOYEES
UNION ALL SELECT 'stg_payroll', COUNT(*) FROM NORTHWIND_ATLAS.DEV_JUMOKE.STG_PAYROLL
UNION ALL SELECT 'stg_performance_reviews', COUNT(*) FROM NORTHWIND_ATLAS.DEV_JUMOKE.STG_PERFORMANCE_REVIEWS
UNION ALL SELECT 'stg_departments', COUNT(*) FROM NORTHWIND_ATLAS.DEV_JUMOKE.STG_DEPARTMENTS;


-- 1. Person history: should be exactly 12,000 persons
SELECT
    COUNT(*) AS total_persons,
    SUM(CASE WHEN is_currently_active = 1 THEN 1 ELSE 0 END) AS active_persons,
    SUM(CASE WHEN is_rehire THEN 1 ELSE 0 END) AS rehires,
    SUM(CASE WHEN has_transferred THEN 1 ELSE 0 END) AS has_transferred,
    ROUND(AVG(CASE WHEN is_currently_active = 1 THEN tenure_total_service_years END), 2) AS avg_tenure_total_svc,
    ROUND(AVG(CASE WHEN is_currently_active = 1 THEN tenure_current_stint_years END), 2) AS avg_tenure_current_stint
FROM NORTHWIND_ATLAS.DEV_JUMOKE.INT_PERSON_EMPLOYMENT_HISTORY;

-- 2. Stint model: verify transfer chains resolved
SELECT
    record_type,
    COUNT(*) AS records,
    COUNT(DISTINCT person_id) AS persons
FROM NORTHWIND_ATLAS.DEV_JUMOKE.INT_EMPLOYMENT_STINTS
GROUP BY 1;

-- 3. Active headcount must equal 9,254 (deduplicated persons)
SELECT COUNT(*) AS active_headcount
FROM NORTHWIND_ATLAS.DEV_JUMOKE.INT_PERSON_EMPLOYMENT_HISTORY
WHERE is_currently_active = 1;

-- 1. fct_workforce: person grain, one row per human.fct_workforce = 12,000 rows, ~9,254 active
SELECT
    COUNT(*) AS total_persons,
    SUM(CASE WHEN is_currently_active = 1 THEN 1 ELSE 0 END) AS active,
    SUM(CASE WHEN is_rehire THEN 1 ELSE 0 END) AS rehires,
    ROUND(AVG(CASE WHEN is_currently_active = 1 THEN tenure_total_service_years END), 2) AS avg_tenure_svc,
    ROUND(AVG(CASE WHEN is_currently_active = 1 THEN tenure_current_stint_years END), 2) AS avg_tenure_stint
FROM NORTHWIND_ATLAS.DEV_JUMOKE.FCT_WORKFORCE;

-- 2. dim_department: headcount should sum to active persons. dim_department active_headcount sums to ~9,254
SELECT SUM(active_headcount) AS total_active
FROM NORTHWIND_ATLAS.DEV_JUMOKE.DIM_DEPARTMENT;

-- 3. Reconciliation bridge
SELECT * FROM NORTHWIND_ATLAS.DEV_JUMOKE.RPT_RECONCILIATION_BRIDGE;

-- 4. Latest attrition rate
SELECT month_start, active_headcount_eom, exits_trailing_12m, attrition_rate_trailing_12m
FROM NORTHWIND_ATLAS.DEV_JUMOKE.FCT_ATTRITION_MONTHLY
ORDER BY month_start DESC
LIMIT 12;

SELECT * FROM NORTHWIND_ATLAS.DEV_JUMOKE.WORKFORCE_KPIS;