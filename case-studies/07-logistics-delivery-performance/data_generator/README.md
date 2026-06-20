# Data Generator — Cartwright Freightways raw sandbox

This script provisions the four raw operational tables into your Snowflake
sandbox. It simulates a source-system export from a regional carrier's delivery
network: the data is **realistic and deliberately imperfect**. Cleaning it,
reconciling the on-time numbers, and standing up an SLA framework is the
engagement.

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
export SNOWFLAKE_DATABASE=HAULPOINT
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 50,000 orders, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --orders 10000

# Validate generation without touching Snowflake (no connector needed)
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the four tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--orders` always produce identical
> data. Use the default seed so reviewers see the same dataset you modeled against.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_WAREHOUSES` — one row per origin distribution center (master data)
| Column | Type | Description |
|---|---|---|
| `WAREHOUSE_ID` | NUMBER | Unique warehouse identifier. |
| `WAREHOUSE_NAME` | VARCHAR | Human-readable DC name. |
| `REGION` | VARCHAR | Operating region: `northeast`, `midwest`, `south`, `west`. |
| `TIMEZONE` | VARCHAR | IANA timezone of the DC (e.g. `America/Chicago`). |
| `LATITUDE` | NUMBER(9,5) | DC latitude. *(For the optional distance/ETA stretch goal.)* |
| `LONGITUDE` | NUMBER(9,5) | DC longitude. *(For the optional distance/ETA stretch goal.)* |
| `OPENED_AT` | TIMESTAMP_NTZ | When the DC opened. |

### `RAW_DRIVERS` — one row per driver-employment record
| Column | Type | Description |
|---|---|---|
| `DRIVER_ID` | NUMBER | Unique per employment record. |
| `DRIVER_NAME` | VARCHAR | Driver's name. *Not* a unique key — the same person can be rehired under a new `DRIVER_ID`. |
| `HOME_REGION` | VARCHAR | The driver's home operating region. |
| `EMPLOYMENT_STATUS` | VARCHAR | `active` or `terminated`. |
| `HIRED_AT` | TIMESTAMP_NTZ | Start of this employment record. |
| `TERMINATED_AT` | TIMESTAMP_NTZ | End of this record; null while active. |

> Drivers churn and get rehired. A rehire is a **new row with a new `DRIVER_ID`**
> but the same `DRIVER_NAME`. If you key driver metrics off the name you'll merge
> two stints; if you key off the id you'll split one person. Decide deliberately.

### `RAW_ORDERS` — one row per order
| Column | Type | Description |
|---|---|---|
| `ORDER_ID` | NUMBER | Unique order identifier. |
| `CUSTOMER_ID` | NUMBER | The purchasing customer. |
| `ORIGIN_WAREHOUSE_ID` | NUMBER | DC the order ships from (→ `RAW_WAREHOUSES`). |
| `DEST_REGION` | VARCHAR | Destination region. |
| `SERVICE_LEVEL` | VARCHAR | `economy`, `standard`, `express` — sets the promised transit time. |
| `PACKAGE_WEIGHT_KG` | NUMBER(10,2) | Billable weight. |
| `PROMISED_DELIVERY_AT` | TIMESTAMP_NTZ | The delivery window the customer was quoted at checkout. **This is the SLA clock.** |
| `CREATED_AT` | TIMESTAMP_NTZ | When the order was placed. |

> `PROMISED_DELIVERY_AT` is derived from the order date plus the service level's
> promised transit days (economy 6, standard 3, express 1). On-time is measured
> against *this* column.

### `RAW_DELIVERIES` — one row per delivery event
| Column | Type | Description |
|---|---|---|
| `DELIVERY_ID` | NUMBER | Unique per delivery event. |
| `ORDER_ID` | NUMBER | The order being delivered (→ `RAW_ORDERS`). |
| `DRIVER_ID` | NUMBER | The delivering driver (→ `RAW_DRIVERS`). |
| `CARRIER` | VARCHAR | Carrier/feed that reported the event. |
| `DELIVERY_STATUS` | VARCHAR | `delivered` (completed) or `failed` (attempt that never completed). |
| `FAILURE_REASON` | VARCHAR | Why a `failed` delivery failed; null for completed deliveries. |
| `PICKED_UP_AT` | TIMESTAMP_NTZ | When the parcel left the DC. |
| `DELIVERED_AT` | TIMESTAMP_NTZ | When it was delivered. **Sometimes null** — a carrier feed dropped out and never reported the final scan. |
| `ATTEMPTED_AT` | TIMESTAMP_NTZ | Last delivery-attempt timestamp. |

> The delivery feed is stitched from several carrier APIs. Honestly, it's the
> messiest table. Most orders have one row; some show up **twice** (two feeds
> reported the same physical delivery), and a meaningful slice have a **missing
> `DELIVERED_AT`** even though the parcel status says it was delivered.

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `HAULPOINT` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--orders`; 50k orders generates ~51k delivery rows. `write_pandas` uses Parquet staging so it should still be quick.

## Optional stretch goal — distance / ETA enrichment

`RAW_WAREHOUSES` carries real-ish `LATITUDE`/`LONGITUDE`, and orders carry a
`DEST_REGION`. If you want to enrich the mart with haversine distance or call a
geocoding/routing API to estimate expected transit time per lane, the
coordinates are there. **This is entirely optional** — the generator and the
core engagement stand alone without it.
