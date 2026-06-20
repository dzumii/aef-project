#!/usr/bin/env python3
"""
GlobeMart — multi-country retail source-system data export simulator.

Provisions the four raw operational tables (SALES, STORES, INVENTORY,
CURRENCY_RATES) into a Snowflake sandbox. This emulates the messy, as-emitted
feed from a retail chain operating across eight countries: sales booked in
eight local currencies, store metadata with timezones and reporting calendars,
an inventory snapshot feed, and a partial/messy currency-rate table that only
covers part of the window and is missing weekend and holiday rows.

The reporting currency is USD, but the conversion rates are NOT in the
warehouse in any trustworthy, complete form. Fellows must pull historical
daily rates from a free, keyless FX API (Frankfurter or exchangerate.host) and
decide which day's rate applies to each sale — and what to do about weekends,
holidays, and gaps. See README.md ("FX rate workflow").

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --rows 60000 --seed 42

Credentials are read from environment variables (see requirements.txt / README):
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

Nothing about the data flaws is documented here on purpose — this is meant to
read like a real operational export. Fellows: your job is to find what's wrong.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd

# snowflake.connector is imported lazily inside get_connection() so that
# `--dry-run` works without the connector installed (e.g. for quick validation).


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# The simulated business operates over this window. Keep it spanning month and
# quarter boundaries so the FX rate-date timing problem is exercised, and so
# month-end vs transaction-date rate policies diverge.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

# Eight countries, each booking in its own local currency. Each tuple is:
#   (country, currency, timezone, share-of-sales-weight, approx local price multiplier)
# The price multiplier is roughly the local-currency magnitude vs USD, so that
# a "$50-ish" basket lands at a believable local face value (e.g. ~7,500 JPY).
COUNTRIES = [
    ("United States",  "USD", "America/New_York",     0.26,    1.0),
    ("United Kingdom", "GBP", "Europe/London",        0.13,    0.79),
    ("Germany",        "EUR", "Europe/Berlin",        0.15,    0.92),
    ("Japan",          "JPY", "Asia/Tokyo",           0.12,  150.0),
    ("Canada",         "CAD", "America/Toronto",      0.10,    1.36),
    ("Australia",      "AUD", "Australia/Sydney",     0.09,    1.52),
    ("India",          "INR", "Asia/Kolkata",         0.08,   83.0),
    ("Brazil",         "BRL", "America/Sao_Paulo",    0.07,    4.95),
]

CHANNELS = ["in_store", "in_store", "in_store", "online", "online"]
PAYMENT_METHODS = ["card", "card", "card", "cash", "mobile_wallet"]
PRODUCT_CATEGORIES = ["apparel", "home", "electronics", "beauty", "grocery", "toys"]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end (naive, store-local)."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_stores(rng, n_stores=40):
    """
    One row per store. Stores are distributed across the eight countries.
    Carries the country, local currency, timezone, and the store's fiscal
    reporting-calendar flavour (which a keen fellow notices is not uniform).
    """
    rows = []
    store_id = 3000
    # Reporting calendars are not uniform across the estate — some legacy
    # stores still close their books on a 4-4-5 retail calendar, most on the
    # gregorian month. This is metadata the exec layer has to reconcile.
    calendars = ["gregorian", "gregorian", "gregorian", "retail_445"]
    for _ in range(n_stores):
        country, currency, tz, _w, _m = COUNTRIES[
            rng.choice(len(COUNTRIES), p=[c[3] for c in COUNTRIES])
        ]
        rows.append({
            "STORE_ID": store_id,
            "STORE_NAME": f"GlobeMart {country.split()[0]} #{store_id}",
            "COUNTRY": country,
            "LOCAL_CURRENCY": currency,
            "TIMEZONE": tz,
            "REPORTING_CALENDAR": rng.choice(calendars),
            "OPENED_AT": (START_DATE - timedelta(days=int(rng.integers(200, 3000)))),
        })
        store_id += 1
    return pd.DataFrame(rows)


def generate_sales(rng, n_rows, stores):
    """
    One row per sale (transaction line at order grain). Amounts are in the
    store's LOCAL currency — there is no USD column. Timestamps are naive and
    are local wall-clock time in the store's own timezone (no offset stored).
    """
    # ----------------------------------------------------------------------- #
    # GAP DRIVERS — tune these to make the headline FX-spread land in band.    #
    # The headline metric is: consolidated USD revenue computed with three    #
    # different FX rate-date policies (transaction-date / month-end / fixed    #
    # annual-average) and how far apart the totals land. These knobs control   #
    # how much the currency mix and intra-year FX drift move that spread.      #
    # ----------------------------------------------------------------------- #
    NON_USD_TILT = 1.00       # >1 over-weights volatile non-USD currencies vs the country shares
    LATE_BOOKING_PROB = 0.06  # share of sales whose BOOKED_AT lands in a later month than SOLD_AT
    RETURN_PROB = 0.05        # share flagged returned (negative-ish economic value)
    VOID_PROB = 0.02          # share voided (should be excluded from revenue)

    store_lookup = stores.set_index("STORE_ID")
    store_ids = stores["STORE_ID"].to_numpy()

    # Weight store selection by country share AND the non-USD tilt so the
    # currency mix is controllable. USD stores get weight 1; others get tilt.
    store_weights = []
    for sid in store_ids:
        cur = store_lookup.loc[sid, "LOCAL_CURRENCY"]
        store_weights.append(1.0 if cur == "USD" else NON_USD_TILT)
    store_weights = np.array(store_weights, dtype=float)
    store_weights /= store_weights.sum()

    chosen_stores = rng.choice(store_ids, size=n_rows, p=store_weights)
    sold_at = _random_datetimes(rng, n_rows, START_DATE, END_DATE)

    rows = []
    sale_id = 1_000_000
    cur_mult = {c[1]: c[4] for c in COUNTRIES}

    for i in range(n_rows):
        sid = int(chosen_stores[i])
        store = store_lookup.loc[sid]
        currency = store["LOCAL_CURRENCY"]

        # USD-equivalent basket size (log-normal), then expressed in local face
        # value via the currency magnitude multiplier.
        usd_basket = float(np.clip(rng.lognormal(mean=3.9, sigma=0.55), 5.0, 4000.0))
        local_amount = round(usd_basket * cur_mult[currency], 2)

        # Most sales complete; a slice are voided (cancelled at the till, no
        # revenue) and a slice are returned (revenue reversed later).
        r = rng.random()
        if r < VOID_PROB:
            status = "voided"
        elif r < VOID_PROB + RETURN_PROB:
            status = "returned"
        else:
            status = "completed"

        s_at = sold_at[i]
        # Most sales are booked the same day; a slice are booked into the
        # accounting system later — sometimes crossing a month boundary, which
        # is exactly where "which day's FX rate" starts to bite.
        if rng.random() < LATE_BOOKING_PROB:
            booked = s_at + timedelta(days=int(rng.integers(3, 22)))
        else:
            booked = s_at + timedelta(hours=int(rng.integers(0, 6)))

        rows.append({
            "SALE_ID": sale_id,
            "STORE_ID": sid,
            "PRODUCT_CATEGORY": rng.choice(PRODUCT_CATEGORIES),
            "CHANNEL": rng.choice(CHANNELS),
            "PAYMENT_METHOD": rng.choice(PAYMENT_METHODS),
            "QUANTITY": int(rng.integers(1, 6)),
            "LOCAL_AMOUNT": local_amount,
            "LOCAL_CURRENCY": currency,
            "SALE_STATUS": status,
            "SOLD_AT": s_at,           # store-local wall clock, naive
            "BOOKED_AT": booked,       # when it hit the accounting system
        })
        sale_id += 1

    df = pd.DataFrame(rows)

    # A small population of duplicate transactions: the POS occasionally
    # re-sends a settled sale (offline terminal re-sync). Same store/amount/time,
    # new SALE_ID. Left in as-emitted.
    dup_idx = rng.choice(len(df), size=max(1, len(df) // 130), replace=False)
    dups = df.loc[dup_idx].copy()
    dups["SALE_ID"] = np.arange(sale_id, sale_id + len(dups))
    df = pd.concat([df, dups], ignore_index=True)

    # A thin slice of sales lost their SOLD_AT in transit (terminal clock not
    # set / field dropped by the integration). BOOKED_AT still present.
    null_idx = rng.choice(len(df), size=max(1, len(df) // 90), replace=False)
    df.loc[null_idx, "SOLD_AT"] = None

    return df


def generate_inventory(rng, stores, n_snaps_per_store=6):
    """
    Periodic inventory snapshots per store × product category. Value is carried
    in the store's local currency (UNITS × local unit cost), so the inventory
    mart faces the same currency-normalisation problem as sales.
    """
    rows = []
    snap_id = 800_000
    cur_mult = {c[1]: c[4] for c in COUNTRIES}
    # Roughly monthly snapshots across the window.
    snap_dates = [START_DATE + timedelta(days=int(d)) for d in
                  np.linspace(15, 350, n_snaps_per_store).astype(int)]
    for s in stores.itertuples(index=False):
        currency = s.LOCAL_CURRENCY
        for snap_dt in snap_dates:
            for cat in PRODUCT_CATEGORIES:
                units = int(rng.integers(0, 800))
                usd_unit_cost = float(np.clip(rng.lognormal(mean=2.4, sigma=0.5), 2.0, 400.0))
                local_unit_cost = round(usd_unit_cost * cur_mult[currency], 2)
                rows.append({
                    "SNAPSHOT_ID": snap_id,
                    "STORE_ID": s.STORE_ID,
                    "PRODUCT_CATEGORY": cat,
                    "UNITS_ON_HAND": units,
                    "LOCAL_UNIT_COST": local_unit_cost,
                    "LOCAL_CURRENCY": currency,
                    "SNAPSHOT_DATE": snap_dt.date(),
                })
                snap_id += 1
    df = pd.DataFrame(rows)
    return df


def generate_currency_rates(rng, n_rows_window=None):
    """
    A PARTIAL, messy in-warehouse FX table. This is deliberately NOT a complete
    or trustworthy rate source — it only covers the FIRST part of the year, has
    NO weekend rows, drops a scatter of weekdays, and is missing several
    currencies entirely. It models the common "we had some rates in a
    spreadsheet" situation. Fellows are expected to pull the authoritative
    history from the FX API and treat this table as, at best, a cross-check.

    Rate convention: RATE_TO_USD is the multiplier such that
        amount_usd = local_amount / RATE_TO_USD        (i.e. local units per USD)
    EXCEPT the table is internally inconsistent in places (see below), which is
    part of why it is not trustworthy on its own.
    """
    # Anchor "local units per 1 USD" near plausible 2024 levels, with a gentle
    # intra-year drift so transaction-date vs month-end policies actually differ.
    anchors = {
        "GBP": 0.79, "EUR": 0.92, "JPY": 150.0,
        "CAD": 1.36, "AUD": 1.52, "INR": 83.0, "BRL": 4.95,
    }
    # Only a SUBSET of currencies made it into the warehouse table.
    covered = ["GBP", "EUR", "JPY", "CAD"]   # AUD, INR, BRL absent entirely
    # Coverage stops partway through the year — the rest must come from the API.
    coverage_end = datetime(2024, 7, 31)

    rows = []
    rate_id = 600_000
    d = START_DATE
    while d <= coverage_end:
        wd = d.weekday()
        # No weekend rows at all (markets closed; nobody backfilled).
        if wd >= 5:
            d += timedelta(days=1)
            continue
        # A scatter of weekdays are missing too (holidays / load failures).
        if rng.random() < 0.05:
            d += timedelta(days=1)
            continue
        # Day index for a slow drift.
        day_idx = (d - START_DATE).days
        for cur in covered:
            base = anchors[cur]
            # Smooth seasonal drift up to ~6% plus small daily noise.
            drift = 1.0 + 0.06 * np.sin(day_idx / 58.0) + float(rng.normal(0, 0.004))
            rate = round(base * drift, 6)
            rows.append({
                "RATE_ID": rate_id,
                "CURRENCY": cur,
                "RATE_DATE": d.date(),
                "RATE_TO_USD": rate,
                "SOURCE": "legacy_spreadsheet",
            })
            rate_id += 1
        d += timedelta(days=1)

    df = pd.DataFrame(rows)

    # A handful of rows are inverted (someone stored USD-per-local instead of
    # local-per-USD) — an internal inconsistency that makes the table unsafe to
    # trust blind. Left in as-emitted.
    if len(df):
        bad_idx = rng.choice(len(df), size=max(1, len(df) // 200), replace=False)
        df.loc[bad_idx, "RATE_TO_USD"] = (1.0 / df.loc[bad_idx, "RATE_TO_USD"]).round(6)

    return df


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_SALES": """
        CREATE OR REPLACE TABLE RAW_SALES (
            SALE_ID          NUMBER(18,0),
            STORE_ID         NUMBER(18,0),
            PRODUCT_CATEGORY VARCHAR,
            CHANNEL          VARCHAR,
            PAYMENT_METHOD   VARCHAR,
            QUANTITY         NUMBER(9,0),
            LOCAL_AMOUNT     NUMBER(18,2),
            LOCAL_CURRENCY   VARCHAR,
            SALE_STATUS      VARCHAR,
            SOLD_AT          TIMESTAMP_NTZ,
            BOOKED_AT        TIMESTAMP_NTZ
        )""",
    "RAW_STORES": """
        CREATE OR REPLACE TABLE RAW_STORES (
            STORE_ID           NUMBER(18,0),
            STORE_NAME         VARCHAR,
            COUNTRY            VARCHAR,
            LOCAL_CURRENCY     VARCHAR,
            TIMEZONE           VARCHAR,
            REPORTING_CALENDAR VARCHAR,
            OPENED_AT          TIMESTAMP_NTZ
        )""",
    "RAW_INVENTORY": """
        CREATE OR REPLACE TABLE RAW_INVENTORY (
            SNAPSHOT_ID      NUMBER(18,0),
            STORE_ID         NUMBER(18,0),
            PRODUCT_CATEGORY VARCHAR,
            UNITS_ON_HAND    NUMBER(12,0),
            LOCAL_UNIT_COST  NUMBER(18,2),
            LOCAL_CURRENCY   VARCHAR,
            SNAPSHOT_DATE    DATE
        )""",
    "RAW_CURRENCY_RATES": """
        CREATE OR REPLACE TABLE RAW_CURRENCY_RATES (
            RATE_ID     NUMBER(18,0),
            CURRENCY    VARCHAR,
            RATE_DATE   DATE,
            RATE_TO_USD NUMBER(18,6),
            SOURCE      VARCHAR
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

def build_tables(rng, n_rows):
    stores = generate_stores(rng)
    sales = generate_sales(rng, n_rows, stores)
    inventory = generate_inventory(rng, stores)
    rates = generate_currency_rates(rng)
    return {
        "RAW_SALES": sales,
        "RAW_STORES": stores,
        "RAW_INVENTORY": inventory,
        "RAW_CURRENCY_RATES": rates,
    }


def main():
    ap = argparse.ArgumentParser(description="Provision the GlobeMart raw sandbox.")
    ap.add_argument("--rows", type=int, default=60_000, help="number of sales rows to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (rows={args.rows:,}, seed={args.seed}) ...")
    tables = build_tables(rng, args.rows)

    print("\nRow counts:")
    for name, df in tables.items():
        print(f"  {name:<20} {len(df):>10,}")

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
