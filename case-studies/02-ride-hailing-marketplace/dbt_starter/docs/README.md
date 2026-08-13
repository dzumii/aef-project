# Cobalt Mobility — Ride-Hailing Marketplace Analytics

A dbt analytics engineering project that builds a single source of truth for a ride-hailing startup operating in four cities (~80K trips, ~$1M GMV). Reconciles competing GMV, net revenue, and driver payout definitions across Growth, Finance, and Driver Operations stakeholders.

## The Problem

Three teams report different top-line numbers:
- **VP Growth** reports GMV (gross bookings) — every fare riders agreed to pay
- **Head of Finance** reports net revenue — 8–12% lower, varying monthly
- **Head of Driver Ops** reports driver earnings — must match what hits bank accounts

This project makes each definition explicit, reconciles the gap, and lets every stakeholder read their own number from the same models.

## Key Findings

| Metric | Value |
|--------|-------|
| Growth GMV | $952,091 |
| Finance Net Revenue | $855,749 |
| Gap | $96,342 (10.1%) |
| Fraud reversals | 31% of gap |
| Uncollected fares | 29% of gap |
| Processor fees | 39% of gap |

## Architecture

```
RAW (5 source tables)
 → STAGING (clean, deduplicate, classify)
   → INTERMEDIATE (join, enrich, aggregate)
     → MARTS (4 deliverables)
```

| Layer | Materialization | Purpose |
|-------|----------------|---------|
| Staging | Views | Dedup drivers/payments, classify trips, flag multi-campaign |
| Intermediate | Views | Join trip+payment+incentive, USD conversion, per-entity aggregation |
| Marts | Tables | Final deliverables for stakeholders |

## Deliverables

### 1. Driver Performance Mart (`mart_drivers`)
One row per driver (4,000 after deduplication). Includes trips, completion rate, fraud rate, gross earnings, and incentive spend that reconciles to the raw payment ledger.

### 2. Rider Activity Mart (`mart_riders`)
One row per rider (20,000) with four concurrent active-rider definitions:

| Definition | Logic | Stakeholder |
|---|---|---|
| `is_active_account` | CRM status = 'active' | CRM (vanity) |
| `is_active_30d` | Completed non-fraud trip in trailing 30 days | Growth |
| `is_active_90d` | Completed non-fraud trip in trailing 90 days | Finance |
| `is_active_any_trip_30d` | Any trip requested in trailing 30 days | Ops |

### 3. Marketplace KPI Layer (`mart_marketplace_kpis`)
Monthly GMV, net revenue, take rate, cancellation rate, fraud rate, incentive spend — all with explicit definitions and USD conversion.

### 4. Reconciliation Bridge (`mart_reconciliation`)
Single-row model that walks from Growth GMV to Finance net revenue, line by line:

```
Growth GMV (completed trip fares, incl. fraud)       $952,091
Less: Fraud reversals                                – $30,391  (31%)
Less: Uncollected fares (no captured payment)        – $28,065  (29%)
Less: Processor fees                                 – $37,887  (39%)
                                                     ─────────
= Finance Net Revenue                                $855,749
Gap rate: 10.1%
```

## Data Quality Framework

48 automated tests across all layers:
- **10 singular tests** (referential integrity, reconciliation, business rule assertions)
- **38 schema tests** (not_null, unique, accepted_values, accepted_range)

| Severity | Behavior | Example |
|----------|----------|---------|
| ERROR | Pipeline blocks | Orphan FK, incentive mismatch, negative fare |
| WARN | Log and continue | Future timestamps, gap outside bounds |

## 7 Definitional Assumptions

Every number in this project traces to an explicit, documented decision:

1. **Driver Deduplication** — Latest row per driver_id wins (re-onboarding creates duplicates)
2. **Payment Deduplication** — First captured payment per trip (retries/webhook dupes removed)
3. **Fraud Treatment** — In GMV (Growth), out of net revenue (Finance), driver keeps earnings (Ops)
4. **Currency** — GBP→USD at 1.27 fixed rate; local preserved at grain
5. **Incentive Attribution** — All campaign lines are real costs; no cross-campaign dedup
6. **Cancellation Classification** — Excluded from GMV; billed cancellations = separate fee revenue
7. **Revenue Recognition** — At payment capture, not trip end

Full rationale for each: see [`assumptions_log.md`](assumptions_log.md)

## Data Quality Issues Found

| # | Issue | Severity | Action |
|---|-------|----------|--------|
| 1 | 160 duplicate driver rows | Medium | Fixed in staging (dedup) |
| 2 | ~6,700 multi-payment trips | Critical | Fixed in staging (first capture wins) |
| 3 | 6,473 dual-attributed incentive trips | High | Surfaced as metric (not a bug — campaign overlap) |
| 4 | $2,835 incentives paid on fraud trips | High | Surfaced in reconciliation (leakage) |
| 5 | Mixed GBP/USD | Critical | Fixed in intermediate (conversion) |
| 6 | 1,956 completed trips with no capture | Critical | Escalate to payments engineering |
| 7 | 3,312 no_driver_found at $0 fare | Low | Excluded from GMV |

## Project Structure

```
cobalt_mobility_dbt/
├── dbt_project.yml
├── packages.yml
├── models/
│   ├── staging/
│   │   ├── _stg__sources.yml
│   │   ├── _stg__models.yml
│   │   ├── stg_riders.sql
│   │   ├── stg_drivers.sql
│   │   ├── stg_trips.sql
│   │   ├── stg_payments.sql
│   │   └── stg_driver_incentives.sql
│   ├── intermediate/
│   │   ├── _int__models.yml
│   │   ├── int_trips_enriched.sql
│   │   ├── int_driver_metrics.sql
│   │   └── int_rider_activity.sql
│   └── marts/
│       ├── _mart__models.yml
│       ├── mart_drivers.sql
│       ├── mart_riders.sql
│       ├── mart_marketplace_kpis.sql
│       └── mart_reconciliation.sql
├── tests/
│   ├── staging/
│   │   ├── assert_no_orphan_trips_without_rider.sql
│   │   ├── assert_no_orphan_payments_without_trip.sql
│   │   ├── assert_no_negative_fares.sql
│   │   └── assert_no_future_trips.sql
│   ├── intermediate/
│   │   ├── assert_driver_incentive_reconciliation.sql
│   │   ├── assert_no_revenue_on_fraud_trips.sql
│   │   └── assert_captured_lte_gross_fare.sql
│   └── marts/
│       ├── assert_gap_rate_within_bounds.sql
│       ├── assert_rider_definitions_monotonic.sql
│       └── assert_kpi_months_complete.sql
└── docs/
    └── assumptions_log.md
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
- A Snowflake account with the raw data loaded into `<YOUR_DB>.RAW`
- A development schema for dbt to write to

### Setup

```bash
# Clone the repository
git clone https://github.com/<your-username>/cobalt-mobility-analytics.git
cd cobalt-mobility-analytics

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install dbt-snowflake==1.12.0
```

### Configure Snowflake connection

Create or update `~/.dbt/profiles.yml`:

```yaml
cobalt_mobility_dbt:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: <your-account>
      user: <your-username>
      authenticator: externalbrowser
      role: <your-role>
      warehouse: <your-warehouse>
      database: <your-database>
      schema: <your-dev-schema>
      threads: 4
```

### Verify connection

```bash
dbt debug
```

### Install packages

```bash
dbt deps
```

### Build the full pipeline

```bash
# Run all models (staging → intermediate → marts)
dbt run

# Run all 48 tests
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
dbt test --select intermediate

# Marts only
dbt run --select marts
dbt test --select marts
```

### Check source freshness

```bash
dbt source freshness
```

Note: With static/historical data, sources will report as stale. This is expected and confirms the freshness check is wired correctly.

### Generate and view documentation

```bash
dbt docs generate
dbt docs serve
```

### Validate the reconciliation

After `dbt run`, verify the GMV-to-net bridge in Snowflake:

```sql
SELECT * FROM <your-schema>.MART_RECONCILIATION;
```

Expected output: single row showing GMV, net revenue, gap rate ~10.1%, with fraud/uncollected/fees breakdown.

### Validate driver incentive reconciliation

```sql
-- Should return 0 rows (perfect match to raw ledger)
SELECT d.driver_id, d.total_incentive_paid, r.raw_total
FROM <your-schema>.MART_DRIVERS d
JOIN (
  SELECT driver_id, SUM(bonus_amount) AS raw_total
  FROM <your-database>.RAW.RAW_DRIVER_INCENTIVES
  GROUP BY driver_id
) r ON d.driver_id = r.driver_id
WHERE ABS(d.total_incentive_paid - r.raw_total) > 0.01;
```

### Validate active rider definitions

```sql
SELECT
  COUNT(CASE WHEN is_active_account THEN 1 END) AS crm_active,
  COUNT(CASE WHEN is_active_30d THEN 1 END) AS active_30d,
  COUNT(CASE WHEN is_active_90d THEN 1 END) AS active_90d,
  COUNT(CASE WHEN is_active_any_trip_30d THEN 1 END) AS any_trip_30d
FROM <your-schema>.MART_RIDERS;
```

Expected: 10–15% variance between definitions.

## DAG / Orchestration Design

For production deployment, the pipeline runs daily at 06:00 UTC:

```
source_freshness → run_staging → test_staging → run_intermediate
→ test_intermediate → run_marts → test_marts → notify_success
```

- ERROR-severity test failure = pipeline halts, alert fired
- WARN-severity test failure = logged, pipeline continues
- Full re-run is idempotent (same input = same output)

## License

This project was built as part of an analytics engineering engagement for Cobalt Mobility.
