# Data Generator — Cobalt Mobility raw sandbox

This script provisions the five raw operational tables into your Snowflake
sandbox (database `RIDEFLOW`). It simulates a source-system export from a
ride-hailing marketplace: the data is **realistic and deliberately imperfect**.
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
export SNOWFLAKE_DATABASE=RIDEFLOW
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 80,000 trips, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --trips 20000

# Validate generation without touching Snowflake (no connector needed)
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the five tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--trips` always produce identical
> data. Use the default seed so reviewers see the same dataset you modeled against.

Rider count is `trips // 4` and driver count is `trips // 20`, so scaling
`--trips` scales the whole marketplace proportionally.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_RIDERS` — one row per rider account
| Column | Type | Description |
|---|---|---|
| `RIDER_ID` | NUMBER | Unique rider identifier. |
| `HOME_CITY` | VARCHAR | Operating city the rider signed up in: `metro_north`, `bayview`, `rivermouth`, `sunbelt`. |
| `ACCOUNT_STATUS` | VARCHAR | Account state: `active`, `dormant`, `suspended`, `guest`. *This is the CRM flag, not a behavioural measure.* |
| `SIGNUP_AT` | TIMESTAMP_NTZ | When the account was created. Some predate the trip window. |
| `REFERRED_BY` | NUMBER | The referring rider's id, or `NULL` for organic signups. |

### `RAW_DRIVERS` — one row per driver (see note)
| Column | Type | Description |
|---|---|---|
| `DRIVER_ID` | NUMBER | Driver identifier. **Reused across re-onboarding** — see below. |
| `HOME_CITY` | VARCHAR | Operating city. |
| `DRIVER_STATUS` | VARCHAR | `active`, `inactive`, `deactivated`. |
| `RATING` | NUMBER(4,2) | Rolling star rating, 3.0–5.0. |
| `ONBOARDED_AT` | TIMESTAMP_NTZ | When the driver was onboarded. |
| `VEHICLE_CLASS` | VARCHAR | `standard`, `premium`, `xl`. |

> The onboarding service assigns `DRIVER_ID` on first contact and **reuses it if
> a churned driver comes back**, writing a second row with a later `ONBOARDED_AT`.
> The Data Lead believes this table is "one row per driver." Verify that.

### `RAW_TRIPS` — one row per trip request
| Column | Type | Description |
|---|---|---|
| `TRIP_ID` | NUMBER | Unique trip identifier. |
| `RIDER_ID` | NUMBER | The requesting rider. |
| `DRIVER_ID` | NUMBER | The assigned driver. |
| `CITY` | VARCHAR | City the trip was billed in. |
| `PRODUCT` | VARCHAR | `standard`, `pool`, `premium`, `xl`. |
| `TRIP_STATUS` | VARCHAR | `completed` or `cancelled`. |
| `CANCEL_REASON` | VARCHAR | For cancellations: `rider_cancel`, `driver_cancel`, `no_driver_found`, `rider_no_show`. NULL on completed trips. |
| `GROSS_FARE` | NUMBER(12,2) | Fare booked for the trip, in `CURRENCY`. **This is what leadership sums for GMV.** Cancellations can carry a (reduced) fare; some are 0. |
| `SURGE_MULTIPLIER` | NUMBER(5,2) | Surge applied at request time (1.0 = no surge). |
| `CURRENCY` | VARCHAR | `USD` for US cities; `GBP` for `rivermouth`. Un-normalised. |
| `IS_FRAUD_FLAGGED` | BOOLEAN | Trip later flagged by the fraud team (spoofing, collusion, chargeback). The fare is still present. |
| `PICKUP_LAT` / `PICKUP_LON` | NUMBER(9,6) | Pickup coordinates. |
| `DROPOFF_LAT` / `DROPOFF_LON` | NUMBER(9,6) | Dropoff coordinates. |
| `REQUESTED_AT` | TIMESTAMP_NTZ | When the trip was requested. |
| `ACCEPTED_AT` | TIMESTAMP_NTZ | When a driver accepted. *Usually* ≥ `REQUESTED_AT`. |
| `STARTED_AT` | TIMESTAMP_NTZ | Ride start. **NULL on cancelled trips.** |
| `ENDED_AT` | TIMESTAMP_NTZ | Ride end. **NULL on cancelled trips.** |

> Coordinates are provided so you *can* compute trip distance/ETA via a geocoding
> / routing API (OpenRouteService, OSRM) or a haversine fallback. This is a
> **stretch goal**, not required to reconcile the revenue gap.

### `RAW_PAYMENTS` — one row per payment capture *attempt*
| Column | Type | Description |
|---|---|---|
| `PAYMENT_ID` | NUMBER | Unique per attempt. |
| `TRIP_ID` | NUMBER | The trip being charged. |
| `RIDER_ID` | NUMBER | The charged rider. |
| `PAYMENT_STATUS` | VARCHAR | `captured` or `failed`. |
| `AMOUNT` | NUMBER(12,2) | Attempted charge (matches the trip fare). |
| `CURRENCY` | VARCHAR | Charge currency. |
| `PAYMENT_METHOD` | VARCHAR | `card`, `wallet`, `apple_pay`, `cash`. |
| `PROCESSOR_FEE` | NUMBER(12,2) | Processor fee on captured charges; 0 on failures. |
| `ATTEMPTED_AT` | TIMESTAMP_NTZ | When the attempt was made. |
| `CAPTURED_AT` | TIMESTAMP_NTZ | When it settled; NULL for failed attempts. |

> The processor logs **every** capture attempt, including retries after a
> declined card. There are no payment rows for zero-fare trips.

### `RAW_DRIVER_INCENTIVES` — one row per incentive line
| Column | Type | Description |
|---|---|---|
| `INCENTIVE_ID` | NUMBER | Unique incentive line identifier. |
| `DRIVER_ID` | NUMBER | Driver credited. |
| `TRIP_ID` | NUMBER | The qualifying trip. |
| `CAMPAIGN` | VARCHAR | `quest_weekly`, `surge_guarantee`, `referral_bonus`, `consecutive_trips`, `peak_hour_boost`. |
| `BONUS_AMOUNT` | NUMBER(12,2) | Bonus credited on this line. |
| `CURRENCY` | VARCHAR | Bonus currency. |
| `EARNED_AT` | TIMESTAMP_NTZ | When the qualifying trip ended. |
| `PAID_AT` | TIMESTAMP_NTZ | When the weekly batch paid it. **Often a later month than `EARNED_AT`.** |

> Payouts run as a weekly batch and write **one line per campaign a trip
> qualified for**. Because campaigns overlap, a single trip can appear on more
> than one incentive line. The Data Lead assumes "incentive spend per trip" is
> just a sum — check whether that double-counts.

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `RIDEFLOW` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--trips`; 80k trips generates ~78k payment rows and ~29k incentive rows. `write_pandas` uses Parquet staging so it should still be quick.
