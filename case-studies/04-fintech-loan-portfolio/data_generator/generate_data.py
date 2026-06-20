#!/usr/bin/env python3
"""
LendWell — source-system data export simulator.

Provisions the four raw operational tables (APPLICATIONS, LOANS, REPAYMENTS,
DEFAULTS) into a Snowflake sandbox. This emulates the messy, as-emitted feed
from the client's lending core and servicing systems: retried/partial
repayments, late instalments, loans that were restructured (resetting their
servicing clock), and a defaults feed that the servicing team maintains by
hand and does not always keep in step with what the repayment ledger shows.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --loans 40000 --seed 42

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

# The book is observed as at this reporting date. Loans are originated across
# the prior window so that a spread of them are mid-term on the as-of date and
# the days-past-due maths is exercised across month boundaries.
AS_OF_DATE = datetime(2025, 6, 30)
ORIGINATION_START = datetime(2023, 7, 1)
ORIGINATION_END = datetime(2025, 5, 31)

CURRENCIES = ["NGN", "NGN", "NGN", "NGN", "USD", "GHS"]  # mostly local currency
PRODUCTS = ["payday", "payday", "sme_working_capital", "asset_finance", "salary_advance"]
CHANNELS = ["mobile_app", "mobile_app", "ussd", "agent", "web"]
DECLINE_REASONS = ["thin_file", "affordability", "fraud_flag", "policy_age", "existing_arrears"]
DEFAULT_REASONS = ["non_payment", "skip", "deceased", "fraud", "bankruptcy"]


# --------------------------------------------------------------------------- #
# Gap drivers — the five isolated knobs that govern the headline business pain #
# (reported default rate UNDERSTATES true portfolio-at-risk). Tune these to    #
# make a harder/easier cohort variant; they are validated at seed 42 in the   #
# instructor notes. Everything else flows from them.                          #
# --------------------------------------------------------------------------- #

# (1) Baseline share of funded loans that become STRESSED (fall materially
#     behind at some point). Primary driver of TRUE portfolio-at-risk.
GAP_P_STRESSED = 0.11

# (2) Of stressed loans, the share the servicer RESTRUCTURES rather than letting
#     roll into formal default. Restructuring resets the DPD clock — the
#     mechanism that hides risk from the reported book.
GAP_P_RESTRUCTURE_WHEN_STRESSED = 0.55

# (3) Probability collections actually BOOKS a default for a stressed,
#     NON-restructured loan in the defaults register (Finance's reporting source).
GAP_P_BOOK_DEFAULT_IF_STRESSED = 0.82

# (4) Probability collections books a default for a RESTRUCTURED loan that has
#     re-defaulted. Near zero — the reporting blind spot.
GAP_P_BOOK_DEFAULT_IF_RESTRUCTURED = 0.06

# (5) Share of repayment postings that are PARTIAL (short of the scheduled
#     instalment). A repayment-pipeline data-quality wrinkle, not a default
#     signal — fellows must not treat a short-pay as a missed instalment.
GAP_P_PARTIAL_POSTING = 0.22


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_applications(rng, n_apps):
    """
    One row per loan application. Only a share are approved and go on to become
    a funded loan; the rest are declined or still pending. Approved applications
    are the parents of the LOANS table.
    """
    app_ids = np.arange(300_000, 300_000 + n_apps)
    customer_ids = rng.integers(1, max(2, n_apps // 3), size=n_apps)
    submitted = _random_datetimes(rng, n_apps, ORIGINATION_START, ORIGINATION_END)

    # Requested principal: log-normal-ish, rounded.
    requested = np.round(rng.lognormal(mean=11.0, sigma=0.7, size=n_apps), 2)
    requested = np.clip(requested, 5_000.0, 5_000_000.0)

    decision = rng.choice(
        ["approved", "declined", "pending"],
        size=n_apps,
        p=[0.62, 0.30, 0.08],
    )

    # decided_at is normally >= submitted_at ...
    decided = [s + timedelta(hours=int(rng.integers(1, 480))) for s in submitted]

    df = pd.DataFrame({
        "APPLICATION_ID": app_ids,
        "CUSTOMER_ID": customer_ids,
        "PRODUCT_TYPE": rng.choice(PRODUCTS, size=n_apps),
        "CHANNEL": rng.choice(CHANNELS, size=n_apps),
        "REQUESTED_AMOUNT": requested,
        "CURRENCY": rng.choice(CURRENCIES, size=n_apps),
        "DECISION": decision,
        "DECLINE_REASON": [
            rng.choice(DECLINE_REASONS) if d == "declined" else None for d in decision
        ],
        "SUBMITTED_AT": submitted,
        "DECIDED_AT": decided,
    })

    # ... except for a small population where the underwriting system clock
    # skewed and decided_at lands BEFORE submitted_at. Left in as-emitted.
    skew_idx = rng.choice(n_apps, size=max(1, n_apps // 500), replace=False)
    df.loc[skew_idx, "DECIDED_AT"] = [
        s - timedelta(hours=int(rng.integers(1, 48))) for s in df.loc[skew_idx, "SUBMITTED_AT"]
    ]
    return df


def generate_loans(rng, applications):
    """
    One row per funded loan, originated from an approved application. The
    servicing system tracks the CURRENT state of the loan. When a loan is
    restructured, the servicer re-papers it onto a fresh schedule and stamps a
    new origination/first-due date — the prior arrears history is not carried
    forward on the loan record itself.
    """
    P_RESTRUCTURE_WHEN_STRESSED = GAP_P_RESTRUCTURE_WHEN_STRESSED
    P_STRESSED = GAP_P_STRESSED

    approved = applications[applications["DECISION"] == "approved"]

    rows = []
    loan_id = 600_000
    for a in approved.itertuples(index=False):
        # Funded amount tracks requested but is occasionally trimmed by policy.
        funded = float(a.REQUESTED_AMOUNT)
        if rng.random() < 0.18:
            funded = np.round(funded * rng.uniform(0.5, 0.95), 2)

        term_months = int(rng.choice([3, 6, 6, 12, 12, 24], p=[0.18, 0.24, 0.20, 0.18, 0.12, 0.08]))
        apr = float(np.round(rng.uniform(0.18, 0.60), 4))

        # Origination shortly after the decision.
        originated = a.DECIDED_AT + timedelta(days=int(rng.integers(0, 7)))
        if originated > AS_OF_DATE:
            originated = AS_OF_DATE - timedelta(days=int(rng.integers(1, 30)))

        # Is this loan stressed at some point?
        stressed = rng.random() < P_STRESSED

        restructured = False
        restructure_at = None
        original_first_due = originated + timedelta(days=30)
        first_due = original_first_due

        if stressed and rng.random() < P_RESTRUCTURE_WHEN_STRESSED:
            # The servicer restructured the loan: a fresh schedule is stamped on,
            # moving the first-due date forward and clearing the visible clock.
            restructured = True
            months_in = int(rng.integers(2, max(3, term_months)))
            restructure_at = originated + timedelta(days=30 * months_in)
            if restructure_at > AS_OF_DATE:
                restructure_at = AS_OF_DATE - timedelta(days=int(rng.integers(1, 20)))
            # New schedule's first due sits AFTER the restructure — clock reset.
            first_due = restructure_at + timedelta(days=30)

        # Current servicing status as the core system reports it. A restructured
        # loan is re-flagged "current" / "restructured" regardless of the arrears
        # that triggered the restructure.
        if restructured:
            current_status = "restructured"
        elif stressed:
            current_status = rng.choice(["active", "delinquent", "active"])
        else:
            current_status = rng.choice(["active", "active", "closed"])

        rows.append({
            "LOAN_ID": loan_id,
            "APPLICATION_ID": a.APPLICATION_ID,
            "CUSTOMER_ID": a.CUSTOMER_ID,
            "PRODUCT_TYPE": a.PRODUCT_TYPE,
            "PRINCIPAL_AMOUNT": funded,
            "CURRENCY": a.CURRENCY,
            "INTEREST_RATE_APR": apr,
            "TERM_MONTHS": term_months,
            "LOAN_STATUS": current_status,
            "ORIGINATED_AT": originated,
            "FIRST_DUE_DATE": first_due,
            "RESTRUCTURED_AT": restructure_at,
            # private bookkeeping, NOT emitted to Snowflake — used to drive the
            # downstream repayment/default generators with a consistent ground truth.
            "PV_STRESSED": stressed,
            "PV_RESTRUCTURED": restructured,
            "PV_ORIGINAL_FIRST_DUE": original_first_due,
            "PV_TERM_MONTHS": term_months,
        })
        loan_id += 1

    return pd.DataFrame(rows)


def generate_repayments(rng, loans):
    """
    One row per repayment EVENT against a loan's schedule. The servicing gateway
    logs each posting, including partial postings and the occasional reversal/
    re-post, so a single scheduled instalment can map to several rows. Stressed
    loans miss or short-pay instalments; their most recent instalments are the
    ones running past due as at the reporting date.
    """
    # For a STRESSED loan, how far past due (in days) the oldest unpaid
    # instalment runs as at the reporting date. This is what pushes a loan over
    # the 30/90-day PAR thresholds in TRUTH terms.
    STRESSED_DPD_CHOICES = np.array([35, 45, 70, 95, 130, 180])
    STRESSED_DPD_WEIGHTS = np.array([0.16, 0.16, 0.20, 0.18, 0.18, 0.12])
    P_PARTIAL_POSTING = GAP_P_PARTIAL_POSTING
    STRESSED_DPD_WEIGHTS = STRESSED_DPD_WEIGHTS / STRESSED_DPD_WEIGHTS.sum()

    rows = []
    repayment_id = 800_000

    for l in loans.itertuples(index=False):
        term = int(l.PV_TERM_MONTHS)
        instalment = np.round(
            float(l.PRINCIPAL_AMOUNT) * (1.0 + float(l.INTEREST_RATE_APR) * (term / 12.0)) / term, 2
        )
        sched_start = l.PV_ORIGINAL_FIRST_DUE

        # How many instalments have come due on or before the reporting date.
        months_elapsed = (AS_OF_DATE.year - sched_start.year) * 12 + (AS_OF_DATE.month - sched_start.month) + 1
        n_due = int(np.clip(months_elapsed, 0, term))

        if n_due <= 0:
            continue

        if l.PV_STRESSED:
            # Pick how far the oldest unpaid instalment is past due, then back
            # out how many of the most-recent instalments are unpaid.
            dpd = int(rng.choice(STRESSED_DPD_CHOICES, p=STRESSED_DPD_WEIGHTS))
            n_missed = int(np.clip(round(dpd / 30.0), 1, n_due))
            n_paid = n_due - n_missed
        else:
            n_paid = n_due  # healthy loans are current through the schedule

        for i in range(n_due):
            due_date = sched_start + timedelta(days=30 * i)
            if i < n_paid:
                paid_on = due_date + timedelta(days=int(rng.integers(-2, 6)))
                if paid_on > AS_OF_DATE:
                    paid_on = AS_OF_DATE
                # Partial vs full posting.
                if rng.random() < P_PARTIAL_POSTING:
                    amount = np.round(instalment * rng.uniform(0.30, 0.85), 2)
                    status = "partial"
                else:
                    amount = instalment
                    status = "posted"

                row = {
                    "REPAYMENT_ID": repayment_id,
                    "LOAN_ID": l.LOAN_ID,
                    "INSTALMENT_NO": i + 1,
                    "SCHEDULED_AMOUNT": instalment,
                    "AMOUNT_PAID": amount,
                    "CURRENCY": l.CURRENCY,
                    "PAYMENT_STATUS": status,
                    "DUE_DATE": due_date,
                    "PAID_AT": paid_on,
                }
                rows.append(row)
                repayment_id += 1

                # The gateway occasionally double-posts a settled repayment
                # (webhook delivered twice). Same loan/instalment/amount, new id.
                if rng.random() < 0.02:
                    dup = dict(row)
                    dup["REPAYMENT_ID"] = repayment_id
                    dup["PAID_AT"] = paid_on + timedelta(minutes=int(rng.integers(1, 30)))
                    rows.append(dup)
                    repayment_id += 1
            else:
                # Instalment is due but unpaid as at the reporting date: a missed
                # row is still written by the scheduler with a null PAID_AT.
                rows.append({
                    "REPAYMENT_ID": repayment_id,
                    "LOAN_ID": l.LOAN_ID,
                    "INSTALMENT_NO": i + 1,
                    "SCHEDULED_AMOUNT": instalment,
                    "AMOUNT_PAID": 0.0,
                    "CURRENCY": l.CURRENCY,
                    "PAYMENT_STATUS": "missed",
                    "DUE_DATE": due_date,
                    "PAID_AT": None,
                })
                repayment_id += 1

    return pd.DataFrame(rows)


def generate_defaults(rng, loans):
    """
    One row per loan the servicing team has FORMALLY flagged as defaulted in the
    defaults register. This register is maintained by the collections team and
    lags the repayment ledger: notably, loans that were restructured are taken
    OFF the watch-list and are rarely written into the register even when they
    later run past due again. This is the register Finance reports PAR from.
    """
    P_BOOK_DEFAULT_IF_STRESSED_NOT_RESTRUCTURED = GAP_P_BOOK_DEFAULT_IF_STRESSED
    P_BOOK_DEFAULT_IF_RESTRUCTURED = GAP_P_BOOK_DEFAULT_IF_RESTRUCTURED

    rows = []
    default_id = 950_000

    for l in loans.itertuples(index=False):
        if not l.PV_STRESSED:
            continue

        if l.PV_RESTRUCTURED:
            book = rng.random() < P_BOOK_DEFAULT_IF_RESTRUCTURED
        else:
            book = rng.random() < P_BOOK_DEFAULT_IF_STRESSED_NOT_RESTRUCTURED

        if not book:
            continue

        flagged = l.ORIGINATED_AT + timedelta(days=int(rng.integers(60, 300)))
        if flagged > AS_OF_DATE:
            flagged = AS_OF_DATE - timedelta(days=int(rng.integers(1, 15)))

        outstanding = np.round(float(l.PRINCIPAL_AMOUNT) * rng.uniform(0.30, 0.95), 2)

        rows.append({
            "DEFAULT_ID": default_id,
            "LOAN_ID": l.LOAN_ID,
            "DEFAULT_REASON": rng.choice(DEFAULT_REASONS, p=[0.70, 0.12, 0.05, 0.08, 0.05]),
            "OUTSTANDING_AT_DEFAULT": outstanding,
            "CURRENCY": l.CURRENCY,
            "DEFAULT_STATUS": rng.choice(["open", "open", "in_recovery", "written_off"]),
            "FLAGGED_AT": flagged,
        })
        default_id += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_APPLICATIONS": """
        CREATE OR REPLACE TABLE RAW_APPLICATIONS (
            APPLICATION_ID   NUMBER(18,0),
            CUSTOMER_ID      NUMBER(18,0),
            PRODUCT_TYPE     VARCHAR,
            CHANNEL          VARCHAR,
            REQUESTED_AMOUNT NUMBER(18,2),
            CURRENCY         VARCHAR,
            DECISION         VARCHAR,
            DECLINE_REASON   VARCHAR,
            SUBMITTED_AT     TIMESTAMP_NTZ,
            DECIDED_AT       TIMESTAMP_NTZ
        )""",
    "RAW_LOANS": """
        CREATE OR REPLACE TABLE RAW_LOANS (
            LOAN_ID           NUMBER(18,0),
            APPLICATION_ID    NUMBER(18,0),
            CUSTOMER_ID       NUMBER(18,0),
            PRODUCT_TYPE      VARCHAR,
            PRINCIPAL_AMOUNT  NUMBER(18,2),
            CURRENCY          VARCHAR,
            INTEREST_RATE_APR NUMBER(9,4),
            TERM_MONTHS       NUMBER(9,0),
            LOAN_STATUS       VARCHAR,
            ORIGINATED_AT     TIMESTAMP_NTZ,
            FIRST_DUE_DATE    TIMESTAMP_NTZ,
            RESTRUCTURED_AT   TIMESTAMP_NTZ
        )""",
    "RAW_REPAYMENTS": """
        CREATE OR REPLACE TABLE RAW_REPAYMENTS (
            REPAYMENT_ID     NUMBER(18,0),
            LOAN_ID          NUMBER(18,0),
            INSTALMENT_NO    NUMBER(9,0),
            SCHEDULED_AMOUNT NUMBER(18,2),
            AMOUNT_PAID      NUMBER(18,2),
            CURRENCY         VARCHAR,
            PAYMENT_STATUS   VARCHAR,
            DUE_DATE         TIMESTAMP_NTZ,
            PAID_AT          TIMESTAMP_NTZ
        )""",
    "RAW_DEFAULTS": """
        CREATE OR REPLACE TABLE RAW_DEFAULTS (
            DEFAULT_ID             NUMBER(18,0),
            LOAN_ID                NUMBER(18,0),
            DEFAULT_REASON         VARCHAR,
            OUTSTANDING_AT_DEFAULT NUMBER(18,2),
            CURRENCY               VARCHAR,
            DEFAULT_STATUS         VARCHAR,
            FLAGGED_AT             TIMESTAMP_NTZ
        )""",
}

# Bookkeeping columns prefixed with "_" never get loaded.
_PRIVATE_COLS = ["PV_STRESSED", "PV_RESTRUCTURED", "PV_ORIGINAL_FIRST_DUE", "PV_TERM_MONTHS"]


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

def build_tables(rng):
    """Generate all four feeds and strip private bookkeeping columns."""
    applications = generate_applications(rng, build_tables.n_apps)
    loans = generate_loans(rng, applications)
    repayments = generate_repayments(rng, loans)
    defaults = generate_defaults(rng, loans)

    loans_out = loans.drop(columns=[c for c in _PRIVATE_COLS if c in loans.columns])

    return {
        "RAW_APPLICATIONS": applications,
        "RAW_LOANS": loans_out,
        "RAW_REPAYMENTS": repayments,
        "RAW_DEFAULTS": defaults,
    }, loans  # return loans WITH bookkeeping for validation


def main():
    ap = argparse.ArgumentParser(description="Provision the LendWell raw sandbox.")
    ap.add_argument("--loans", type=int, default=40_000,
                    help="approximate number of FUNDED loans to target (drives application count)")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    # ~62% of applications approve into a funded loan; scale applications so the
    # funded-loan count lands near --loans.
    build_tables.n_apps = int(args.loans / 0.62)

    print(f"Generating data (target funded loans={args.loans:,}, seed={args.seed}) ...")
    tables, _loans_full = build_tables(rng)

    print("\nRow counts:")
    for name, df in tables.items():
        print(f"  {name:<18} {len(df):>10,}")

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
