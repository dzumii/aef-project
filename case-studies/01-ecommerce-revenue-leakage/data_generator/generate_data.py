#!/usr/bin/env python3
"""
Lumen & Loom — source-system data export simulator.

Provisions the four raw operational tables (ORDERS, PAYMENTS, REFUNDS, SHIPPING)
into a Snowflake sandbox. This emulates the messy, as-emitted feed from the
client's production systems: retried payments, partial and late refunds,
cancelled-but-paid orders, and a flaky shipping feed with missing timestamps.

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

# snowflake.connector is imported lazily inside get_connection() so that
# `--dry-run` works without the connector installed (e.g. for quick validation).


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# The simulated business operates over this window. Keep it spanning month
# boundaries so the revenue-recognition timing problem is exercised.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

CURRENCIES = ["USD", "USD", "USD", "USD", "USD", "EUR", "GBP"]  # mostly USD
PAYMENT_METHODS = ["card", "card", "card", "paypal", "apple_pay", "bank_transfer"]
CARRIERS = ["fleet_a", "fleet_b", "regional_x", "regional_y"]
REFUND_REASONS = ["damaged", "wrong_item", "changed_mind", "late_delivery", "not_as_described"]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_orders(rng, n_orders):
    """One row per order. Status reflects the order's current lifecycle state."""
    order_ids = np.arange(100_000, 100_000 + n_orders)
    customer_ids = rng.integers(1, max(2, n_orders // 4), size=n_orders)
    created = _random_datetimes(rng, n_orders, START_DATE, END_DATE)

    # Order value: log-normal-ish basket sizes, rounded to cents.
    amounts = np.round(rng.lognormal(mean=4.0, sigma=0.6, size=n_orders), 2)
    amounts = np.clip(amounts, 5.0, 5000.0)

    # Lifecycle status mix. "confirmed" means paid-and-progressing; "completed"
    # means fulfilled; "cancelled" means voided (but cash may already have moved).
    status = rng.choice(
        ["completed", "confirmed", "cancelled", "placed"],
        size=n_orders,
        p=[0.64, 0.19, 0.09, 0.08],
    )

    # updated_at is normally >= created_at...
    updated = [c + timedelta(hours=int(rng.integers(1, 720))) for c in created]

    df = pd.DataFrame({
        "ORDER_ID": order_ids,
        "CUSTOMER_ID": customer_ids,
        "ORDER_STATUS": status,
        "ORDER_AMOUNT": amounts,
        "CURRENCY": rng.choice(CURRENCIES, size=n_orders),
        "CREATED_AT": created,
        "UPDATED_AT": updated,
    })

    # ...except for a small population where the source system clock skewed and
    # updated_at lands BEFORE created_at. Left in as-emitted.
    skew_idx = rng.choice(n_orders, size=max(1, n_orders // 500), replace=False)
    df.loc[skew_idx, "UPDATED_AT"] = [
        c - timedelta(hours=int(rng.integers(1, 48))) for c in df.loc[skew_idx, "CREATED_AT"]
    ]
    return df


def generate_payments(rng, orders):
    """
    One row per payment ATTEMPT. The gateway logs every try, including failures
    and customer retries, so an order can have multiple rows.
    """
    rows = []
    payment_id = 500_000

    for o in orders.itertuples(index=False):
        # Cancelled and placed orders sometimes still have payment activity.
        # Completed/confirmed orders virtually always do.
        if o.ORDER_STATUS in ("completed", "confirmed"):
            attempt_success = True
        elif o.ORDER_STATUS == "cancelled":
            # A meaningful share of cancellations happened AFTER the card was charged.
            attempt_success = rng.random() < 0.45
        else:  # placed
            attempt_success = rng.random() < 0.25

        # Some orders see one or more failed attempts before success (retries).
        n_failed = rng.choice([0, 0, 0, 1, 2], p=[0.70, 0.12, 0.08, 0.07, 0.03])

        base_ts = o.CREATED_AT + timedelta(minutes=int(rng.integers(1, 120)))

        # Failed attempts first.
        for k in range(n_failed):
            rows.append({
                "PAYMENT_ID": payment_id,
                "ORDER_ID": o.ORDER_ID,
                "PAYMENT_STATUS": "failed",
                "AMOUNT": o.ORDER_AMOUNT,
                "CURRENCY": o.CURRENCY,
                "PAYMENT_METHOD": rng.choice(PAYMENT_METHODS),
                "GATEWAY_FEE": 0.0,
                "ATTEMPTED_AT": base_ts + timedelta(minutes=int(k * rng.integers(1, 30))),
                "PROCESSED_AT": None,
            })
            payment_id += 1

        if attempt_success:
            fee = np.round(o.ORDER_AMOUNT * 0.029 + 0.30, 2)
            success_ts = base_ts + timedelta(minutes=int((n_failed + 1) * rng.integers(1, 30)))
            success_row = {
                "PAYMENT_ID": payment_id,
                "ORDER_ID": o.ORDER_ID,
                "PAYMENT_STATUS": "succeeded",
                "AMOUNT": o.ORDER_AMOUNT,
                "CURRENCY": o.CURRENCY,
                "PAYMENT_METHOD": rng.choice(PAYMENT_METHODS),
                "GATEWAY_FEE": fee,
                "ATTEMPTED_AT": success_ts,
                "PROCESSED_AT": success_ts + timedelta(seconds=int(rng.integers(1, 90))),
            }
            rows.append(success_row)
            payment_id += 1

            # The gateway occasionally double-logs a settled payment (webhook
            # delivered twice). Same amount, same order, new payment_id.
            if rng.random() < 0.015:
                dup = dict(success_row)
                dup["PAYMENT_ID"] = payment_id
                dup["PROCESSED_AT"] = success_row["PROCESSED_AT"] + timedelta(seconds=int(rng.integers(1, 10)))
                rows.append(dup)
                payment_id += 1

    return pd.DataFrame(rows)


def generate_refunds(rng, orders, payments):
    """
    One row per refund. Refunds reference a succeeded payment, can be partial,
    and frequently land in a LATER month than the original order.
    """
    succeeded = payments[payments["PAYMENT_STATUS"] == "succeeded"]
    # Dedupe to one settling payment per order for refund targeting (the model
    # under test must itself decide how to handle the gateway double-logs).
    succeeded = succeeded.drop_duplicates(subset=["ORDER_ID"], keep="first")
    order_lookup = orders.set_index("ORDER_ID")

    rows = []
    refund_id = 900_000

    for p in succeeded.itertuples(index=False):
        o = order_lookup.loc[p.ORDER_ID]

        # Base refund propensity, higher for cancelled orders that were charged.
        if o.ORDER_STATUS == "cancelled":
            p_refund = 0.80
        else:
            p_refund = 0.075

        if rng.random() >= p_refund:
            continue

        # Partial vs full.
        if rng.random() < 0.35:
            refund_amount = np.round(float(p.AMOUNT) * rng.uniform(0.15, 0.85), 2)
        else:
            refund_amount = float(p.AMOUNT)

        # Timing: most refunds come days-to-weeks after payment, deliberately
        # pushing a chunk of them across a month boundary.
        lag_days = int(rng.choice([2, 5, 9, 20, 35, 55], p=[0.20, 0.22, 0.20, 0.18, 0.12, 0.08]))
        requested = p.PROCESSED_AT + timedelta(days=lag_days)
        processed = requested + timedelta(days=int(rng.integers(0, 4)))

        rows.append({
            "REFUND_ID": refund_id,
            "ORDER_ID": p.ORDER_ID,
            "PAYMENT_ID": p.PAYMENT_ID,
            "REFUND_AMOUNT": refund_amount,
            "CURRENCY": p.CURRENCY,
            "REFUND_REASON": rng.choice(REFUND_REASONS),
            "REFUND_STATUS": "completed",
            "REQUESTED_AT": requested,
            "PROCESSED_AT": processed,
        })
        refund_id += 1

    return pd.DataFrame(rows)


def generate_shipping(rng, orders, payments):
    """
    One row per shipment for orders that were paid. The carrier feed is flaky:
    SHIPPED_AT and DELIVERED_AT go missing when the carrier API times out.
    """
    paid_order_ids = set(payments.loc[payments["PAYMENT_STATUS"] == "succeeded", "ORDER_ID"])
    order_lookup = orders.set_index("ORDER_ID")

    rows = []
    shipment_id = 700_000

    for oid in paid_order_ids:
        o = order_lookup.loc[oid]
        # Cancelled orders usually weren't shipped.
        if o.ORDER_STATUS == "cancelled" and rng.random() < 0.85:
            continue

        ship_lag = int(rng.choice([1, 2, 3, 5, 8], p=[0.30, 0.30, 0.20, 0.12, 0.08]))
        shipped = o.CREATED_AT + timedelta(days=ship_lag)
        delivery_lag = int(rng.choice([2, 3, 4, 6, 10], p=[0.25, 0.30, 0.20, 0.15, 0.10]))
        delivered = shipped + timedelta(days=delivery_lag)

        status = "delivered"
        # Carrier API timeouts: null out timestamps on a slice of rows.
        if rng.random() < 0.08:
            shipped = None
            status = "in_transit"
        if shipped is not None and rng.random() < 0.06:
            delivered = None
            status = "in_transit"

        rows.append({
            "SHIPMENT_ID": shipment_id,
            "ORDER_ID": oid,
            "CARRIER": rng.choice(CARRIERS),
            "SHIPPING_COST": np.round(rng.uniform(3.5, 18.0), 2),
            "STATUS": status,
            "SHIPPED_AT": shipped,
            "DELIVERED_AT": delivered,
        })
        shipment_id += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_ORDERS": """
        CREATE OR REPLACE TABLE RAW_ORDERS (
            ORDER_ID     NUMBER(18,0),
            CUSTOMER_ID  NUMBER(18,0),
            ORDER_STATUS VARCHAR,
            ORDER_AMOUNT NUMBER(12,2),
            CURRENCY     VARCHAR,
            CREATED_AT   TIMESTAMP_NTZ,
            UPDATED_AT   TIMESTAMP_NTZ
        )""",
    "RAW_PAYMENTS": """
        CREATE OR REPLACE TABLE RAW_PAYMENTS (
            PAYMENT_ID     NUMBER(18,0),
            ORDER_ID       NUMBER(18,0),
            PAYMENT_STATUS VARCHAR,
            AMOUNT         NUMBER(12,2),
            CURRENCY       VARCHAR,
            PAYMENT_METHOD VARCHAR,
            GATEWAY_FEE    NUMBER(12,2),
            ATTEMPTED_AT   TIMESTAMP_NTZ,
            PROCESSED_AT   TIMESTAMP_NTZ
        )""",
    "RAW_REFUNDS": """
        CREATE OR REPLACE TABLE RAW_REFUNDS (
            REFUND_ID     NUMBER(18,0),
            ORDER_ID      NUMBER(18,0),
            PAYMENT_ID    NUMBER(18,0),
            REFUND_AMOUNT NUMBER(12,2),
            CURRENCY      VARCHAR,
            REFUND_REASON VARCHAR,
            REFUND_STATUS VARCHAR,
            REQUESTED_AT  TIMESTAMP_NTZ,
            PROCESSED_AT  TIMESTAMP_NTZ
        )""",
    "RAW_SHIPPING": """
        CREATE OR REPLACE TABLE RAW_SHIPPING (
            SHIPMENT_ID   NUMBER(18,0),
            ORDER_ID      NUMBER(18,0),
            CARRIER       VARCHAR,
            SHIPPING_COST NUMBER(12,2),
            STATUS        VARCHAR,
            SHIPPED_AT    TIMESTAMP_NTZ,
            DELIVERED_AT  TIMESTAMP_NTZ
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

def main():
    ap = argparse.ArgumentParser(description="Provision the Lumen & Loom raw sandbox.")
    ap.add_argument("--orders", type=int, default=50_000, help="number of orders to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (orders={args.orders:,}, seed={args.seed}) ...")
    orders = generate_orders(rng, args.orders)
    payments = generate_payments(rng, orders)
    refunds = generate_refunds(rng, orders, payments)
    shipping = generate_shipping(rng, orders, payments)

    tables = {
        "RAW_ORDERS": orders,
        "RAW_PAYMENTS": payments,
        "RAW_REFUNDS": refunds,
        "RAW_SHIPPING": shipping,
    }

    print("\nRow counts:")
    for name, df in tables.items():
        print(f"  {name:<14} {len(df):>10,}")

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
