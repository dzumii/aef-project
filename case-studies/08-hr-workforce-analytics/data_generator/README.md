# Data Generator — Northwind Atlas raw HR sandbox

This script provisions the four raw HR tables into your Snowflake sandbox. It
simulates an HRIS export: the data is **realistic and deliberately imperfect**.
Cleaning and reconciling it is the engagement.

## Setup

```bash
cd data_generator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Provide Snowflake credentials (see .env.example for the full list)
export SNOWFLAKE_ACCOUNT=xy12345.us-east-1
export SNOWFLAKE_USER=YOUR_USER
export SNOWFLAKE_PASSWORD=********
export SNOWFLAKE_ROLE=SYSADMIN
export SNOWFLAKE_WAREHOUSE=COMPUTE_WH
export SNOWFLAKE_DATABASE=PEOPLECORE
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 12,000 people, seed 42 (reproducible)
python generate_data.py

# Smaller/larger (this is a count of PEOPLE; employment records will exceed it)
python generate_data.py --employees 4000

# Validate generation without touching Snowflake (no connector required)
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the four tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--employees` always produce
> identical data. Use the default seed so reviewers see the same dataset you
> modeled against. The reporting "as-of" date is fixed at **2025-12-31**.

> **Grain warning:** `--employees` controls the number of distinct *people*. The
> `RAW_EMPLOYEES` table has **more rows than that** — a person who transfers
> departments or is rehired appears under more than one employment record. This
> is the whole point of the engagement.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_EMPLOYEES` — one row per employment **record** (NOT per person)
| Column | Type | Description |
|---|---|---|
| `EMPLOYEE_ID` | NUMBER | Unique per employment record. A new record opens on transfer or rehire. |
| `PERSON_ID` | NUMBER | Stable identifier for the human. Repeats across a person's records. |
| `FULL_NAME` | VARCHAR | Display name (derived from `PERSON_ID`). |
| `DEPARTMENT_ID` | NUMBER | The department of this record. Joins to `RAW_DEPARTMENTS`. |
| `JOB_LEVEL` | VARCHAR | `IC1`–`IC4`, `M1`–`M3`. |
| `EMPLOYMENT_TYPE` | VARCHAR | `full_time`, `part_time`, `contractor`. |
| `LOCATION` | VARCHAR | Office or remote region. |
| `HIRE_DATE` | TIMESTAMP_NTZ | Start of *this record*. On a transfer/rehire record this is the move/return date — **not** the person's original hire. |
| `TERMINATION_DATE` | TIMESTAMP_NTZ | End of this record; null if open. Set when a record is closed by a term **or** a transfer. |
| `EMPLOYMENT_STATUS` | VARCHAR | `active`, `terminated`, or `transferred`. *Set independently of `TERMINATION_DATE`* — the two do not always agree. |
| `PRIOR_EMPLOYEE_ID` | NUMBER | On a transfer/rehire record, points back to the record it succeeded; null on an original record. |

> A `transferred` record represents an internal move, **not** an exit. A second
> record with the same `PERSON_ID` and an earlier one closed-out usually means a
> rehire (look at the gap between the old `TERMINATION_DATE` and the new
> `HIRE_DATE`) or a transfer (look at `PRIOR_EMPLOYEE_ID`).

### `RAW_DEPARTMENTS` — one row per department
| Column | Type | Description |
|---|---|---|
| `DEPARTMENT_ID` | NUMBER | Unique department identifier. |
| `DEPARTMENT_CODE` | VARCHAR | Short code, e.g. `ENG`, `SAL`. |
| `DEPARTMENT_NAME` | VARCHAR | Human-readable name. |
| `DIVISION` | VARCHAR | Roll-up: `Product & Technology`, `Go-To-Market`, `Operations`. |
| `COST_CENTER` | VARCHAR | Finance cost center the department maps to. |

### `RAW_PERFORMANCE_REVIEWS` — one row per review
| Column | Type | Description |
|---|---|---|
| `REVIEW_ID` | NUMBER | Unique review identifier. |
| `EMPLOYEE_ID` | NUMBER | The employment record reviewed. |
| `PERSON_ID` | NUMBER | The person reviewed (stable across records). |
| `REVIEW_PERIOD` | NUMBER | The review cycle year. |
| `RATING` | VARCHAR | `outstanding`, `exceeds`, `meets`, `below`. |
| `REVIEW_SCORE` | NUMBER(5,2) | Numeric 1.00–5.00. |
| `REVIEWER_ID` | NUMBER | The reviewing manager's id. |
| `REVIEW_DATE` | TIMESTAMP_NTZ | When the review was finalized. **Sometimes null** (cycle-close job failed). |

> The cycle occasionally re-submits a review, producing a duplicate row with a
> new `REVIEW_ID`.

### `RAW_PAYROLL` — one row per employee per monthly pay period
| Column | Type | Description |
|---|---|---|
| `PAYROLL_ID` | NUMBER | Unique payroll line identifier. |
| `EMPLOYEE_ID` | NUMBER | The employment record paid. |
| `PERSON_ID` | NUMBER | The person paid. |
| `PAY_PERIOD` | TIMESTAMP_NTZ | First day of the pay month. |
| `GROSS_PAY` | NUMBER(12,2) | Gross pay for the period, in `CURRENCY`. |
| `CURRENCY` | VARCHAR | `USD`, `GBP`, `EUR`, `SGD` — local payroll, **un-normalized**. |
| `IS_PARTIAL_PERIOD` | BOOLEAN | True when a stint started or ended mid-month (pay is prorated). |
| `PAID_AT` | TIMESTAMP_NTZ | When the run was paid out. |

> A cancelled-and-reissued run produces a duplicate period row for the same
> employee with a new `PAYROLL_ID`.

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `PEOPLECORE` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--employees`; 12k people generates ~14k employee records, ~36k reviews and ~600k payroll lines. `write_pandas` uses Parquet staging so it should still be quick.
