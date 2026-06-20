# Data Generator — GlobeMart raw sandbox

This script provisions the four raw operational tables into your Snowflake
sandbox. It simulates a source-system export from a retail chain operating
across eight countries: the data is **realistic and deliberately imperfect**.
Cleaning, currency-normalising, and consolidating it is the engagement.

**Every monetary value is in local currency. There is no USD column.** The
conversion rates you need are not reliably in the warehouse — you must pull them
from a free FX API (see "FX rate workflow" below).

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
export SNOWFLAKE_DATABASE=GLOBEMART
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 60,000 sales rows, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --rows 10000

# Validate generation without touching Snowflake
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the four tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--rows` always produce identical
> data. Use the default seed so reviewers see the same dataset you modeled against.

---

## FX rate workflow (REQUIRED — read this)

The `RAW_CURRENCY_RATES` table in the warehouse is **deliberately partial and not
trustworthy**: it covers only part of the year, only some currencies, has no
weekend rows, and contains a few inverted values. You are expected to source
authoritative historical daily rates from a **free, keyless FX API** and build
your own rate layer.

### Pick an API (no key required)

- **Frankfurter** — ECB reference rates. Historical daily endpoint:
  ```
  https://api.frankfurter.app/2024-03-15?from=USD&to=GBP,EUR,JPY,CAD,AUD,INR,BRL
  ```
  A date range in one call:
  ```
  https://api.frankfurter.app/2024-01-01..2024-12-31?from=USD&to=GBP,EUR,JPY,CAD,AUD,INR,BRL
  ```
- **exchangerate.host** — similar historical/time-series endpoints, also keyless.

Both return rates as **target-currency per 1 USD** (e.g. `GBP: 0.79` means 0.79
GBP buys what 1 USD buys). To convert a local sale to USD:
`amount_usd = local_amount / rate_local_per_usd`.

### The decisions the API forces on you

1. **Which day's rate?** Each sale has a `SOLD_AT` (local wall-clock) and a
   `BOOKED_AT`. Transaction-date, booking-date, month-end, and a fixed budget
   rate each produce a *different consolidated USD total* — the spread is the
   point of the engagement. Decide and document.
2. **Weekends & holidays.** Frankfurter/ECB publish on trading days only — there
   is **no rate for Saturdays, Sundays, or market holidays** (~30% of calendar
   days). A sale on those days has no exact-date rate. Carry forward the last
   published rate (recommended), carry back, or interpolate — but never drop the
   sale or null its USD value silently.
3. **Backfill the full year.** Pull every trading day in the window once, then
   forward-fill to a complete daily calendar so every possible `SOLD_AT` date
   resolves to a rate for all eight currencies.
4. **Incremental & idempotent.** In a daily pipeline, fetch only new dates since
   the last successful pull, upsert by `(currency, rate_date)`, and never mutate
   historical rates. Re-running must not duplicate rows or change past conversions.
5. **Materialise, don't fetch live.** Land the API rates into the warehouse (a dbt
   seed, a staged table, or a small loader) so your marts are reproducible and
   don't depend on the API being up at query time.

### Use `RAW_CURRENCY_RATES` only as a cross-check
It can value only CAD/EUR/GBP/JPY, stops mid-year, and has a few inverted rows.
Comparing your API rates against it (where they overlap) is a good sanity test —
relying on it as your primary source is a failing approach.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_SALES` — one row per sale
| Column | Type | Description |
|---|---|---|
| `SALE_ID` | NUMBER | Unique per sale row. *Usually* unique — re-rung terminal re-syncs can repeat a sale under a new id. |
| `STORE_ID` | NUMBER | The store where the sale occurred (FK to `RAW_STORES`). |
| `PRODUCT_CATEGORY` | VARCHAR | `apparel`, `home`, `electronics`, `beauty`, `grocery`, `toys`. |
| `CHANNEL` | VARCHAR | `in_store` or `online`. |
| `PAYMENT_METHOD` | VARCHAR | `card`, `cash`, `mobile_wallet`. |
| `QUANTITY` | NUMBER | Units in the sale. |
| `LOCAL_AMOUNT` | NUMBER(18,2) | Sale total **in the store's local currency**. No USD column exists. |
| `LOCAL_CURRENCY` | VARCHAR | One of `USD`, `GBP`, `EUR`, `JPY`, `CAD`, `AUD`, `INR`, `BRL`. |
| `SALE_STATUS` | VARCHAR | `completed`, `returned` (revenue reversed), or `voided` (cancelled at till). |
| `SOLD_AT` | TIMESTAMP_NTZ | When the sale rang up — **store-local wall clock, no offset stored. Sometimes null** (dropped in integration). |
| `BOOKED_AT` | TIMESTAMP_NTZ | When the sale hit the accounting system. **Sometimes a later month than `SOLD_AT`.** |

### `RAW_STORES` — one row per store
| Column | Type | Description |
|---|---|---|
| `STORE_ID` | NUMBER | Unique store identifier. |
| `STORE_NAME` | VARCHAR | Display name. |
| `COUNTRY` | VARCHAR | One of the eight operating countries. |
| `LOCAL_CURRENCY` | VARCHAR | The store's booking currency. |
| `TIMEZONE` | VARCHAR | IANA timezone (e.g. `Asia/Tokyo`). Use this to interpret `SOLD_AT` if you normalise to UTC. |
| `REPORTING_CALENDAR` | VARCHAR | `gregorian` (most) or `retail_445` (a few legacy stores close on a 4-4-5 retail calendar). |
| `OPENED_AT` | TIMESTAMP_NTZ | Store open date. |

### `RAW_INVENTORY` — one row per store × category × snapshot
| Column | Type | Description |
|---|---|---|
| `SNAPSHOT_ID` | NUMBER | Unique snapshot row. |
| `STORE_ID` | NUMBER | The store (FK to `RAW_STORES`). |
| `PRODUCT_CATEGORY` | VARCHAR | Stock category. |
| `UNITS_ON_HAND` | NUMBER | Units in stock at the snapshot. |
| `LOCAL_UNIT_COST` | NUMBER(18,2) | Unit cost **in local currency**. Stock value = `UNITS_ON_HAND × LOCAL_UNIT_COST`, in local currency — same FX problem as sales. |
| `LOCAL_CURRENCY` | VARCHAR | The store's currency. |
| `SNAPSHOT_DATE` | DATE | Snapshot date (~monthly). |

### `RAW_CURRENCY_RATES` — one row per currency × date (PARTIAL, do not trust)
| Column | Type | Description |
|---|---|---|
| `RATE_ID` | NUMBER | Unique rate row. |
| `CURRENCY` | VARCHAR | Currency the rate is for. **Only CAD/EUR/GBP/JPY are present — AUD/INR/BRL are absent.** |
| `RATE_DATE` | DATE | The rate's date. **Coverage stops mid-year; no weekend rows; weekday gaps.** |
| `RATE_TO_USD` | NUMBER(18,6) | Intended as local-units-per-USD. **A few rows are inverted** (USD-per-local). |
| `SOURCE` | VARCHAR | `legacy_spreadsheet`. |

> This table exists so you can practice cross-checking — it is **not** a
> sufficient rate source. Pull the real history from the API (see above).

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `GLOBEMART` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--rows`; 60k sales generates ~60k rows plus small dimension tables. `write_pandas` uses Parquet staging so it should still be quick.
- **FX API rate-limited / down** — Frankfurter and exchangerate.host are free and occasionally throttle. Pull the full-year range once, cache to a seed/table, and have your orchestration fall back to the last successful pull (this is part of the orchestration design you're graded on).
