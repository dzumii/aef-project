#!/usr/bin/env python3
"""
StreamNine — source-system data export simulator.

Provisions the five raw operational tables (USERS, PLANS, PAYMENTS, UPGRADES,
DOWNGRADES) into a Snowflake sandbox. This emulates the messy, as-emitted feed
from the client's billing and product systems: paused subscriptions, mid-cycle
upgrades and downgrades with proration, retried/duplicated charges, and a
lifecycle feed where status, plan, and payment do not always agree.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --users 40000 --seed 42

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

# snowflake.connector is imported lazily inside get_connection() / load_to_snowflake()
# so that `--dry-run` works without the connector installed (quick validation).


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# The simulated business operates over this window. Keep it spanning many month
# boundaries so the mid-cycle proration and paused-subscription timing problems
# are exercised across reporting periods.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

CURRENCIES = ["USD", "USD", "USD", "USD", "USD", "EUR", "GBP"]  # mostly USD
BILLING_INTERVALS = ["monthly", "monthly", "monthly", "annual"]  # mostly monthly
PAYMENT_METHODS = ["card", "card", "card", "paypal", "apple_pay"]

# The plan catalogue. PRICE is the list monthly price in the plan's currency.
# annual plans bill 12x at a discount, but the catalogue price is the monthly
# equivalent the product team quotes. Tiers are ordered cheap -> premium.
PLAN_CATALOGUE = [
    # (plan_code, plan_name, tier_rank, monthly_price_usd)
    ("FREE",     "Free",        0,  0.00),
    ("BASIC",    "Basic",       1,  6.99),
    ("STANDARD", "Standard",    2, 12.99),
    ("PLUS",     "Plus",        3, 17.99),
    ("PREMIUM",  "Premium",     4, 22.99),
    ("FAMILY",   "Family",      5, 29.99),
]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_plans():
    """One row per plan in the catalogue. Static reference data."""
    rows = []
    plan_id = 10
    for code, name, rank, price in PLAN_CATALOGUE:
        rows.append({
            "PLAN_ID": plan_id,
            "PLAN_CODE": code,
            "PLAN_NAME": name,
            "TIER_RANK": rank,
            "MONTHLY_PRICE": price,
            "CURRENCY": "USD",
        })
        plan_id += 1
    return pd.DataFrame(rows)


def generate_users(rng, n_users, plans):
    """
    One row per subscriber. Carries the CURRENT subscription state as the
    billing system last wrote it: current plan, current status, and the
    signup / cancellation lifecycle dates.
    """
    # ----------------------------------------------------------------- #
    # GAP DRIVERS (tunable). These three constants set the size of the  #
    # MRR-definition spread the engagement is built around. Treat the   #
    # block as the difficulty dial.                                     #
    # ----------------------------------------------------------------- #
    PAUSED_SHARE = 0.075       # fraction of subscribers currently `paused`
    CANCELLED_SHARE = 0.17     # fraction currently `cancelled`
    PAST_DUE_SHARE = 0.03      # fraction currently `past_due` (billing failed)
    # ----------------------------------------------------------------- #

    user_ids = np.arange(200_000, 200_000 + n_users)
    signup = _random_datetimes(rng, n_users, START_DATE, END_DATE)

    # Status mix. `active` = paying-and-current. `paused` = subscription on hold
    # (billing suspended, seat retained). `past_due` = last charge failed but not
    # yet cancelled. `cancelled` = voluntarily or involuntarily churned.
    active_share = 1.0 - PAUSED_SHARE - CANCELLED_SHARE - PAST_DUE_SHARE
    status = rng.choice(
        ["active", "paused", "past_due", "cancelled"],
        size=n_users,
        p=[active_share, PAUSED_SHARE, PAST_DUE_SHARE, CANCELLED_SHARE],
    )

    # Assign a current plan. Free tier exists; most subscribers sit on paid tiers.
    paid_plans = plans[plans["TIER_RANK"] > 0]
    plan_pick = rng.choice(
        paid_plans["PLAN_ID"].to_numpy(),
        size=n_users,
        p=_tier_weights(paid_plans),
    )
    # A slice of users are on the free tier (no revenue) regardless of status.
    free_id = int(plans.loc[plans["PLAN_CODE"] == "FREE", "PLAN_ID"].iloc[0])
    free_idx = rng.choice(n_users, size=max(1, int(n_users * 0.06)), replace=False)
    plan_pick[free_idx] = free_id

    billing_interval = rng.choice(BILLING_INTERVALS, size=n_users)
    currency = rng.choice(CURRENCIES, size=n_users)

    # Lifecycle dates.
    paused_at = [None] * n_users
    cancelled_at = [None] * n_users
    for i in range(n_users):
        s = signup[i]
        if status[i] == "paused":
            # Paused somewhere after signup; many pauses are recent / open-ended.
            paused_at[i] = s + timedelta(days=int(rng.integers(20, 300)))
        elif status[i] == "cancelled":
            cancelled_at[i] = s + timedelta(days=int(rng.integers(15, 330)))

    df = pd.DataFrame({
        "USER_ID": user_ids,
        "PLAN_ID": plan_pick,
        "SUBSCRIPTION_STATUS": status,
        "BILLING_INTERVAL": billing_interval,
        "CURRENCY": currency,
        "SIGNUP_AT": signup,
        "PAUSED_AT": paused_at,
        "CANCELLED_AT": cancelled_at,
    })

    # Source-system quirk: a slice of cancelled accounts retain a non-null
    # PAUSED_AT (they were paused, then cancelled) and a slice of paused/active
    # rows carry a stale CANCELLED_AT from a prior lifecycle the billing system
    # never cleared. Left in as-emitted.
    stale_idx = rng.choice(n_users, size=max(1, n_users // 200), replace=False)
    for i in stale_idx:
        if cancelled_at[i] is None:
            cancelled_at[i] = signup[i] + timedelta(days=int(rng.integers(5, 60)))
    df["CANCELLED_AT"] = cancelled_at

    # A small population has SIGNUP_AT after PAUSED_AT (clock skew on the
    # lifecycle feed). Left in.
    skew_idx = rng.choice(n_users, size=max(1, n_users // 400), replace=False)
    for i in skew_idx:
        if df.at[i, "PAUSED_AT"] is not None:
            df.at[i, "SIGNUP_AT"] = df.at[i, "PAUSED_AT"] + timedelta(days=int(rng.integers(1, 20)))

    return df


def _tier_weights(paid_plans):
    """Weighting toward the cheaper paid tiers; thinning toward premium."""
    ranks = paid_plans["TIER_RANK"].to_numpy().astype(float)
    w = 1.0 / ranks  # rank 1 heaviest, rank 5 lightest
    return w / w.sum()


def generate_upgrades(rng, users, plans):
    """
    One row per upgrade event (a move to a higher-priced tier). Mid-cycle
    upgrades generate a proration charge for the unused remainder of the period.
    Children reference USERS and PLANS.
    """
    # ----------------------------------------------------------------- #
    # GAP DRIVER (tunable). Share of eligible subscribers who upgraded   #
    # mid-cycle during the window. Mid-cycle moves are the proration     #
    # engine that splits MRR definitions apart.                          #
    # ----------------------------------------------------------------- #
    UPGRADE_RATE = 0.22
    # ----------------------------------------------------------------- #

    plan_by_id = plans.set_index("PLAN_ID")
    by_rank = plans.sort_values("TIER_RANK")
    rows = []
    upgrade_id = 600_000

    for u in users.itertuples(index=False):
        if u.SUBSCRIPTION_STATUS == "cancelled":
            continue
        cur = plan_by_id.loc[u.PLAN_ID]
        # Need a higher tier to exist to upgrade into.
        higher = by_rank[by_rank["TIER_RANK"] > int(cur.TIER_RANK)]
        if higher.empty:
            continue
        if rng.random() >= UPGRADE_RATE:
            continue

        to_plan = higher.iloc[int(rng.integers(0, len(higher)))]
        from_price = float(cur.MONTHLY_PRICE)
        to_price = float(to_plan["MONTHLY_PRICE"])

        # Effective date: sometime after signup, within the window.
        base = u.SIGNUP_AT + timedelta(days=int(rng.integers(10, 250)))
        if base > END_DATE:
            base = END_DATE - timedelta(days=int(rng.integers(1, 30)))
        effective = base

        # Mid-cycle proration: how far into the 30-day cycle the move happened.
        days_into_cycle = int(rng.integers(1, 30))
        remaining_fraction = (30 - days_into_cycle) / 30.0
        # The pro-rated catch-up charge for the remainder of the current cycle.
        proration_amount = np.round((to_price - from_price) * remaining_fraction, 2)

        rows.append({
            "UPGRADE_ID": upgrade_id,
            "USER_ID": u.USER_ID,
            "FROM_PLAN_ID": int(u.PLAN_ID),
            "TO_PLAN_ID": int(to_plan["PLAN_ID"]),
            "FROM_PRICE": from_price,
            "TO_PRICE": to_price,
            "PRORATION_AMOUNT": proration_amount,
            "DAYS_INTO_CYCLE": days_into_cycle,
            "CURRENCY": u.CURRENCY,
            "EFFECTIVE_AT": effective,
            "CREATED_AT": effective + timedelta(minutes=int(rng.integers(0, 120))),
        })
        upgrade_id += 1

        # Billing system occasionally writes the same plan-change event twice
        # (retry on the webhook). Same user, same effective date, new id.
        if rng.random() < 0.02:
            dup = dict(rows[-1])
            dup["UPGRADE_ID"] = upgrade_id
            rows.append(dup)
            upgrade_id += 1

    return pd.DataFrame(rows)


def generate_downgrades(rng, users, plans):
    """
    One row per downgrade event (a move to a lower-priced tier). Downgrades are
    typically scheduled for the NEXT cycle (no immediate proration credit), but
    a share take effect immediately with a pro-rated credit. Children reference
    USERS and PLANS.
    """
    # ----------------------------------------------------------------- #
    # GAP DRIVERS (tunable). DOWNGRADE_RATE sizes the population; the     #
    # IMMEDIATE share controls how many downgrades cut MRR this period    #
    # vs next period — the other half of the proration spread.           #
    # ----------------------------------------------------------------- #
    DOWNGRADE_RATE = 0.15
    IMMEDIATE_SHARE = 0.40   # rest are scheduled for next cycle
    # ----------------------------------------------------------------- #

    plan_by_id = plans.set_index("PLAN_ID")
    by_rank = plans.sort_values("TIER_RANK")
    rows = []
    downgrade_id = 800_000

    for u in users.itertuples(index=False):
        if u.SUBSCRIPTION_STATUS == "cancelled":
            continue
        cur = plan_by_id.loc[u.PLAN_ID]
        lower = by_rank[(by_rank["TIER_RANK"] < int(cur.TIER_RANK)) & (by_rank["TIER_RANK"] > 0)]
        if lower.empty:
            continue
        if rng.random() >= DOWNGRADE_RATE:
            continue

        to_plan = lower.iloc[int(rng.integers(0, len(lower)))]
        from_price = float(cur.MONTHLY_PRICE)
        to_price = float(to_plan["MONTHLY_PRICE"])

        base = u.SIGNUP_AT + timedelta(days=int(rng.integers(10, 250)))
        if base > END_DATE:
            base = END_DATE - timedelta(days=int(rng.integers(1, 30)))
        effective = base

        immediate = rng.random() < IMMEDIATE_SHARE
        if immediate:
            days_into_cycle = int(rng.integers(1, 30))
            remaining_fraction = (30 - days_into_cycle) / 30.0
            # Pro-rated CREDIT for the unused premium portion (negative amount).
            proration_amount = -np.round((from_price - to_price) * remaining_fraction, 2)
            change_type = "immediate"
        else:
            days_into_cycle = None
            proration_amount = 0.0
            change_type = "scheduled"
            # Scheduled downgrades take effect at the next cycle boundary.
            effective = effective + timedelta(days=int(rng.integers(1, 30)))

        rows.append({
            "DOWNGRADE_ID": downgrade_id,
            "USER_ID": u.USER_ID,
            "FROM_PLAN_ID": int(u.PLAN_ID),
            "TO_PLAN_ID": int(to_plan["PLAN_ID"]),
            "FROM_PRICE": from_price,
            "TO_PRICE": to_price,
            "PRORATION_AMOUNT": proration_amount,
            "DAYS_INTO_CYCLE": days_into_cycle,
            "CHANGE_TYPE": change_type,
            "CURRENCY": u.CURRENCY,
            "EFFECTIVE_AT": effective,
            "CREATED_AT": effective + timedelta(minutes=int(rng.integers(0, 120))),
        })
        downgrade_id += 1

    return pd.DataFrame(rows)


def generate_payments(rng, users, plans, upgrades, downgrades):
    """
    One row per billing charge ATTEMPT. The billing system logs every monthly
    (or annual) renewal attempt, every proration charge, retries on a declined
    card, and the occasional double-posted webhook. An order can have multiple
    rows; not all are successful settlements.
    """
    plan_by_id = plans.set_index("PLAN_ID")
    rows = []
    payment_id = 400_000

    # Pre-index proration events for charge generation.
    upg_by_user = {}
    for u in upgrades.itertuples(index=False):
        upg_by_user.setdefault(u.USER_ID, []).append(u)
    dwn_by_user = {}
    for d in downgrades.itertuples(index=False):
        dwn_by_user.setdefault(d.USER_ID, []).append(d)

    for u in users.itertuples(index=False):
        plan = plan_by_id.loc[u.PLAN_ID]
        price = float(plan.MONTHLY_PRICE)

        # Free tier never bills.
        if price <= 0:
            continue

        # Determine the billing window for this user: from signup to the end of
        # the window OR cancellation OR pause (paused subs stop billing).
        start = u.SIGNUP_AT
        stop = END_DATE
        if u.SUBSCRIPTION_STATUS == "cancelled" and u.CANCELLED_AT is not None:
            stop = min(stop, u.CANCELLED_AT)
        if u.SUBSCRIPTION_STATUS == "paused" and u.PAUSED_AT is not None:
            stop = min(stop, u.PAUSED_AT)

        if stop <= start:
            stop = start + timedelta(days=1)

        interval_days = 365 if u.BILLING_INTERVAL == "annual" else 30
        charge_unit = price * 12 if u.BILLING_INTERVAL == "annual" else price

        # Walk monthly/annual renewal charges across the active window.
        t = start
        while t < stop:
            # past_due users have a failed most-recent charge; model a failure
            # near the end of their window.
            is_last = (t + timedelta(days=interval_days)) >= stop
            failed = (u.SUBSCRIPTION_STATUS == "past_due" and is_last)

            n_failed_retries = 0
            if not failed:
                n_failed_retries = rng.choice([0, 0, 0, 1, 2], p=[0.74, 0.12, 0.07, 0.05, 0.02])

            base_ts = t + timedelta(minutes=int(rng.integers(1, 240)))
            for k in range(n_failed_retries):
                rows.append(_charge_row(
                    payment_id, u.USER_ID, int(u.PLAN_ID), "failed", charge_unit,
                    "renewal", u.CURRENCY, u.BILLING_INTERVAL,
                    base_ts + timedelta(minutes=int(k * rng.integers(1, 60))), None,
                ))
                payment_id += 1

            if failed:
                rows.append(_charge_row(
                    payment_id, u.USER_ID, int(u.PLAN_ID), "failed", charge_unit,
                    "renewal", u.CURRENCY, u.BILLING_INTERVAL, base_ts, None,
                ))
                payment_id += 1
            else:
                settle = base_ts + timedelta(minutes=int(rng.integers(1, 30)))
                row = _charge_row(
                    payment_id, u.USER_ID, int(u.PLAN_ID), "succeeded", charge_unit,
                    "renewal", u.CURRENCY, u.BILLING_INTERVAL, base_ts, settle,
                )
                rows.append(row)
                payment_id += 1
                # Billing webhook occasionally double-posts a settled charge.
                if rng.random() < 0.013:
                    dup = dict(row)
                    payment_id += 0
                    dup["PAYMENT_ID"] = payment_id
                    dup["PROCESSED_AT"] = row["PROCESSED_AT"] + timedelta(seconds=int(rng.integers(1, 20)))
                    rows.append(dup)
                    payment_id += 1

            t = t + timedelta(days=interval_days)

        # Proration charges for upgrades (positive catch-up charges).
        for ev in upg_by_user.get(u.USER_ID, []):
            if ev.EFFECTIVE_AT >= stop:
                continue
            ts = ev.EFFECTIVE_AT + timedelta(minutes=int(rng.integers(1, 60)))
            rows.append(_charge_row(
                payment_id, u.USER_ID, int(ev.TO_PLAN_ID), "succeeded",
                float(ev.PRORATION_AMOUNT), "proration", u.CURRENCY,
                u.BILLING_INTERVAL, ts, ts + timedelta(seconds=int(rng.integers(1, 60))),
            ))
            payment_id += 1

        # Proration credits for immediate downgrades (negative amounts).
        for ev in dwn_by_user.get(u.USER_ID, []):
            if ev.CHANGE_TYPE != "immediate" or ev.EFFECTIVE_AT >= stop:
                continue
            ts = ev.EFFECTIVE_AT + timedelta(minutes=int(rng.integers(1, 60)))
            rows.append(_charge_row(
                payment_id, u.USER_ID, int(ev.TO_PLAN_ID), "succeeded",
                float(ev.PRORATION_AMOUNT), "proration_credit", u.CURRENCY,
                u.BILLING_INTERVAL, ts, ts + timedelta(seconds=int(rng.integers(1, 60))),
            ))
            payment_id += 1

    df = pd.DataFrame(rows)
    return df


def _charge_row(payment_id, user_id, plan_id, status, amount, charge_type,
                currency, interval, attempted_at, processed_at):
    fee = np.round(abs(amount) * 0.029 + 0.30, 2) if status == "succeeded" else 0.0
    return {
        "PAYMENT_ID": payment_id,
        "USER_ID": user_id,
        "PLAN_ID": plan_id,
        "PAYMENT_STATUS": status,
        "AMOUNT": np.round(float(amount), 2),
        "CHARGE_TYPE": charge_type,
        "CURRENCY": currency,
        "BILLING_INTERVAL": interval,
        "PAYMENT_METHOD": None,  # set below in bulk for variety
        "GATEWAY_FEE": fee,
        "ATTEMPTED_AT": attempted_at,
        "PROCESSED_AT": processed_at,
    }


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_PLANS": """
        CREATE OR REPLACE TABLE RAW_PLANS (
            PLAN_ID       NUMBER(18,0),
            PLAN_CODE     VARCHAR,
            PLAN_NAME     VARCHAR,
            TIER_RANK     NUMBER(9,0),
            MONTHLY_PRICE NUMBER(12,2),
            CURRENCY      VARCHAR
        )""",
    "RAW_USERS": """
        CREATE OR REPLACE TABLE RAW_USERS (
            USER_ID             NUMBER(18,0),
            PLAN_ID             NUMBER(18,0),
            SUBSCRIPTION_STATUS VARCHAR,
            BILLING_INTERVAL    VARCHAR,
            CURRENCY            VARCHAR,
            SIGNUP_AT           TIMESTAMP_NTZ,
            PAUSED_AT           TIMESTAMP_NTZ,
            CANCELLED_AT        TIMESTAMP_NTZ
        )""",
    "RAW_PAYMENTS": """
        CREATE OR REPLACE TABLE RAW_PAYMENTS (
            PAYMENT_ID       NUMBER(18,0),
            USER_ID          NUMBER(18,0),
            PLAN_ID          NUMBER(18,0),
            PAYMENT_STATUS   VARCHAR,
            AMOUNT           NUMBER(12,2),
            CHARGE_TYPE      VARCHAR,
            CURRENCY         VARCHAR,
            BILLING_INTERVAL VARCHAR,
            PAYMENT_METHOD   VARCHAR,
            GATEWAY_FEE      NUMBER(12,2),
            ATTEMPTED_AT     TIMESTAMP_NTZ,
            PROCESSED_AT     TIMESTAMP_NTZ
        )""",
    "RAW_UPGRADES": """
        CREATE OR REPLACE TABLE RAW_UPGRADES (
            UPGRADE_ID       NUMBER(18,0),
            USER_ID          NUMBER(18,0),
            FROM_PLAN_ID     NUMBER(18,0),
            TO_PLAN_ID       NUMBER(18,0),
            FROM_PRICE       NUMBER(12,2),
            TO_PRICE         NUMBER(12,2),
            PRORATION_AMOUNT NUMBER(12,2),
            DAYS_INTO_CYCLE  NUMBER(9,0),
            CURRENCY         VARCHAR,
            EFFECTIVE_AT     TIMESTAMP_NTZ,
            CREATED_AT       TIMESTAMP_NTZ
        )""",
    "RAW_DOWNGRADES": """
        CREATE OR REPLACE TABLE RAW_DOWNGRADES (
            DOWNGRADE_ID     NUMBER(18,0),
            USER_ID          NUMBER(18,0),
            FROM_PLAN_ID     NUMBER(18,0),
            TO_PLAN_ID       NUMBER(18,0),
            FROM_PRICE       NUMBER(12,2),
            TO_PRICE         NUMBER(12,2),
            PRORATION_AMOUNT NUMBER(12,2),
            DAYS_INTO_CYCLE  NUMBER(9,0),
            CHANGE_TYPE      VARCHAR,
            CURRENCY         VARCHAR,
            EFFECTIVE_AT     TIMESTAMP_NTZ,
            CREATED_AT       TIMESTAMP_NTZ
        )""",
}


def _fill_payment_methods(rng, payments):
    """Assign a payment method per row in bulk (cosmetic, not load-bearing)."""
    if payments.empty:
        return payments
    payments["PAYMENT_METHOD"] = rng.choice(PAYMENT_METHODS, size=len(payments))
    return payments


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

def build_tables(rng, n_users):
    """Generate all five raw frames. Importable for validation."""
    plans = generate_plans()
    users = generate_users(rng, n_users, plans)
    upgrades = generate_upgrades(rng, users, plans)
    downgrades = generate_downgrades(rng, users, plans)
    payments = generate_payments(rng, users, plans, upgrades, downgrades)
    payments = _fill_payment_methods(rng, payments)
    return {
        "RAW_PLANS": plans,
        "RAW_USERS": users,
        "RAW_PAYMENTS": payments,
        "RAW_UPGRADES": upgrades,
        "RAW_DOWNGRADES": downgrades,
    }


def main():
    ap = argparse.ArgumentParser(description="Provision the StreamNine raw sandbox.")
    ap.add_argument("--users", type=int, default=40_000, help="number of subscribers to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (users={args.users:,}, seed={args.seed}) ...")
    tables = build_tables(rng, args.users)

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
