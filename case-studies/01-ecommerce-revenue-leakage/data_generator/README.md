# Data Generator — Lumen & Loom raw sandbox

This script provisions the four raw operational tables into your Snowflake
sandbox. It simulates a source-system export: the data is **realistic and
deliberately imperfect**. Cleaning and reconciling it is the engagement.

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
export SNOWFLAKE_DATABASE=LUMEN_LOOM
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 50,000 orders, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --orders 10000

# Validate generation without touching Snowflake
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

### `RAW_ORDERS` — one row per order
| Column | Type | Description |
|---|---|---|
| `ORDER_ID` | NUMBER | Unique order identifier. |
| `CUSTOMER_ID` | NUMBER | The purchasing customer. |
| `ORDER_STATUS` | VARCHAR | Current lifecycle state: `placed`, `confirmed`, `completed`, `cancelled`. |
| `ORDER_AMOUNT` | NUMBER(12,2) | Order total at placement, in `CURRENCY`. |
| `CURRENCY` | VARCHAR | Mostly `USD`; some `EUR`/`GBP`. |
| `CREATED_AT` | TIMESTAMP_NTZ | When the order was placed. |
| `UPDATED_AT` | TIMESTAMP_NTZ | Last status change. *Usually* ≥ `CREATED_AT`. |

### `RAW_PAYMENTS` — one row per payment *attempt*
| Column | Type | Description |
|---|---|---|
| `PAYMENT_ID` | NUMBER | Unique per attempt. |
| `ORDER_ID` | NUMBER | The order being paid for. |
| `PAYMENT_STATUS` | VARCHAR | `succeeded` or `failed`. |
| `AMOUNT` | NUMBER(12,2) | Attempted charge. |
| `CURRENCY` | VARCHAR | Charge currency. |
| `PAYMENT_METHOD` | VARCHAR | `card`, `paypal`, `apple_pay`, `bank_transfer`. |
| `GATEWAY_FEE` | NUMBER(12,2) | Processor fee on succeeded charges; 0 on failures. |
| `ATTEMPTED_AT` | TIMESTAMP_NTZ | When the attempt was made. |
| `PROCESSED_AT` | TIMESTAMP_NTZ | When it settled; null for failed attempts. |

> The gateway logs **every** attempt, including retries after a declined card.

### `RAW_REFUNDS` — one row per refund
| Column | Type | Description |
|---|---|---|
| `REFUND_ID` | NUMBER | Unique refund identifier. |
| `ORDER_ID` | NUMBER | Order being refunded. |
| `PAYMENT_ID` | NUMBER | The payment the refund applies to. |
| `REFUND_AMOUNT` | NUMBER(12,2) | Amount refunded; **can be partial**. |
| `CURRENCY` | VARCHAR | Refund currency. |
| `REFUND_REASON` | VARCHAR | `damaged`, `wrong_item`, `changed_mind`, `late_delivery`, `not_as_described`. |
| `REFUND_STATUS` | VARCHAR | `completed`. |
| `REQUESTED_AT` | TIMESTAMP_NTZ | When the refund was requested. |
| `PROCESSED_AT` | TIMESTAMP_NTZ | When it settled. **Often a later month than the order.** |

### `RAW_SHIPPING` — one row per shipment
| Column | Type | Description |
|---|---|---|
| `SHIPMENT_ID` | NUMBER | Unique shipment identifier. |
| `ORDER_ID` | NUMBER | Order being shipped. |
| `CARRIER` | VARCHAR | Fulfilment carrier. |
| `SHIPPING_COST` | NUMBER(12,2) | Cost to ship. |
| `STATUS` | VARCHAR | `delivered` or `in_transit`. |
| `SHIPPED_AT` | TIMESTAMP_NTZ | Dispatch time. **Sometimes null** (carrier API timeout). |
| `DELIVERED_AT` | TIMESTAMP_NTZ | Delivery time. **Sometimes null.** |

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `LUMEN_LOOM` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--orders`; 50k orders generates ~70–90k payment rows. `write_pandas` uses Parquet staging so it should still be quick.
