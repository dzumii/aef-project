#!/usr/bin/env python3
"""
Cartwright Freightways — source-system data export simulator.

Provisions the four raw operational tables (ORDERS, WAREHOUSES, DRIVERS,
DELIVERIES) into a Snowflake sandbox. This emulates the messy, as-emitted feed
from the carrier's production systems: orders with promised delivery windows, a
driver roster that has churned and been rehired, warehouse master data, and a
delivery-event feed stitched together from multiple carrier APIs — so it has
duplicate scan events, partial / incomplete deliveries, and missing delivery
timestamps when a carrier feed drops out.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --orders 50000 --seed 42

Credentials are read from environment variables (see requirements.txt / README):
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

Nothing about the data flaws is documented here on purpose — this is meant to
read like a real operational export. Fellows: your job is to find what's wrong.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# snowflake.connector is imported lazily inside get_connection() / load functions
# so that `--dry-run` works without the connector installed (quick validation).


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# The simulated network operates over this window. Keep it spanning month
# boundaries so the monthly SLA-reporting problem is exercised.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

SERVICE_LEVELS = ["standard", "standard", "standard", "express", "express", "economy"]
# Promised transit days by service level (the SLA clock the customer was sold).
PROMISED_DAYS = {"economy": 6, "standard": 3, "express": 1}

REGIONS = ["northeast", "midwest", "south", "west"]
CARRIERS = ["linehaul_a", "linehaul_b", "regional_x", "regional_y"]
FAILURE_REASONS = ["address_not_found", "customer_absent", "refused", "damaged_in_transit", "access_restricted"]
TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]

# Rough warehouse coordinates (optional geocoding / distance stretch goal). One
# anchor coordinate per region; warehouses jitter around their region anchor.
REGION_ANCHORS = {
    "northeast": (40.71, -74.01),   # NYC
    "midwest": (41.88, -87.63),     # Chicago
    "south": (29.76, -95.37),       # Houston
    "west": (34.05, -118.24),       # Los Angeles
}


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_warehouses(rng, n_warehouses=12):
    """One row per origin warehouse (master data). Small, slowly-changing."""
    rows = []
    wh_id = 10
    for i in range(n_warehouses):
        region = REGIONS[i % len(REGIONS)]
        anchor_lat, anchor_lon = REGION_ANCHORS[region]
        rows.append({
            "WAREHOUSE_ID": wh_id,
            "WAREHOUSE_NAME": f"{region.title()} DC {wh_id}",
            "REGION": region,
            "TIMEZONE": TIMEZONES[REGIONS.index(region)],
            "LATITUDE": round(float(anchor_lat + rng.uniform(-0.6, 0.6)), 5),
            "LONGITUDE": round(float(anchor_lon + rng.uniform(-0.6, 0.6)), 5),
            "OPENED_AT": START_DATE - timedelta(days=int(rng.integers(200, 2000))),
        })
        wh_id += 1
    return pd.DataFrame(rows)


def generate_drivers(rng, n_drivers=400):
    """
    One row per driver-employment record. Drivers churn and get rehired, so the
    same human can appear under more than one DRIVER_ID with overlapping names.
    """
    # --- gap driver: how much the roster has been reshuffled ---------------- #
    REHIRE_RATE = 0.10   # share of drivers that are a rehire of an earlier record

    first_names = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Morgan", "Riley",
                   "Jamie", "Devon", "Cameron", "Drew", "Reese", "Quinn", "Avery"]
    last_names = ["Reyes", "Nguyen", "Patel", "Okoro", "Santos", "Ivanov",
                  "Kim", "Diallo", "Murphy", "Costa", "Haddad", "Brooks"]

    rows = []
    driver_id = 5000
    name_pool = []  # (first, last) of earlier drivers, for rehires
    for i in range(n_drivers):
        is_rehire = len(name_pool) > 0 and rng.random() < REHIRE_RATE
        if is_rehire:
            first, last = name_pool[int(rng.integers(0, len(name_pool)))]
        else:
            first = first_names[int(rng.integers(0, len(first_names)))]
            last = last_names[int(rng.integers(0, len(last_names)))]
            name_pool.append((first, last))

        hired = START_DATE + timedelta(days=int(rng.integers(-400, 330)))
        # Some drivers have already terminated (left the company).
        if rng.random() < 0.22:
            terminated = hired + timedelta(days=int(rng.integers(30, 500)))
        else:
            terminated = None

        rows.append({
            "DRIVER_ID": driver_id,
            "DRIVER_NAME": f"{first} {last}",
            "HOME_REGION": REGIONS[int(rng.integers(0, len(REGIONS)))],
            "EMPLOYMENT_STATUS": "terminated" if terminated is not None else "active",
            "HIRED_AT": hired,
            "TERMINATED_AT": terminated,
        })
        driver_id += 1
    return pd.DataFrame(rows)


def generate_orders(rng, n_orders, warehouses):
    """
    One row per order. Carries the promised delivery window (the SLA the
    customer was sold) computed from the order date + service-level transit days.
    """
    order_ids = np.arange(100_000, 100_000 + n_orders)
    customer_ids = rng.integers(1, max(2, n_orders // 4), size=n_orders)
    created = _random_datetimes(rng, n_orders, START_DATE, END_DATE)

    wh_ids = warehouses["WAREHOUSE_ID"].to_numpy()
    origin_wh = rng.choice(wh_ids, size=n_orders)

    service = rng.choice(SERVICE_LEVELS, size=n_orders)

    weights = np.round(np.clip(rng.lognormal(mean=1.0, sigma=0.7, size=n_orders), 0.2, 70.0), 2)

    rows = []
    for i in range(n_orders):
        svc = service[i]
        promised_days = PROMISED_DAYS[svc]
        # The promised-by timestamp the customer was quoted at checkout.
        promised_by = created[i] + timedelta(days=promised_days)
        rows.append({
            "ORDER_ID": int(order_ids[i]),
            "CUSTOMER_ID": int(customer_ids[i]),
            "ORIGIN_WAREHOUSE_ID": int(origin_wh[i]),
            "DEST_REGION": REGIONS[int(rng.integers(0, len(REGIONS)))],
            "SERVICE_LEVEL": svc,
            "PACKAGE_WEIGHT_KG": float(weights[i]),
            "PROMISED_DELIVERY_AT": promised_by,
            "CREATED_AT": created[i],
        })
    return pd.DataFrame(rows)


def generate_deliveries(rng, orders, drivers):
    """
    One row per delivery record. Built from the carrier event feed. Most orders
    have exactly one delivery row; some have a duplicate scan (the same physical
    delivery double-reported by two carrier APIs), and a slice carry a missing
    delivered-at timestamp because a carrier feed dropped out mid-day.
    """
    # ----------------------------------------------------------------------- #
    # GAP DRIVERS — the three knobs that set the headline SLA spread.         #
    # The on-time rate swings several points depending on whether a fellow    #
    # EXCLUDES, IMPUTES, or FAILS the rows with a null DELIVERED_AT. These    #
    # constants control how big that swing is. Tune here to make a variant    #
    # harder/easier and to keep the headline metric in the brief's band.     #
    # ----------------------------------------------------------------------- #
    NULL_TIMESTAMP_RATE = 0.13   # share of completed deliveries missing DELIVERED_AT (feed dropout)
    LATE_AMONG_NULLS = 0.78      # of those null-timestamp rows, share that were ACTUALLY late
    BASE_LATE_RATE = 0.115       # late share among normal (timestamped) deliveries
    # --- secondary knobs ---------------------------------------------------- #
    DUP_SCAN_RATE = 0.02         # share of deliveries double-reported by two feeds
    INCOMPLETE_RATE = 0.05       # share of attempts that failed (no successful delivery)

    active_driver_ids = drivers["DRIVER_ID"].to_numpy()
    order_lookup = orders.set_index("ORDER_ID")

    rows = []
    delivery_id = 700_000

    for o in orders.itertuples(index=False):
        promised = o.PROMISED_DELIVERY_AT
        created = o.CREATED_AT
        svc = o.SERVICE_LEVEL
        driver_id = int(active_driver_ids[int(rng.integers(0, len(active_driver_ids)))])

        # Was this a failed / incomplete delivery attempt?
        if rng.random() < INCOMPLETE_RATE:
            attempted = created + timedelta(days=int(rng.integers(1, PROMISED_DAYS[svc] + 4)),
                                            hours=int(rng.integers(0, 24)))
            rows.append({
                "DELIVERY_ID": delivery_id,
                "ORDER_ID": int(o.ORDER_ID),
                "DRIVER_ID": driver_id,
                "CARRIER": str(rng.choice(CARRIERS)),
                "DELIVERY_STATUS": "failed",
                "FAILURE_REASON": str(rng.choice(FAILURE_REASONS)),
                "PICKED_UP_AT": created + timedelta(hours=int(rng.integers(2, 36))),
                "DELIVERED_AT": None,
                "ATTEMPTED_AT": attempted,
            })
            delivery_id += 1
            continue

        # Decide on-time vs late for this (completed) delivery.
        is_late = rng.random() < BASE_LATE_RATE

        # Will the carrier feed drop the delivered-at timestamp for this row?
        feed_dropped = rng.random() < NULL_TIMESTAMP_RATE
        if feed_dropped:
            # The dropped-timestamp population skews LATE — these are the
            # problem deliveries the carrier feed conveniently lost track of.
            is_late = rng.random() < LATE_AMONG_NULLS

        if is_late:
            # Delivered after the promised window.
            delivered = promised + timedelta(days=int(rng.integers(0, 4)),
                                             hours=int(rng.integers(1, 36)))
        else:
            # Delivered on or before the promised window.
            span_hours = max(1, int((promised - created).total_seconds() // 3600) - 2)
            delivered = created + timedelta(hours=int(rng.integers(2, span_hours + 1)))

        picked_up = created + timedelta(hours=int(rng.integers(2, 36)))
        delivered_at = None if feed_dropped else delivered

        status = "delivered"
        rows.append({
            "DELIVERY_ID": delivery_id,
            "ORDER_ID": int(o.ORDER_ID),
            "DRIVER_ID": driver_id,
            "CARRIER": str(rng.choice(CARRIERS)),
            "DELIVERY_STATUS": status,
            "FAILURE_REASON": None,
            "PICKED_UP_AT": picked_up,
            "DELIVERED_AT": delivered_at,
            "ATTEMPTED_AT": delivered if not feed_dropped else (promised + timedelta(hours=int(rng.integers(1, 24)))),
        })
        delivery_id += 1

        # A small share of deliveries are double-reported (same physical
        # delivery scanned by two carrier APIs). Same order, new delivery_id,
        # near-identical timestamps.
        if rng.random() < DUP_SCAN_RATE:
            dup = dict(rows[-1])
            dup["DELIVERY_ID"] = delivery_id
            if dup["DELIVERED_AT"] is not None:
                dup["DELIVERED_AT"] = dup["DELIVERED_AT"] + timedelta(seconds=int(rng.integers(5, 120)))
            dup["CARRIER"] = str(rng.choice(CARRIERS))
            rows.append(dup)
            delivery_id += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_WAREHOUSES": """
        CREATE OR REPLACE TABLE RAW_WAREHOUSES (
            WAREHOUSE_ID   NUMBER(18,0),
            WAREHOUSE_NAME VARCHAR,
            REGION         VARCHAR,
            TIMEZONE       VARCHAR,
            LATITUDE       NUMBER(9,5),
            LONGITUDE      NUMBER(9,5),
            OPENED_AT      TIMESTAMP_NTZ
        )""",
    "RAW_DRIVERS": """
        CREATE OR REPLACE TABLE RAW_DRIVERS (
            DRIVER_ID         NUMBER(18,0),
            DRIVER_NAME       VARCHAR,
            HOME_REGION       VARCHAR,
            EMPLOYMENT_STATUS VARCHAR,
            HIRED_AT          TIMESTAMP_NTZ,
            TERMINATED_AT     TIMESTAMP_NTZ
        )""",
    "RAW_ORDERS": """
        CREATE OR REPLACE TABLE RAW_ORDERS (
            ORDER_ID             NUMBER(18,0),
            CUSTOMER_ID          NUMBER(18,0),
            ORIGIN_WAREHOUSE_ID  NUMBER(18,0),
            DEST_REGION          VARCHAR,
            SERVICE_LEVEL        VARCHAR,
            PACKAGE_WEIGHT_KG    NUMBER(10,2),
            PROMISED_DELIVERY_AT TIMESTAMP_NTZ,
            CREATED_AT           TIMESTAMP_NTZ
        )""",
    "RAW_DELIVERIES": """
        CREATE OR REPLACE TABLE RAW_DELIVERIES (
            DELIVERY_ID     NUMBER(18,0),
            ORDER_ID        NUMBER(18,0),
            DRIVER_ID       NUMBER(18,0),
            CARRIER         VARCHAR,
            DELIVERY_STATUS VARCHAR,
            FAILURE_REASON  VARCHAR,
            PICKED_UP_AT    TIMESTAMP_NTZ,
            DELIVERED_AT    TIMESTAMP_NTZ,
            ATTEMPTED_AT    TIMESTAMP_NTZ
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

def build_tables(rng, n_orders):
    """Generate all four dataframes. Shared by main() and the validation hook."""
    warehouses = generate_warehouses(rng)
    drivers = generate_drivers(rng)
    orders = generate_orders(rng, n_orders, warehouses)
    deliveries = generate_deliveries(rng, orders, drivers)
    return {
        "RAW_WAREHOUSES": warehouses,
        "RAW_DRIVERS": drivers,
        "RAW_ORDERS": orders,
        "RAW_DELIVERIES": deliveries,
    }


def main():
    ap = argparse.ArgumentParser(description="Provision the Cartwright Freightways raw sandbox.")
    ap.add_argument("--orders", type=int, default=50_000, help="number of orders to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (orders={args.orders:,}, seed={args.seed}) ...")
    tables = build_tables(rng, args.orders)

    print("\nRow counts:")
    for name, df in tables.items():
        print(f"  {name:<16} {len(df):>10,}")

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
