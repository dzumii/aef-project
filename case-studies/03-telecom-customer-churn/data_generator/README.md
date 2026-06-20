# Data Generator — Northwind Cellular raw sandbox

This script provisions the five raw operational tables into your Snowflake
sandbox. It simulates a carrier source-system export: the data is **realistic
and deliberately imperfect**. Cleaning and reconciling it is the engagement.

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
export SNOWFLAKE_DATABASE=TELCO_CORE
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 40,000 subscriber lines, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --subscribers 10000

# Validate generation without touching Snowflake
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the five tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--subscribers` always produce
> identical data. Use the default seed so reviewers see the same dataset you
> modeled against.

> **Observation date.** The simulated teams all run their churn reports as-of
> **2024-12-31**. The trailing-30-day-no-usage and payment-lapse definitions are
> only comparable if you evaluate them as-of this same date. Build your mart to a
> fixed observation date, not "today."

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_SUBSCRIBERS` — one row per subscriber line
| Column | Type | Description |
|---|---|---|
| `SUBSCRIBER_ID` | NUMBER | Subscriber line identifier. *Should* be unique — confirm it. |
| `PLAN_CODE` | VARCHAR | The line's plan; joins to `RAW_PLANS`. |
| `REGION` | VARCHAR | `north`, `south`, `east`, `west`, `central`. |
| `ACCOUNT_STATUS` | VARCHAR | Billing system's current view: `active` or `cancelled`. |
| `AUTOPAY_ENROLLED` | BOOLEAN | Whether the line is on autopay. |
| `DISCONNECT_REASON` | VARCHAR | For cancelled lines: `voluntary`, `involuntary` (carrier-initiated for non-payment), or `ported_out`. Null for active lines. |
| `ACTIVATED_AT` | TIMESTAMP_NTZ | When the line was activated. |
| `CANCELLED_AT` | TIMESTAMP_NTZ | When the line was cancelled; null for active lines. |

> The same `SUBSCRIBER_ID` can appear more than once after a SIM swap / account
> migration — same id, different `ACTIVATED_AT`, occasionally a conflicting
> `ACCOUNT_STATUS`.

### `RAW_PLANS` — one row per plan
| Column | Type | Description |
|---|---|---|
| `PLAN_CODE` | VARCHAR | Plan identifier. |
| `PLAN_TYPE` | VARCHAR | `prepaid` or `postpaid`. |
| `MONTHLY_RECURRING_CHARGE` | NUMBER(12,2) | Postpaid monthly charge / prepaid nominal tier price. |
| `DATA_ALLOWANCE_GB` | NUMBER | Included data allowance. |
| `CONTRACT_MONTHS` | NUMBER | 0 for prepaid; 24 for postpaid. |

### `RAW_USAGE` — one row per daily usage-mediation record
| Column | Type | Description |
|---|---|---|
| `USAGE_ID` | NUMBER | Unique per mediation record. |
| `SUBSCRIBER_ID` | NUMBER | The line that generated the usage. |
| `USAGE_TYPE` | VARCHAR | `voice` (minutes), `data` (GB), `sms` (messages). |
| `USAGE_UNITS` | NUMBER(14,3) | Quantity, in the unit implied by `USAGE_TYPE`. |
| `USAGE_DATE` | TIMESTAMP_NTZ | When the usage occurred. |

> The mediation pipeline occasionally **replays a batch**, producing duplicate
> records: same subscriber / day / units / type, new `USAGE_ID`.

### `RAW_SUPPORT_TICKETS` — one row per support contact
| Column | Type | Description |
|---|---|---|
| `TICKET_ID` | NUMBER | Unique ticket identifier. |
| `SUBSCRIBER_ID` | NUMBER | The line that contacted support. |
| `CATEGORY` | VARCHAR | `billing`, `network`, `device`, `plan_change`, `retention`, `porting`. |
| `CHANNEL` | VARCHAR | `phone`, `chat`, `store`, `app`, `email`. |
| `OPENED_AT` | TIMESTAMP_NTZ | When the ticket was opened. |
| `RESOLVED_AT` | TIMESTAMP_NTZ | When it was resolved. **Sometimes null** (still open / feed gap). |

### `RAW_PAYMENTS` — one row per billing charge / top-up
| Column | Type | Description |
|---|---|---|
| `PAYMENT_ID` | NUMBER | Unique per charge attempt. |
| `SUBSCRIBER_ID` | NUMBER | The billed line. |
| `BILLING_PERIOD` | VARCHAR | `YYYY-MM` the charge belongs to. |
| `AMOUNT_DUE` | NUMBER(12,2) | Charge amount. |
| `PAYMENT_STATUS` | VARCHAR | `paid`, `past_due`, or `failed`. |
| `PAYMENT_METHOD` | VARCHAR | `card`, `direct_debit`, `wallet`, `bank_transfer`. |
| `DUE_AT` | TIMESTAMP_NTZ | When the charge was due. |
| `PAID_AT` | TIMESTAMP_NTZ | When it settled; null for `past_due`/`failed`. |

> Postpaid lines emit one row per monthly charge; prepaid lines emit one row per
> top-up (variable amount). A `failed` charge is sometimes **retried** and a
> later `paid` row settles the same `BILLING_PERIOD` — use the *latest* outcome
> per period, not the first row you find.

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `TELCO_CORE` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--subscribers`; 40k subscribers generates ~800k+ usage rows. `write_pandas` uses Parquet staging so it should still be quick.
