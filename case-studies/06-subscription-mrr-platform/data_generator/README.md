# Data Generator — StreamNine raw sandbox

This script provisions the five raw operational tables into your Snowflake
sandbox. It simulates a source-system export from a subscription billing and
product stack: the data is **realistic and deliberately imperfect**. Cleaning
it and settling on a single MRR definition is the engagement.

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
export SNOWFLAKE_DATABASE=STREAMNINE
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 40,000 subscribers, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --users 10000

# Validate generation without touching Snowflake
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the five tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--users` always produce identical
> data. Use the default seed so reviewers see the same dataset you modeled against.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_PLANS` — one row per plan in the catalogue (static reference)
| Column | Type | Description |
|---|---|---|
| `PLAN_ID` | NUMBER | Unique plan identifier. |
| `PLAN_CODE` | VARCHAR | Short code: `FREE`, `BASIC`, `STANDARD`, `PLUS`, `PREMIUM`, `FAMILY`. |
| `PLAN_NAME` | VARCHAR | Display name. |
| `TIER_RANK` | NUMBER | Ordering of tiers; `0` is the free tier, higher = more premium. |
| `MONTHLY_PRICE` | NUMBER(12,2) | List **monthly** price in `CURRENCY`. Annual plans bill 12× this. |
| `CURRENCY` | VARCHAR | Catalogue currency (`USD`). |

### `RAW_USERS` — one row per subscriber (current state)
| Column | Type | Description |
|---|---|---|
| `USER_ID` | NUMBER | Unique subscriber identifier. |
| `PLAN_ID` | NUMBER | The subscriber's **current** plan (FK to `RAW_PLANS`). |
| `SUBSCRIPTION_STATUS` | VARCHAR | Current lifecycle state: `active`, `paused`, `past_due`, `cancelled`. |
| `BILLING_INTERVAL` | VARCHAR | `monthly` or `annual`. |
| `CURRENCY` | VARCHAR | Mostly `USD`; some `EUR`/`GBP`. |
| `SIGNUP_AT` | TIMESTAMP_NTZ | When the subscription started. |
| `PAUSED_AT` | TIMESTAMP_NTZ | When the subscription was paused; null if never paused. |
| `CANCELLED_AT` | TIMESTAMP_NTZ | When it was cancelled; null if not cancelled. *Not always cleared on re-activation.* |

> `paused` means billing is suspended but the seat is retained — the subscriber
> can resume. Whether a paused subscriber counts toward MRR is **a definitional
> choice, not a given**.

### `RAW_PAYMENTS` — one row per billing charge *attempt*
| Column | Type | Description |
|---|---|---|
| `PAYMENT_ID` | NUMBER | Unique per attempt. |
| `USER_ID` | NUMBER | The subscriber being billed. |
| `PLAN_ID` | NUMBER | Plan the charge was raised under. |
| `PAYMENT_STATUS` | VARCHAR | `succeeded` or `failed`. |
| `AMOUNT` | NUMBER(12,2) | Charge amount. **Proration charges are partial; credits are negative.** |
| `CHARGE_TYPE` | VARCHAR | `renewal`, `proration` (upgrade catch-up), `proration_credit` (downgrade credit). |
| `CURRENCY` | VARCHAR | Charge currency. |
| `BILLING_INTERVAL` | VARCHAR | `monthly` or `annual` (annual renewals bill 12×). |
| `PAYMENT_METHOD` | VARCHAR | `card`, `paypal`, `apple_pay`. |
| `GATEWAY_FEE` | NUMBER(12,2) | Processor fee on succeeded charges; 0 on failures. |
| `ATTEMPTED_AT` | TIMESTAMP_NTZ | When the attempt was made. |
| `PROCESSED_AT` | TIMESTAMP_NTZ | When it settled; null for failed attempts. |

> The billing system logs **every** attempt, including retries after a declined card.

### `RAW_UPGRADES` — one row per upgrade event (move to a higher tier)
| Column | Type | Description |
|---|---|---|
| `UPGRADE_ID` | NUMBER | Unique upgrade identifier. |
| `USER_ID` | NUMBER | Subscriber who upgraded. |
| `FROM_PLAN_ID` / `TO_PLAN_ID` | NUMBER | Plans moved between (FK to `RAW_PLANS`). |
| `FROM_PRICE` / `TO_PRICE` | NUMBER(12,2) | Monthly list prices at the time of the move. |
| `PRORATION_AMOUNT` | NUMBER(12,2) | Pro-rated catch-up charge for the remainder of the current cycle. |
| `DAYS_INTO_CYCLE` | NUMBER | How far into the 30-day cycle the upgrade happened. |
| `CURRENCY` | VARCHAR | Event currency. |
| `EFFECTIVE_AT` | TIMESTAMP_NTZ | When the new plan took effect. |
| `CREATED_AT` | TIMESTAMP_NTZ | When the event was written. |

### `RAW_DOWNGRADES` — one row per downgrade event (move to a lower tier)
| Column | Type | Description |
|---|---|---|
| `DOWNGRADE_ID` | NUMBER | Unique downgrade identifier. |
| `USER_ID` | NUMBER | Subscriber who downgraded. |
| `FROM_PLAN_ID` / `TO_PLAN_ID` | NUMBER | Plans moved between (FK to `RAW_PLANS`). |
| `FROM_PRICE` / `TO_PRICE` | NUMBER(12,2) | Monthly list prices at the time of the move. |
| `PRORATION_AMOUNT` | NUMBER(12,2) | Pro-rated **credit** (negative) for immediate downgrades; `0` for scheduled. |
| `DAYS_INTO_CYCLE` | NUMBER | Cycle position for immediate downgrades; null for scheduled. |
| `CHANGE_TYPE` | VARCHAR | `immediate` (cuts MRR this cycle, with credit) or `scheduled` (next cycle). |
| `CURRENCY` | VARCHAR | Event currency. |
| `EFFECTIVE_AT` | TIMESTAMP_NTZ | When the lower plan takes / took effect. |
| `CREATED_AT` | TIMESTAMP_NTZ | When the event was written. |

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `STREAMNINE` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--users`; 40k subscribers generates ~200k payment rows. `write_pandas` uses Parquet staging so it should still be quick.
