#!/usr/bin/env python3
"""
Cobalt Mobility — source-system data export simulator.

Provisions the five raw operational tables (RIDERS, DRIVERS, TRIPS, PAYMENTS,
DRIVER_INCENTIVES) into a Snowflake sandbox. This emulates the messy, as-emitted
feed from the marketplace's production systems: cancelled trips that still moved
money, retried payment captures, fraud-flagged rides, and an incentives ledger
that double-books bonuses across overlapping campaigns.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --trips 80000 --seed 42

Credentials are read from environment variables (see requirements.txt / README):
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

Pickup/dropoff coordinates are emitted so the distance/ETA enrichment stretch
goal is possible (OpenRouteService / OSRM, or a haversine fallback). Nothing
about the data flaws is documented here on purpose — this is meant to read like
a real operational export. Fellows: your job is to find what's wrong.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# snowflake.connector is imported lazily inside get_connection() / load_to_snowflake()
# so that `--dry-run` works without the connector installed (e.g. for quick validation).


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# The simulated marketplace operates over this window. Keep it spanning month
# boundaries so the cross-period accounting problems are exercised.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

# A few operating cities, each with an approximate centre coordinate. Trips are
# scattered around these centres so a real geocoding/distance API (or haversine)
# can recover plausible trip distances.
CITIES = {
    "metro_north":  (40.7580, -73.9855),   # dense urban core
    "bayview":      (37.7749, -122.4194),
    "rivermouth":   (51.5074,  -0.1278),    # note: a non-USD market
    "sunbelt":      (33.4484, -112.0740),
}
CITY_CURRENCY = {
    "metro_north": "USD",
    "bayview":     "USD",
    "rivermouth":  "GBP",   # un-normalised; reported in local currency
    "sunbelt":     "USD",
}

PAYMENT_METHODS = ["card", "card", "card", "wallet", "apple_pay", "cash"]
TRIP_PRODUCTS = ["standard", "standard", "standard", "pool", "premium", "xl"]
CANCEL_REASONS = ["rider_cancel", "driver_cancel", "no_driver_found", "rider_no_show"]
INCENTIVE_CAMPAIGNS = [
    "quest_weekly", "surge_guarantee", "referral_bonus",
    "consecutive_trips", "peak_hour_boost",
]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_riders(rng, n_riders):
    """One row per rider account. Signup date drives the 'active rider' question."""
    rider_ids = np.arange(10_000, 10_000 + n_riders)
    signup = _random_datetimes(rng, n_riders, START_DATE - timedelta(days=540), END_DATE)
    home_city = rng.choice(list(CITIES.keys()), size=n_riders)

    # Account state as the source system records it. "suspended" riders may still
    # have historical trips; "guest" riders checked out without completing signup.
    account_status = rng.choice(
        ["active", "active", "active", "dormant", "suspended", "guest"],
        size=n_riders,
        p=[0.55, 0.18, 0.07, 0.12, 0.04, 0.04],
    )

    df = pd.DataFrame({
        "RIDER_ID": rider_ids,
        "HOME_CITY": home_city,
        "ACCOUNT_STATUS": account_status,
        "SIGNUP_AT": signup,
        "REFERRED_BY": rng.choice(
            np.append(rider_ids, [-1] * (n_riders * 3)), size=n_riders
        ),
    })
    # REFERRED_BY of -1 means organic; store as NULL-ish sentinel the model must handle.
    df.loc[df["REFERRED_BY"] == -1, "REFERRED_BY"] = None
    return df


def generate_drivers(rng, n_drivers):
    """One row per driver. Drivers churn and are sometimes re-onboarded (new row)."""
    driver_ids = np.arange(20_000, 20_000 + n_drivers)
    onboarded = _random_datetimes(rng, n_drivers, START_DATE - timedelta(days=720), END_DATE)
    home_city = rng.choice(list(CITIES.keys()), size=n_drivers)

    status = rng.choice(
        ["active", "active", "active", "inactive", "deactivated"],
        size=n_drivers,
        p=[0.62, 0.18, 0.06, 0.09, 0.05],
    )
    rating = np.round(np.clip(rng.normal(4.7, 0.25, size=n_drivers), 3.0, 5.0), 2)

    df = pd.DataFrame({
        "DRIVER_ID": driver_ids,
        "HOME_CITY": home_city,
        "DRIVER_STATUS": status,
        "RATING": rating,
        "ONBOARDED_AT": onboarded,
        "VEHICLE_CLASS": rng.choice(["standard", "standard", "premium", "xl"], size=n_drivers),
    })

    # A slice of drivers were re-onboarded after churning: a second row with the
    # SAME driver_id but a later onboarding date. Left in as-emitted by the
    # onboarding service, which assigns the id on first contact and reuses it.
    rehire_idx = rng.choice(n_drivers, size=max(1, n_drivers // 25), replace=False)
    rehires = df.loc[rehire_idx].copy()
    rehires["ONBOARDED_AT"] = [
        o + timedelta(days=int(rng.integers(120, 500))) for o in rehires["ONBOARDED_AT"]
    ]
    rehires["DRIVER_STATUS"] = "active"
    df = pd.concat([df, rehires], ignore_index=True)
    return df


def generate_trips(rng, n_trips, riders, drivers):
    """
    One row per trip request. Includes completed, cancelled, and fraud-flagged
    trips. GMV (gross merchandise value) is the fare booked at request time.

    -- Gap drivers (tune here to move the headline GMV-vs-net gap) -------------
    These three isolated constants are the primary levers on the GMV-to-net
    spread the engagement is about. Raising them widens the gap.
    """
    CANCEL_RATE = 0.165          # share of trips that end cancelled
    CANCEL_BILLED_PROB = 0.55    # share of cancellations that still carried a fare (fee/charge)
    FRAUD_RATE = 0.032           # share of *completed* trips later flagged fraudulent
    # ---------------------------------------------------------------------------

    rider_pool = riders["RIDER_ID"].to_numpy()
    rider_city = riders.set_index("RIDER_ID")["HOME_CITY"].to_dict()
    driver_pool = drivers["DRIVER_ID"].drop_duplicates().to_numpy()
    driver_city = (
        drivers.drop_duplicates(subset=["DRIVER_ID"])
        .set_index("DRIVER_ID")["HOME_CITY"].to_dict()
    )

    trip_ids = np.arange(300_000, 300_000 + n_trips)
    requested = _random_datetimes(rng, n_trips, START_DATE, END_DATE)
    rider_ids = rng.choice(rider_pool, size=n_trips)
    driver_ids = rng.choice(driver_pool, size=n_trips)

    products = rng.choice(TRIP_PRODUCTS, size=n_trips)

    # Status mix: most complete, a meaningful slice cancel.
    is_cancelled = rng.random(n_trips) < CANCEL_RATE
    status = np.where(is_cancelled, "cancelled", "completed")

    rows = []
    for i in range(n_trips):
        tid = int(trip_ids[i])
        rid = int(rider_ids[i])
        # Bill the trip in the rider's home city / currency.
        city = rider_city.get(rid, "metro_north")
        currency = CITY_CURRENCY[city]
        lat0, lon0 = CITIES[city]

        # Pickup/dropoff scattered around the city centre (~ up to ~12km).
        pickup_lat = lat0 + rng.normal(0, 0.04)
        pickup_lon = lon0 + rng.normal(0, 0.04)
        drop_lat = lat0 + rng.normal(0, 0.06)
        drop_lon = lon0 + rng.normal(0, 0.06)

        req_ts = requested[i]
        st = str(status[i])

        # Fare model: base + per-trip lognormal, surge multiplier sometimes.
        base_fare = float(np.round(rng.lognormal(mean=2.45, sigma=0.5), 2))
        surge = float(rng.choice([1.0, 1.0, 1.0, 1.2, 1.5, 2.0],
                                 p=[0.55, 0.15, 0.10, 0.10, 0.06, 0.04]))
        gross_fare = round(np.clip(base_fare * surge, 3.0, 400.0), 2)

        cancel_reason = None
        accepted_ts = req_ts + timedelta(seconds=int(rng.integers(5, 90)))
        started_ts = None
        ended_ts = None
        is_fraud = False

        if st == "cancelled":
            cancel_reason = str(rng.choice(CANCEL_REASONS,
                                           p=[0.42, 0.20, 0.25, 0.13]))
            # Some cancellations still carry a fare: cancellation fee, or the
            # rider was charged because the driver had already arrived.
            if rng.random() < CANCEL_BILLED_PROB and cancel_reason != "no_driver_found":
                # billed cancellation — a (often reduced) fare is recorded
                gross_fare = round(gross_fare * float(rng.uniform(0.20, 0.60)), 2)
            else:
                gross_fare = 0.0
            # cancelled trips have no real ride window
            accepted_ts = req_ts + timedelta(seconds=int(rng.integers(5, 120)))
        else:  # completed
            started_ts = accepted_ts + timedelta(seconds=int(rng.integers(60, 600)))
            duration_min = int(np.clip(rng.normal(16, 8), 3, 90))
            ended_ts = started_ts + timedelta(minutes=duration_min)
            # A slice of completed trips are later flagged fraudulent (GPS
            # spoofing, collusion, payment chargebacks). The fare is still in
            # the trips feed as booked GMV.
            is_fraud = rng.random() < FRAUD_RATE

        rows.append({
            "TRIP_ID": tid,
            "RIDER_ID": rid,
            "DRIVER_ID": int(driver_ids[i]),
            "CITY": city,
            "PRODUCT": str(products[i]),
            "TRIP_STATUS": st,
            "CANCEL_REASON": cancel_reason,
            "GROSS_FARE": float(gross_fare),
            "SURGE_MULTIPLIER": surge,
            "CURRENCY": currency,
            "IS_FRAUD_FLAGGED": bool(is_fraud),
            "PICKUP_LAT": round(pickup_lat, 6),
            "PICKUP_LON": round(pickup_lon, 6),
            "DROPOFF_LAT": round(drop_lat, 6),
            "DROPOFF_LON": round(drop_lon, 6),
            "REQUESTED_AT": req_ts,
            "ACCEPTED_AT": accepted_ts,
            "STARTED_AT": started_ts,
            "ENDED_AT": ended_ts,
        })

    df = pd.DataFrame(rows)

    # Clock skew: a tiny population has ACCEPTED_AT before REQUESTED_AT (mobile
    # client buffered events offline and replayed them out of order).
    skew_idx = rng.choice(len(df), size=max(1, len(df) // 500), replace=False)
    df.loc[skew_idx, "ACCEPTED_AT"] = [
        r - timedelta(minutes=int(rng.integers(1, 30)))
        for r in df.loc[skew_idx, "REQUESTED_AT"]
    ]
    return df


def generate_payments(rng, trips):
    """
    One row per payment capture ATTEMPT against a trip. The processor logs every
    attempt; riders' cards get retried, and settled captures are occasionally
    double-delivered by the webhook. Cancelled-with-fare trips are also captured.
    """
    rows = []
    payment_id = 800_000

    for t in trips.itertuples(index=False):
        # No money moves on a zero-fare cancellation or a no-driver-found.
        if t.GROSS_FARE <= 0:
            continue

        # Failed captures before a success (declined card, then retry).
        n_failed = rng.choice([0, 0, 0, 1, 2], p=[0.72, 0.12, 0.08, 0.06, 0.02])
        base_ts = t.ENDED_AT or t.ACCEPTED_AT
        base_ts = base_ts + timedelta(minutes=int(rng.integers(1, 60)))

        for k in range(int(n_failed)):
            rows.append({
                "PAYMENT_ID": payment_id,
                "TRIP_ID": t.TRIP_ID,
                "RIDER_ID": t.RIDER_ID,
                "PAYMENT_STATUS": "failed",
                "AMOUNT": float(t.GROSS_FARE),
                "CURRENCY": t.CURRENCY,
                "PAYMENT_METHOD": str(rng.choice(PAYMENT_METHODS)),
                "PROCESSOR_FEE": 0.0,
                "ATTEMPTED_AT": base_ts + timedelta(minutes=int(k * rng.integers(1, 20))),
                "CAPTURED_AT": None,
            })
            payment_id += 1

        # A few trips never settle (rider had no valid payment method on file).
        settles = rng.random() < 0.97
        if not settles:
            continue

        fee = float(np.round(t.GROSS_FARE * 0.025 + 0.20, 2))
        cap_ts = base_ts + timedelta(minutes=int((n_failed + 1) * rng.integers(1, 20)))
        success_row = {
            "PAYMENT_ID": payment_id,
            "TRIP_ID": t.TRIP_ID,
            "RIDER_ID": t.RIDER_ID,
            "PAYMENT_STATUS": "captured",
            "AMOUNT": float(t.GROSS_FARE),
            "CURRENCY": t.CURRENCY,
            "PAYMENT_METHOD": str(rng.choice(PAYMENT_METHODS)),
            "PROCESSOR_FEE": fee,
            "ATTEMPTED_AT": cap_ts,
            "CAPTURED_AT": cap_ts + timedelta(seconds=int(rng.integers(1, 120))),
        }
        rows.append(success_row)
        payment_id += 1

        # The processor occasionally double-logs a settled capture (webhook
        # delivered twice). Same trip, same amount, new payment_id.
        if rng.random() < 0.017:
            dup = dict(success_row)
            dup["PAYMENT_ID"] = payment_id
            dup["CAPTURED_AT"] = success_row["CAPTURED_AT"] + timedelta(seconds=int(rng.integers(1, 8)))
            rows.append(dup)
            payment_id += 1

    return pd.DataFrame(rows)


def generate_incentives(rng, trips, drivers):
    """
    One row per incentive line credited to a driver. Bonuses are paid out per
    campaign, but campaigns overlap and the payouts service writes a line per
    campaign a trip qualified for — so a single trip can be paid against more
    than one campaign at once (over-attribution).

    -- Gap driver -------------------------------------------------------------
    """
    INCENTIVE_TRIP_SHARE = 0.34   # share of completed trips that earn some incentive
    DOUBLE_BOOK_PROB = 0.28       # of those, the share paid against a 2nd overlapping campaign
    # ---------------------------------------------------------------------------

    completed = trips[trips["TRIP_STATUS"] == "completed"]
    rows = []
    incentive_id = 600_000

    for t in completed.itertuples(index=False):
        if rng.random() >= INCENTIVE_TRIP_SHARE:
            continue

        # Primary campaign payout: a fraction of the fare or a flat-ish boost.
        bonus = float(np.round(max(1.5, t.GROSS_FARE * rng.uniform(0.10, 0.35)), 2))
        campaign = str(rng.choice(INCENTIVE_CAMPAIGNS))
        # Incentives settle on a weekly batch — often a LATER month than the trip.
        lag_days = int(rng.choice([3, 7, 9, 14, 33], p=[0.18, 0.34, 0.20, 0.18, 0.10]))
        paid_at = t.ENDED_AT + timedelta(days=lag_days)

        rows.append({
            "INCENTIVE_ID": incentive_id,
            "DRIVER_ID": t.DRIVER_ID,
            "TRIP_ID": t.TRIP_ID,
            "CAMPAIGN": campaign,
            "BONUS_AMOUNT": bonus,
            "CURRENCY": t.CURRENCY,
            "EARNED_AT": t.ENDED_AT,
            "PAID_AT": paid_at,
        })
        incentive_id += 1

        # Over-attribution: the same trip qualified for a second, overlapping
        # campaign, so a second payout line is written for it.
        if rng.random() < DOUBLE_BOOK_PROB:
            other = [c for c in INCENTIVE_CAMPAIGNS if c != campaign]
            bonus2 = float(np.round(max(1.0, t.GROSS_FARE * rng.uniform(0.05, 0.20)), 2))
            rows.append({
                "INCENTIVE_ID": incentive_id,
                "DRIVER_ID": t.DRIVER_ID,
                "TRIP_ID": t.TRIP_ID,
                "CAMPAIGN": str(rng.choice(other)),
                "BONUS_AMOUNT": bonus2,
                "CURRENCY": t.CURRENCY,
                "EARNED_AT": t.ENDED_AT,
                "PAID_AT": paid_at + timedelta(days=int(rng.integers(0, 5))),
            })
            incentive_id += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_RIDERS": """
        CREATE OR REPLACE TABLE RAW_RIDERS (
            RIDER_ID       NUMBER(18,0),
            HOME_CITY      VARCHAR,
            ACCOUNT_STATUS VARCHAR,
            SIGNUP_AT      TIMESTAMP_NTZ,
            REFERRED_BY    NUMBER(18,0)
        )""",
    "RAW_DRIVERS": """
        CREATE OR REPLACE TABLE RAW_DRIVERS (
            DRIVER_ID     NUMBER(18,0),
            HOME_CITY     VARCHAR,
            DRIVER_STATUS VARCHAR,
            RATING        NUMBER(4,2),
            ONBOARDED_AT  TIMESTAMP_NTZ,
            VEHICLE_CLASS VARCHAR
        )""",
    "RAW_TRIPS": """
        CREATE OR REPLACE TABLE RAW_TRIPS (
            TRIP_ID          NUMBER(18,0),
            RIDER_ID         NUMBER(18,0),
            DRIVER_ID        NUMBER(18,0),
            CITY             VARCHAR,
            PRODUCT          VARCHAR,
            TRIP_STATUS      VARCHAR,
            CANCEL_REASON    VARCHAR,
            GROSS_FARE       NUMBER(12,2),
            SURGE_MULTIPLIER NUMBER(5,2),
            CURRENCY         VARCHAR,
            IS_FRAUD_FLAGGED BOOLEAN,
            PICKUP_LAT       NUMBER(9,6),
            PICKUP_LON       NUMBER(9,6),
            DROPOFF_LAT      NUMBER(9,6),
            DROPOFF_LON      NUMBER(9,6),
            REQUESTED_AT     TIMESTAMP_NTZ,
            ACCEPTED_AT      TIMESTAMP_NTZ,
            STARTED_AT       TIMESTAMP_NTZ,
            ENDED_AT         TIMESTAMP_NTZ
        )""",
    "RAW_PAYMENTS": """
        CREATE OR REPLACE TABLE RAW_PAYMENTS (
            PAYMENT_ID     NUMBER(18,0),
            TRIP_ID        NUMBER(18,0),
            RIDER_ID       NUMBER(18,0),
            PAYMENT_STATUS VARCHAR,
            AMOUNT         NUMBER(12,2),
            CURRENCY       VARCHAR,
            PAYMENT_METHOD VARCHAR,
            PROCESSOR_FEE  NUMBER(12,2),
            ATTEMPTED_AT   TIMESTAMP_NTZ,
            CAPTURED_AT    TIMESTAMP_NTZ
        )""",
    "RAW_DRIVER_INCENTIVES": """
        CREATE OR REPLACE TABLE RAW_DRIVER_INCENTIVES (
            INCENTIVE_ID  NUMBER(18,0),
            DRIVER_ID     NUMBER(18,0),
            TRIP_ID       NUMBER(18,0),
            CAMPAIGN      VARCHAR,
            BONUS_AMOUNT  NUMBER(12,2),
            CURRENCY      VARCHAR,
            EARNED_AT     TIMESTAMP_NTZ,
            PAID_AT       TIMESTAMP_NTZ
        )""",
}


def get_connection():
    try:
        import snowflake.connector
    except ImportError:
        sys.exit("snowflake-connector-python not installed. Run: pip install -r requirements.txt")

    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing Snowflake env vars: {', '.join(missing)}. See README.md.")

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database=os.environ.get("SNOWFLAKE_DATABASE"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
    )


def load_to_snowflake(conn, tables):
    from snowflake.connector.pandas_tools import write_pandas

    database = os.environ.get("SNOWFLAKE_DATABASE")
    schema = os.environ.get("SNOWFLAKE_SCHEMA", "RAW")
    cur = conn.cursor()
    if database:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        cur.execute(f"USE DATABASE {database}")
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    cur.execute(f"USE SCHEMA {schema}")

    for name, df in tables.items():
        print(f"  → {name}: {len(df):,} rows")
        cur.execute(DDL[name])
        # Snowflake stores NULLs from NaT/None correctly via write_pandas/Parquet.
        success, _, nrows, _ = write_pandas(
            conn, df, name, quote_identifiers=False, auto_create_table=False
        )
        if not success:
            sys.exit(f"Load failed for {name}")
    cur.close()


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def build_tables(rng, n_trips):
    """Generate all five dataframes. Factored out so it can be imported and
    validated without touching Snowflake."""
    n_riders = max(2, n_trips // 4)
    n_drivers = max(2, n_trips // 20)

    riders = generate_riders(rng, n_riders)
    drivers = generate_drivers(rng, n_drivers)
    trips = generate_trips(rng, n_trips, riders, drivers)
    payments = generate_payments(rng, trips)
    incentives = generate_incentives(rng, trips, drivers)

    return {
        "RAW_RIDERS": riders,
        "RAW_DRIVERS": drivers,
        "RAW_TRIPS": trips,
        "RAW_PAYMENTS": payments,
        "RAW_DRIVER_INCENTIVES": incentives,
    }


def main():
    ap = argparse.ArgumentParser(description="Provision the Cobalt Mobility raw sandbox.")
    ap.add_argument("--trips", type=int, default=80_000, help="number of trips to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (trips={args.trips:,}, seed={args.seed}) ...")
    tables = build_tables(rng, args.trips)

    print("\nRow counts:")
    for name, df in tables.items():
        print(f"  {name:<22} {len(df):>10,}")

    if args.dry_run:
        print("\n--dry-run set: skipping Snowflake load.")
        return

    print("\nLoading to Snowflake ...")
    conn = get_connection()
    try:
        load_to_snowflake(conn, tables)
    finally:
        conn.close()
    print("\nDone. Raw tables are live in your sandbox. Happy modeling.")


if __name__ == "__main__":
    main()
