#!/usr/bin/env python3
"""
Northwind Cellular — source-system data export simulator.

Provisions the five raw operational tables (SUBSCRIBERS, PLANS, USAGE,
SUPPORT_TICKETS, PAYMENTS) into a Snowflake sandbox. This emulates the messy,
as-emitted feed from the carrier's production systems: subscribers who lapse on
payment but keep using the network, customers who explicitly cancel and later
reactivate, usage feeds that double-log mediation records, and a billing ledger
that mixes voluntary and involuntary disconnects.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --subscribers 40000 --seed 42

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

# The simulated carrier operates over this window. Subscribers acquire across
# the period; the "snapshot" / observation date below is when each team runs
# its churn report. Keep the observation date inside the window so trailing-30
# usage and payment-lapse windows are well-defined.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)
OBSERVATION_DATE = datetime(2024, 12, 31)

PLAN_TIERS = [
    ("PLAN_PREPAID_S", "prepaid", 15.00),
    ("PLAN_PREPAID_L", "prepaid", 30.00),
    ("PLAN_POSTPAID_S", "postpaid", 45.00),
    ("PLAN_POSTPAID_M", "postpaid", 65.00),
    ("PLAN_POSTPAID_L", "postpaid", 95.00),
    ("PLAN_FAMILY", "postpaid", 140.00),
]
USAGE_TYPES = ["voice", "voice", "data", "data", "data", "sms"]
TICKET_CATEGORIES = ["billing", "network", "device", "plan_change", "retention", "porting"]
TICKET_CHANNELS = ["phone", "chat", "store", "app", "email"]
PAYMENT_METHODS = ["card", "card", "card", "direct_debit", "wallet", "bank_transfer"]
REGIONS = ["north", "south", "east", "west", "central"]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_plans():
    """One row per plan. Small dimension; the subscribers table references it."""
    rows = []
    for code, ptype, mrc in PLAN_TIERS:
        rows.append({
            "PLAN_CODE": code,
            "PLAN_TYPE": ptype,
            "MONTHLY_RECURRING_CHARGE": mrc,
            "DATA_ALLOWANCE_GB": {
                "PLAN_PREPAID_S": 2, "PLAN_PREPAID_L": 8,
                "PLAN_POSTPAID_S": 10, "PLAN_POSTPAID_M": 30,
                "PLAN_POSTPAID_L": 100, "PLAN_FAMILY": 250,
            }[code],
            "CONTRACT_MONTHS": 0 if ptype == "prepaid" else 24,
        })
    return pd.DataFrame(rows)


def generate_subscribers(rng, n_subscribers):
    """
    One row per subscriber line. ACCOUNT_STATUS reflects the billing system's
    *current* view of the line. Note: the billing status and what the network
    actually sees (usage) and what the cash ledger sees (payments) do not always
    agree — that disagreement is the whole point of the engagement.
    """
    # ------------------------------------------------------------------- #
    # GAP DRIVERS — the three knobs that set the spread between the three  #
    # competing churn definitions. Tune these to move the headline metric. #
    # ------------------------------------------------------------------- #
    # (1) Share of lines the billing system has flagged explicitly cancelled.
    P_EXPLICIT_CANCEL = 0.135
    # (2) Of lines NOT explicitly cancelled, share that have quietly gone silent
    #     (no network usage in the trailing window) — "dark" lines the billing
    #     system still shows as active.
    P_SILENT_GIVEN_ACTIVE = 0.055
    # (3) Of explicitly-cancelled lines, share that later REACTIVATED (won back
    #     or ported back in) and are using the network again as of observation.
    P_REACTIVATED_GIVEN_CANCEL = 0.22
    # ------------------------------------------------------------------- #

    sub_ids = np.arange(1_000_000, 1_000_000 + n_subscribers)
    plan_codes = [c for c, _, _ in PLAN_TIERS]
    plan_choice = rng.choice(plan_codes, size=n_subscribers,
                             p=[0.10, 0.12, 0.20, 0.26, 0.20, 0.12])

    # Activation spread across the year (older cohorts have more lifecycle).
    activated = _random_datetimes(rng, n_subscribers, START_DATE,
                                  END_DATE - timedelta(days=20))

    region = rng.choice(REGIONS, size=n_subscribers)
    autopay = rng.random(n_subscribers) < 0.58

    explicit_cancel = rng.random(n_subscribers) < P_EXPLICIT_CANCEL
    # Among the not-explicitly-cancelled, who has quietly gone silent.
    silent = (~explicit_cancel) & (rng.random(n_subscribers) < P_SILENT_GIVEN_ACTIVE)
    # Among the explicitly-cancelled, who reactivated and is using again.
    reactivated = explicit_cancel & (rng.random(n_subscribers) < P_REACTIVATED_GIVEN_CANCEL)

    rows = []
    for i in range(n_subscribers):
        act = activated[i]
        if explicit_cancel[i]:
            # Cancellation lands some time after activation.
            cancel_dt = act + timedelta(days=int(rng.integers(25, 320)))
            if cancel_dt > OBSERVATION_DATE:
                cancel_dt = OBSERVATION_DATE - timedelta(days=int(rng.integers(1, 40)))
            status = "cancelled"
            # Some "cancelled" lines were involuntary (carrier-initiated for
            # non-payment) rather than voluntary (customer asked to leave).
            disconnect_reason = rng.choice(
                ["voluntary", "voluntary", "involuntary", "ported_out"],
                p=[0.42, 0.18, 0.30, 0.10],
            )
        else:
            cancel_dt = None
            status = "active"
            disconnect_reason = None

        rows.append({
            "SUBSCRIBER_ID": int(sub_ids[i]),
            "PLAN_CODE": plan_choice[i],
            "REGION": region[i],
            "ACCOUNT_STATUS": status,
            "AUTOPAY_ENROLLED": bool(autopay[i]),
            "DISCONNECT_REASON": disconnect_reason,
            "ACTIVATED_AT": act,
            "CANCELLED_AT": cancel_dt,
            # carry intermediate signals so downstream generators stay consistent;
            # these are NOT emitted to the warehouse.
            "GEN_SILENT": bool(silent[i]),
            "GEN_REACTIVATED": bool(reactivated[i]),
            "GEN_EXPLICIT_CANCEL": bool(explicit_cancel[i]),
        })

    df = pd.DataFrame(rows)

    # A small population of subscribers appears TWICE in the export — the same
    # line re-keyed after a SIM swap / account migration. Same SUBSCRIBER_ID,
    # different ACTIVATED_AT, occasionally a conflicting ACCOUNT_STATUS.
    dup_idx = rng.choice(n_subscribers, size=max(1, n_subscribers // 200), replace=False)
    dups = df.iloc[dup_idx].copy()
    dups["ACTIVATED_AT"] = [a + timedelta(days=int(rng.integers(1, 90)))
                            for a in dups["ACTIVATED_AT"]]
    df = pd.concat([df, dups], ignore_index=True)

    return df


def generate_usage(rng, subscribers):
    """
    One row per daily usage-mediation record for a subscriber-line. The network
    keeps emitting records while the line is live on the radio, regardless of
    what the billing system thinks. Silent / cancelled-not-reactivated lines go
    quiet; reactivated lines resume.
    """
    rows = []
    usage_id = 5_000_000

    # Only iterate the de-duplicated, first-seen view of each subscriber for
    # usage generation (the duplicate export rows share the same SUBSCRIBER_ID).
    seen = set()
    for s in subscribers.itertuples(index=False):
        if s.SUBSCRIBER_ID in seen:
            continue
        seen.add(s.SUBSCRIBER_ID)

        act = s.ACTIVATED_AT
        # When does this line stop generating usage?
        if s.GEN_EXPLICIT_CANCEL and not s.GEN_REACTIVATED:
            # Goes dark around the cancel date.
            last_usage = (s.CANCELLED_AT or OBSERVATION_DATE) - timedelta(
                days=int(rng.integers(0, 10)))
        elif s.GEN_SILENT:
            # Quietly stopped using the network well before observation, but
            # billing still shows active. This is the "30-day-no-usage" churn
            # population that the billing/cancel views miss.
            last_usage = OBSERVATION_DATE - timedelta(days=int(rng.integers(31, 120)))
        else:
            # Active (incl. reactivated) — used recently.
            last_usage = OBSERVATION_DATE - timedelta(days=int(rng.integers(0, 8)))

        if last_usage <= act:
            # Edge case: never really got going. Emit a single light record.
            last_usage = act + timedelta(days=1)

        # Number of usage days sampled across [act, last_usage].
        live_days = max(1, (last_usage - act).days)
        n_events = min(live_days, int(rng.integers(3, 40)))
        event_days = rng.integers(0, live_days, size=n_events)

        for d in event_days:
            ts = act + timedelta(days=int(d),
                                 hours=int(rng.integers(0, 24)),
                                 minutes=int(rng.integers(0, 60)))
            utype = rng.choice(USAGE_TYPES)
            if utype == "data":
                units = float(np.round(rng.uniform(0.05, 3.5), 3))   # GB
            elif utype == "voice":
                units = float(rng.integers(1, 90))                   # minutes
            else:
                units = float(rng.integers(1, 40))                   # messages
            row = {
                "USAGE_ID": usage_id,
                "SUBSCRIBER_ID": int(s.SUBSCRIBER_ID),
                "USAGE_TYPE": utype,
                "USAGE_UNITS": units,
                "USAGE_DATE": ts,
            }
            rows.append(row)
            usage_id += 1

            # The mediation pipeline occasionally double-logs a record (replayed
            # batch). Same subscriber/day/units, new USAGE_ID.
            if rng.random() < 0.012:
                dup = dict(row)
                dup["USAGE_ID"] = usage_id
                rows.append(dup)
                usage_id += 1

    return pd.DataFrame(rows)


def generate_payments(rng, subscribers, plans):
    """
    One row per monthly billing charge / payment outcome for postpaid lines and
    per top-up for prepaid lines. PAYMENT_STATUS captures whether the charge
    cleared. A subscriber can keep using the network while payments lapse — and
    the billing system is slow to flip ACCOUNT_STATUS to cancelled.
    """
    # ------------------------------------------------------------------- #
    # GAP DRIVER (4) — payment-lapse propensity. Of lines that are still   #
    # "active" in billing, the share whose most-recent charge is missed /  #
    # past-due beyond the grace window drives the Finance churn count.     #
    # ------------------------------------------------------------------- #
    P_LAPSE_GIVEN_ACTIVE = 0.135
    # ------------------------------------------------------------------- #

    mrc_lookup = plans.set_index("PLAN_CODE")["MONTHLY_RECURRING_CHARGE"].to_dict()
    rows = []
    payment_id = 8_000_000

    seen = set()
    for s in subscribers.itertuples(index=False):
        if s.SUBSCRIBER_ID in seen:
            continue
        seen.add(s.SUBSCRIBER_ID)

        mrc = float(mrc_lookup.get(s.PLAN_CODE, 45.0))
        # Billing runs monthly from activation up to the earlier of cancel /
        # observation.
        end = s.CANCELLED_AT or OBSERVATION_DATE
        if end <= s.ACTIVATED_AT:
            continue
        n_cycles = max(1, (end - s.ACTIVATED_AT).days // 30)

        # Decide if THIS line is in payment lapse as of observation.
        lapsed = False
        if s.ACCOUNT_STATUS == "active":
            lapsed = rng.random() < P_LAPSE_GIVEN_ACTIVE

        for c in range(n_cycles):
            due = s.ACTIVATED_AT + timedelta(days=30 * (c + 1))
            if due > OBSERVATION_DATE:
                break
            is_last = (due + timedelta(days=30) > OBSERVATION_DATE) or (c == n_cycles - 1)

            if lapsed and is_last:
                status = "past_due"
                paid_at = None
            elif s.ACCOUNT_STATUS == "cancelled" and is_last and \
                    s.DISCONNECT_REASON == "involuntary":
                # Involuntary disconnects trail a missed payment.
                status = "past_due"
                paid_at = None
            else:
                # Occasional one-off failures that later cleared (retry).
                if rng.random() < 0.04:
                    status = "failed"
                    paid_at = None
                else:
                    status = "paid"
                    paid_at = due + timedelta(days=int(rng.integers(0, 6)))

            amount = mrc
            # Prepaid top-ups vary in amount.
            if s.PLAN_CODE.startswith("PLAN_PREPAID"):
                amount = float(np.round(mrc * rng.uniform(0.5, 2.0), 2))

            rows.append({
                "PAYMENT_ID": payment_id,
                "SUBSCRIBER_ID": int(s.SUBSCRIBER_ID),
                "BILLING_PERIOD": due.strftime("%Y-%m"),
                "AMOUNT_DUE": amount,
                "PAYMENT_STATUS": status,
                "PAYMENT_METHOD": rng.choice(PAYMENT_METHODS),
                "DUE_AT": due,
                "PAID_AT": paid_at,
            })
            payment_id += 1

            # A retried charge after a transient failure double-logs occasionally:
            # a second 'paid' row for the same period settles a day later.
            if status == "failed" and rng.random() < 0.55:
                rows.append({
                    "PAYMENT_ID": payment_id,
                    "SUBSCRIBER_ID": int(s.SUBSCRIBER_ID),
                    "BILLING_PERIOD": due.strftime("%Y-%m"),
                    "AMOUNT_DUE": amount,
                    "PAYMENT_STATUS": "paid",
                    "PAYMENT_METHOD": rng.choice(PAYMENT_METHODS),
                    "DUE_AT": due,
                    "PAID_AT": due + timedelta(days=int(rng.integers(1, 9))),
                })
                payment_id += 1

    return pd.DataFrame(rows)


def generate_support_tickets(rng, subscribers):
    """
    One row per support contact. Retention tickets cluster around churn events;
    a slice of tickets carry a null RESOLVED_AT (still open / feed dropped it).
    """
    rows = []
    ticket_id = 3_000_000

    seen = set()
    for s in subscribers.itertuples(index=False):
        if s.SUBSCRIBER_ID in seen:
            continue
        seen.add(s.SUBSCRIBER_ID)

        # Base ticket count; churners and reactivations contact support more.
        base = rng.random()
        if s.GEN_EXPLICIT_CANCEL:
            n_tickets = int(rng.choice([0, 1, 2, 3], p=[0.20, 0.38, 0.28, 0.14]))
        elif s.GEN_SILENT:
            n_tickets = int(rng.choice([0, 1, 2], p=[0.55, 0.33, 0.12]))
        else:
            n_tickets = int(rng.choice([0, 1, 2], p=[0.70, 0.24, 0.06]))

        for _ in range(n_tickets):
            opened = s.ACTIVATED_AT + timedelta(
                days=int(rng.integers(1, max(2, (OBSERVATION_DATE - s.ACTIVATED_AT).days))))
            if opened > OBSERVATION_DATE:
                opened = OBSERVATION_DATE - timedelta(days=int(rng.integers(1, 15)))

            category = rng.choice(TICKET_CATEGORIES)
            if s.GEN_EXPLICIT_CANCEL and rng.random() < 0.4:
                category = "retention"

            resolved = opened + timedelta(hours=int(rng.integers(1, 240)))
            # Some tickets never got a resolution timestamp (open / feed gap).
            if rng.random() < 0.10:
                resolved = None

            rows.append({
                "TICKET_ID": ticket_id,
                "SUBSCRIBER_ID": int(s.SUBSCRIBER_ID),
                "CATEGORY": category,
                "CHANNEL": rng.choice(TICKET_CHANNELS),
                "OPENED_AT": opened,
                "RESOLVED_AT": resolved,
            })
            ticket_id += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_SUBSCRIBERS": """
        CREATE OR REPLACE TABLE RAW_SUBSCRIBERS (
            SUBSCRIBER_ID     NUMBER(18,0),
            PLAN_CODE         VARCHAR,
            REGION            VARCHAR,
            ACCOUNT_STATUS    VARCHAR,
            AUTOPAY_ENROLLED  BOOLEAN,
            DISCONNECT_REASON VARCHAR,
            ACTIVATED_AT      TIMESTAMP_NTZ,
            CANCELLED_AT      TIMESTAMP_NTZ
        )""",
    "RAW_PLANS": """
        CREATE OR REPLACE TABLE RAW_PLANS (
            PLAN_CODE                VARCHAR,
            PLAN_TYPE                VARCHAR,
            MONTHLY_RECURRING_CHARGE NUMBER(12,2),
            DATA_ALLOWANCE_GB        NUMBER(10,0),
            CONTRACT_MONTHS          NUMBER(5,0)
        )""",
    "RAW_USAGE": """
        CREATE OR REPLACE TABLE RAW_USAGE (
            USAGE_ID      NUMBER(18,0),
            SUBSCRIBER_ID NUMBER(18,0),
            USAGE_TYPE    VARCHAR,
            USAGE_UNITS   NUMBER(14,3),
            USAGE_DATE    TIMESTAMP_NTZ
        )""",
    "RAW_SUPPORT_TICKETS": """
        CREATE OR REPLACE TABLE RAW_SUPPORT_TICKETS (
            TICKET_ID     NUMBER(18,0),
            SUBSCRIBER_ID NUMBER(18,0),
            CATEGORY      VARCHAR,
            CHANNEL       VARCHAR,
            OPENED_AT     TIMESTAMP_NTZ,
            RESOLVED_AT   TIMESTAMP_NTZ
        )""",
    "RAW_PAYMENTS": """
        CREATE OR REPLACE TABLE RAW_PAYMENTS (
            PAYMENT_ID     NUMBER(18,0),
            SUBSCRIBER_ID  NUMBER(18,0),
            BILLING_PERIOD VARCHAR,
            AMOUNT_DUE     NUMBER(12,2),
            PAYMENT_STATUS VARCHAR,
            PAYMENT_METHOD VARCHAR,
            DUE_AT         TIMESTAMP_NTZ,
            PAID_AT        TIMESTAMP_NTZ
        )""",
}

# Columns that exist only to keep the generators consistent and must NOT be
# emitted to the warehouse.
_INTERNAL_COLS = ["GEN_SILENT", "GEN_REACTIVATED", "GEN_EXPLICIT_CANCEL"]


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

def build_tables(rng, n_subscribers):
    """Generate every dataframe, return the warehouse-ready table dict."""
    plans = generate_plans()
    subscribers = generate_subscribers(rng, n_subscribers)
    usage = generate_usage(rng, subscribers)
    payments = generate_payments(rng, subscribers, plans)
    tickets = generate_support_tickets(rng, subscribers)

    # Strip the internal helper columns before they hit the warehouse.
    subscribers_out = subscribers.drop(columns=_INTERNAL_COLS)

    return {
        "RAW_SUBSCRIBERS": subscribers_out,
        "RAW_PLANS": plans,
        "RAW_USAGE": usage,
        "RAW_SUPPORT_TICKETS": tickets,
        "RAW_PAYMENTS": payments,
    }, subscribers  # also return the un-stripped frame for validation


def main():
    ap = argparse.ArgumentParser(description="Provision the Northwind Cellular raw sandbox.")
    ap.add_argument("--subscribers", type=int, default=40_000,
                    help="number of subscriber lines to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (subscribers={args.subscribers:,}, seed={args.seed}) ...")
    tables, _ = build_tables(rng, args.subscribers)

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
