# Northwind Atlas — HR Workforce Analytics

A dbt analytics engineering project that builds a person-grain workforce mart reconciling competing headcount, attrition, and tenure definitions between Talent and Finance. Stitches employment records across internal transfers and rehires into a coherent employment history, resolves a 22–33% attrition reporting spread, and surfaces three simultaneous tenure definitions.

## The Problem

Two teams report different workforce numbers to the board:
- **VP of Talent** reports attrition at ~22% — counts only people who actually left the company, excludes internal transfers, nets out rehires
- **Head of Finance** reports attrition at ~33% — counts every closed employment record as an exit, including transfers between departments

Average tenure differs by ~1 year depending on whether rehires reset the clock.

The HRIS creates a new employment record (EMPLOYEE_ID) every time someone transfers departments or is rehired. This architectural choice causes the same human to appear as multiple "employees," inflating headcount, exits, and distorting tenure.

## Key Findings

| Metric | Value |
|--------|-------|
| Active headcount (person-grain) | 9,254 |
| Attrition rate (reconciled, trailing 12m) | 4.61% |
| Internal mobility rate | 2.04% |
| Rehire rate | 0.90% |
| Avg tenure (total service) | 5.31 yrs |
| Avg tenure (current stint) | 5.21 yrs |
| Tenure spread | 0.13 yrs |

### Reconciliation Bridge

```
Finance record-based exits (trailing 12m)                618
  Of which: true terminations                            429
  Of which: transfers miscounted as exits               -189  (30.6% of Finance exits)
                                                        ─────
Reconciled exits (person-level)                          427   → 4.6% attrition
Talent net exits (excludes rehired persons)              388   → 4.2% attrition

Bridge from Finance (6.7%) to Reconciled (4.6%):
  Remove transfers that are not real exits              -2.1 pp

Bridge from Talent (4.2%) to Reconciled (4.6%):
  Add back: rehires whose departure still counts       +0.4 pp
```

## Architecture

```
RAW (4 source tables — HRIS export)
 → STAGING (clean, deduplicate, classify, flag DQ issues)
   → INTERMEDIATE (stitch transfer chains, calculate tenure, normalize currency)
     → MARTS (5 deliverables for stakeholders)
```

| Layer | Materialization | Purpose |
|-------|----------------|---------|
| Staging | Views | Dedup 34 employee records, 6,038 payroll runs, 1,145 reviews; DQ flags |
| Intermediate | Tables | Recursive stint stitching, person-grain rollup, payroll enrichment |
| Marts | Tables | Final deliverables for Talent, Finance, and CPO |

## Deliverables

### 1. Workforce Mart (`fct_workforce`)
One row per person (12,000 total, 9,254 active). The single source of truth both Talent and Finance pull from. Includes:
- Current assignment (department, job level, location, cost center)
- Three tenure definitions (current stint, total service, continuous)
- Latest compensation (local + USD)
- Latest performance rating
- Employment history flags (is_rehire, has_transferred, total_stints)

### 2. Attrition Time Series (`fct_attrition_monthly`)
Monthly headcount, hires, exits, and trailing-12-month attrition rate. Person-grain — transfers excluded from exits.

### 3. Reconciliation Bridge (`rpt_reconciliation_bridge`)
Walks leadership from Finance's number to Talent's number line by line, explaining exactly how much of the spread is transfers, how much is rehires.

### 4. Department Dimension (`dim_department`)
10 departments across 3 divisions with active headcount. Correctly attributes transfers (source loses, destination gains — no phantom exits).

### 5. Workforce KPIs (`workforce_kpis`)
Single-row executive summary: headcount, attrition rate, mobility rate, rehire rate, three tenure averages, and the tenure spread between definitions.

## 10 Definitional Assumptions

Every number traces to an explicit, documented decision:

1. **Grain = Person (PERSON_ID)** — not employment record. One human = one row.
2. **Transfers are not exits** — a department change is continuous employment.
3. **Three tenure definitions** — current stint (Finance), total service (default), continuous (Talent).
4. **Attrition = true exits only** — trailing 12-month, person-grain, SHRM-standard.
5. **Status is authoritative over date** — employment_status determines event type; date gives timing.
6. **Duplicate active records deduplicated** — lower employee_id wins (34 system errors).
7. **Payroll dedup: latest paid_at wins** — cancelled/reissued runs resolved (6,038 removed).
8. **Review dedup: latest review_date wins** — duplicate submissions resolved (1,145 removed).
9. **Missing review dates: flagged, not imputed** — review_period used for time aggregation.
10. **Currency: fixed rates to USD** — GBP×1.27, EUR×1.09, SGD×0.74; local preserved.

Full rationale for each: see [`assumptions_log.md`](assumptions_log.md)

## Data Quality Issues Found

| # | Issue | Count | Severity | Action |
|---|-------|-------|----------|--------|
| 1 | Duplicate active employment records | 34 | Critical | Fixed in staging (dedup) |
| 2 | Cancelled/reissued payroll runs | 6,038 | Critical | Fixed in staging (latest wins) |
| 3 | Duplicate review submissions | 1,145 | High | Fixed in staging (latest wins) |
| 4 | Terminated status with no termination date | 30 | Medium | Flagged; escalate to HRIS |
| 5 | Missing review dates (cycle-close failure) | 2,465 | Medium | Flagged; escalate to HR Systems |
| 6 | 1 unlinked transfer (no successor) | 1 | Low | Investigate |

## Data Quality Framework

29 automated tests:
- **10 singular tests** (headcount reconciliation, grain uniqueness, chain continuity, dedup verification)
- **19 schema tests** (not_null, unique, accepted_values, relationships)

| Severity | Behavior | Example |
|----------|----------|---------|
| CRITICAL | Pipeline halts, alert fired | Person grain not unique, headcount doesn't tie |
| HIGH | Pipeline continues, output flagged | Orphan payroll, negative tenure |
| MEDIUM | Logged for weekly review | Missing termination dates |

## Project Structure

```
northwind_workforce/
├── dbt_project.yml
├── packages.yml
├── models/
│   ├── staging/
│   │   ├── _stg_sources.yml
│   │   ├── stg_employees.sql
│   │   ├── stg_departments.sql
│   │   ├── stg_payroll.sql
│   │   └── stg_performance_reviews.sql
│   ├── intermediate/
│   │   ├── int_employment_stints.sql
│   │   ├── int_person_employment_history.sql
│   │   └── int_payroll_monthly.sql
│   └── marts/
│       ├── _mart_models.yml
│       ├── fct_workforce.sql
│       ├── fct_attrition_monthly.sql
│       ├── dim_department.sql
│       ├── rpt_reconciliation_bridge.sql
│       └── workforce_kpis.sql
├── tests/
│   ├── assert_active_headcount_no_duplicates.sql
│   ├── assert_person_grain_unique.sql
│   ├── assert_dept_headcount_ties_to_total.sql
│   ├── assert_no_orphan_payroll.sql
│   ├── assert_tenure_positive.sql
│   ├── assert_transfer_chain_complete.sql
│   ├── assert_payroll_dedup_no_dupes.sql
│   ├── assert_review_dedup_no_dupes.sql
│   ├── assert_attrition_excludes_transfers.sql
│   └── assert_stint_continuity.sql
└── docs/
    ├── assumptions_log.md
    ├── source_to_target_map.md
    ├── architecture_diagram.md
    ├── data_quality_framework.md
    └── dag_design.md
```

## Tech Stack

| Tool | Purpose |
|------|---------|
| dbt-core 1.12 | Transformation framework |
| dbt-snowflake 1.12 | Snowflake adapter |
| Snowflake | Cloud data warehouse |
| dbt_utils | Testing utilities |

## Reproducing This Project

### Prerequisites

- Python 3.9+
- A Snowflake account with permission to create and load data into a project database
- The project is designed to run against a fixed, shared setup, not custom-edited dbt config files

### Reproduction contract

This project is intended to be reproduced using the exact database and schema names already defined in the project:

- Database: `NORTHWIND_ATLAS`
- Raw source schema: `RAW`
- dbt profile name: `peoplecore`
- dbt development schema: `DEV_JUMOKE` (or another schema you create consistently and keep in the same profile)

Do not edit the project `profiles.yml` or the source YAML files to rename the database or schema. The intended workflow is to create the matching Snowflake objects and keep the dbt configuration as shipped.

### Setup

```bash
# Clone the repository
git clone https://github.com/dzumii/aef-project.git
cd case-studies/08-hr-workforce-analytics/data_generator

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
pip install dbt-snowflake==1.12.0
```

### Create the matching Snowflake objects

Create the database and raw schema exactly as expected by the project:

```sql
CREATE DATABASE IF NOT EXISTS NORTHWIND_ATLAS;
CREATE SCHEMA IF NOT EXISTS NORTHWIND_ATLAS.RAW;
CREATE SCHEMA IF NOT EXISTS NORTHWIND_ATLAS.DEV_JUMOKE;
```

Load the generated source data into `NORTHWIND_ATLAS.RAW` using the raw table names referenced in the project sources.

Then keep the project profile configuration unchanged and point your local `.dbt/profiles.yml` to the same Snowflake account and credentials. The profile in the project already expects the default names used above.

### Build the full pipeline

```bash
# Install packages
dbt deps

# Verify connection
dbt debug

# Run all models (staging → intermediate → marts)
dbt run

# Run all 29 tests
dbt test

# Or do both in one pass
dbt build
```

### Run individual layers

```bash
# Staging only
dbt run --select staging
dbt test --select staging

# Intermediate only
dbt run --select intermediate

# Marts only
dbt run --select marts
dbt test --select marts
```

### Validate the reconciliation

This project ships with a ready-to-run validation script in the docs folder:

- [case-studies/08-hr-workforce-analytics/dbt_starter/docs/northwind_atlas.sql](case-studies/08-hr-workforce-analytics/dbt_starter/docs/northwind_atlas.sql)

Run that script in Snowflake after `dbt run` to confirm the raw tables, staged models, intermediate models, and final marts all align with the fixed project database/schema convention.

The script includes the core verification queries, including:

```sql
SELECT * FROM NORTHWIND_ATLAS.DEV_JUMOKE.RPT_RECONCILIATION_BRIDGE;
SELECT
    (SELECT SUM(active_headcount) FROM NORTHWIND_ATLAS.DEV_JUMOKE.DIM_DEPARTMENT) AS dept_sum,
    (SELECT COUNT(*) FROM NORTHWIND_ATLAS.DEV_JUMOKE.FCT_WORKFORCE WHERE is_currently_active = 1) AS person_count;
SELECT * FROM NORTHWIND_ATLAS.DEV_JUMOKE.WORKFORCE_KPIS;
```

### Validate headcount ties out

The validation script already contains the headcount checks; use it as the canonical verification for this project.

### Validate KPIs

The KPI validation is also included in the SQL doc at [case-studies/08-hr-workforce-analytics/dbt_starter/docs/northwind_atlas.sql](case-studies/08-hr-workforce-analytics/dbt_starter/docs/northwind_atlas.sql).

## DAG / Orchestration Design

For production deployment, the pipeline runs daily at 06:00 UTC:

```
source_freshness → run_staging → test_staging → run_intermediate
→ run_marts → test_marts → notify_success
```

- CRITICAL test failure = pipeline halts, marts retain yesterday's data
- HIGH test failure = marts refresh with warning flag
- Full re-run is idempotent (same input = same output)



