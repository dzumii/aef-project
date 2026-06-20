#!/usr/bin/env python3
"""
Northwind Atlas — HRIS source-system data export simulator.

Provisions the four raw HR tables (EMPLOYEES, DEPARTMENTS, PERFORMANCE_REVIEWS,
PAYROLL) into a Snowflake sandbox. This emulates the messy, as-emitted feed from
the client's people systems: rehired employees that appear under more than one
employment record, mid-career department transfers, conflicting active/terminated
status flags, partial-period payroll, and a review feed with missing review dates.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --employees 12000 --seed 42

Credentials are read from environment variables (see requirements.txt / README):
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

Nothing about the data flaws is documented here on purpose — this is meant to
read like a real HRIS export. Fellows: your job is to find what's wrong.
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

# The company has been hiring across this window. Keep it spanning several years
# so tenure, rehires and transfers are all exercised against a fixed "as-of" date.
HIRE_WINDOW_START = datetime(2016, 1, 1)
HIRE_WINDOW_END = datetime(2025, 12, 31)

# The reporting "as of" date. Tenure and headcount are always measured against
# this. Anyone terminated before it is inactive; anyone hired after it is ignored.
AS_OF_DATE = datetime(2025, 12, 31)

DEPARTMENTS = [
    ("ENG", "Engineering", "Product & Technology"),
    ("PRD", "Product", "Product & Technology"),
    ("DES", "Design", "Product & Technology"),
    ("SAL", "Sales", "Go-To-Market"),
    ("MKT", "Marketing", "Go-To-Market"),
    ("CSM", "Customer Success", "Go-To-Market"),
    ("FIN", "Finance", "Operations"),
    ("HRM", "People & HR", "Operations"),
    ("OPS", "Operations", "Operations"),
    ("LEG", "Legal", "Operations"),
]

JOB_LEVELS = ["IC1", "IC2", "IC3", "IC4", "M1", "M2", "M3"]
EMPLOYMENT_TYPES = ["full_time", "full_time", "full_time", "full_time", "part_time", "contractor"]
LOCATIONS = ["New York", "London", "Berlin", "Singapore", "Remote-US", "Remote-EU"]
REVIEW_RATINGS = ["exceeds", "meets", "meets", "meets", "below", "outstanding"]
PAY_CURRENCIES = ["USD", "USD", "USD", "GBP", "EUR", "SGD"]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_dates(rng, n, start, end):
    """n random dates uniformly between start and end (as datetimes)."""
    span = max(1, int((end - start).total_seconds()))
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_departments(rng):
    """One row per department. The reference dimension all the feeds point at."""
    rows = []
    for i, (code, name, division) in enumerate(DEPARTMENTS):
        rows.append({
            "DEPARTMENT_ID": 10 + i,
            "DEPARTMENT_CODE": code,
            "DEPARTMENT_NAME": name,
            "DIVISION": division,
            "COST_CENTER": f"CC-{1000 + i * 10}",
        })
    return pd.DataFrame(rows)


def generate_employees(rng, n_people, departments):
    """
    One row per EMPLOYMENT RECORD — not necessarily one row per person.

    A person who leaves and is later rehired comes back on a NEW employment
    record (new EMPLOYEE_ID), but their PERSON_ID is the same. A person who
    transfers between departments also gets a fresh employment record that
    supersedes the prior one. The feed therefore contains more rows than there
    are distinct humans, and tenure must be reasoned about per-person, not
    per-record.
    """
    # ------------------------------------------------------------------ #
    # GAP DRIVERS — tune these to move the headline tenure/attrition spread.
    # They are deliberately isolated and named so the metric is validatable.
    # ------------------------------------------------------------------ #
    REHIRE_RATE = 0.18          # share of people who left and were later rehired
    TRANSFER_RATE = 0.22        # share of (continuing) people who changed department
    BASE_TERMINATION_RATE = 0.34  # share of original stints that ended in a term
    # ------------------------------------------------------------------ #

    dept_ids = departments["DEPARTMENT_ID"].to_numpy()

    n_people = int(n_people)
    person_ids = np.arange(1_000_000, 1_000_000 + n_people)

    records = []
    employee_id = 200_000

    for pid in person_ids:
        # First (original) stint -------------------------------------------------
        hire_date = _random_dates(rng, 1, HIRE_WINDOW_START, HIRE_WINDOW_END)[0]
        home_dept = int(rng.choice(dept_ids))
        level_idx = int(rng.integers(0, len(JOB_LEVELS)))
        emp_type = str(rng.choice(EMPLOYMENT_TYPES))
        location = str(rng.choice(LOCATIONS))

        # Did this original stint terminate?
        terminated = rng.random() < BASE_TERMINATION_RATE
        if terminated:
            # Tenure of the first stint, in days, before they left.
            stint_days = int(rng.integers(120, 1500))
            term_date = hire_date + timedelta(days=stint_days)
            if term_date > AS_OF_DATE:
                term_date = None
                terminated = False
        if not terminated:
            term_date = None

        # The original employment record.
        first_emp_id = employee_id
        records.append({
            "EMPLOYEE_ID": employee_id,
            "PERSON_ID": int(pid),
            "FULL_NAME": f"Employee {int(pid) - 1_000_000:05d}",
            "DEPARTMENT_ID": home_dept,
            "JOB_LEVEL": JOB_LEVELS[level_idx],
            "EMPLOYMENT_TYPE": emp_type,
            "LOCATION": location,
            "HIRE_DATE": hire_date,
            "TERMINATION_DATE": term_date,
            # Status flag as the HRIS stamps it. NOTE: this is set independently
            # of TERMINATION_DATE and the two do not always agree.
            "EMPLOYMENT_STATUS": "terminated" if terminated else "active",
            "PRIOR_EMPLOYEE_ID": None,
        })
        employee_id += 1

        last_emp_id = first_emp_id
        last_dept = home_dept
        last_active_from = term_date if terminated else hire_date
        currently_terminated = terminated

        # Department transfer (only for people still employed) --------------------
        if not currently_terminated and rng.random() < TRANSFER_RATE:
            # The transfer closes the old record and opens a new one in a new dept.
            transfer_date = hire_date + timedelta(days=int(rng.integers(180, 2000)))
            if transfer_date < AS_OF_DATE:
                # Close the prior record: stamp a termination_date == transfer_date
                # and flip status to "transferred". This is exactly how the HRIS
                # represents an internal move — as an end-date on the old row.
                for r in records:
                    if r["EMPLOYEE_ID"] == last_emp_id:
                        r["TERMINATION_DATE"] = transfer_date
                        r["EMPLOYMENT_STATUS"] = "transferred"
                        break
                new_dept = int(rng.choice([d for d in dept_ids if d != last_dept]))
                records.append({
                    "EMPLOYEE_ID": employee_id,
                    "PERSON_ID": int(pid),
                    "FULL_NAME": f"Employee {int(pid) - 1_000_000:05d}",
                    "DEPARTMENT_ID": new_dept,
                    "JOB_LEVEL": JOB_LEVELS[min(level_idx + 1, len(JOB_LEVELS) - 1)],
                    "EMPLOYMENT_TYPE": emp_type,
                    "LOCATION": location,
                    # The new record's HIRE_DATE is the transfer date — so a naive
                    # tenure calc on this row resets the clock to the move.
                    "HIRE_DATE": transfer_date,
                    "TERMINATION_DATE": None,
                    "EMPLOYMENT_STATUS": "active",
                    "PRIOR_EMPLOYEE_ID": last_emp_id,
                })
                last_emp_id = employee_id
                last_dept = new_dept
                employee_id += 1

        # Rehire (only for people whose original stint terminated) ---------------
        if currently_terminated and term_date is not None and rng.random() < REHIRE_RATE:
            gap_days = int(rng.choice([45, 90, 180, 365, 720], p=[0.18, 0.27, 0.30, 0.15, 0.10]))
            rehire_date = term_date + timedelta(days=gap_days)
            if rehire_date < AS_OF_DATE:
                new_dept = int(rng.choice(dept_ids))
                # Does the second stint also end before the as-of date?
                rehire_terminated = rng.random() < (BASE_TERMINATION_RATE * 0.6)
                if rehire_terminated:
                    s2 = int(rng.integers(120, 1200))
                    rehire_term = rehire_date + timedelta(days=s2)
                    if rehire_term > AS_OF_DATE:
                        rehire_term = None
                        rehire_terminated = False
                else:
                    rehire_term = None
                records.append({
                    "EMPLOYEE_ID": employee_id,
                    "PERSON_ID": int(pid),
                    "FULL_NAME": f"Employee {int(pid) - 1_000_000:05d}",
                    "DEPARTMENT_ID": new_dept,
                    "JOB_LEVEL": JOB_LEVELS[level_idx],
                    "EMPLOYMENT_TYPE": str(rng.choice(EMPLOYMENT_TYPES)),
                    "LOCATION": str(rng.choice(LOCATIONS)),
                    # Rehire HIRE_DATE is the return date — the gap (time away) is
                    # invisible unless you reason across the person's records.
                    "HIRE_DATE": rehire_date,
                    "TERMINATION_DATE": rehire_term,
                    "EMPLOYMENT_STATUS": "terminated" if rehire_terminated else "active",
                    "PRIOR_EMPLOYEE_ID": first_emp_id,
                })
                employee_id += 1

    df = pd.DataFrame(records)

    # A small population of duplicate employment records: the HRIS migration in
    # 2021 double-loaded a slice of rows under a fresh EMPLOYEE_ID with identical
    # person/department/hire details. Left in as-emitted.
    n_dupe = max(1, len(df) // 400)
    dupe_src = df.sample(n=n_dupe, random_state=int(rng.integers(0, 1_000_000)))
    dupes = dupe_src.copy()
    dupes["EMPLOYEE_ID"] = np.arange(employee_id, employee_id + len(dupes))
    df = pd.concat([df, dupes], ignore_index=True)

    # A handful of records carry a conflicting status: TERMINATION_DATE is null
    # yet EMPLOYMENT_STATUS reads "terminated" (status feed lagged the date feed).
    conflict_idx = rng.choice(len(df), size=max(1, len(df) // 300), replace=False)
    for i in conflict_idx:
        if df.at[i, "TERMINATION_DATE"] is None or pd.isna(df.at[i, "TERMINATION_DATE"]):
            df.at[i, "EMPLOYMENT_STATUS"] = "terminated"

    return df


def generate_performance_reviews(rng, employees):
    """
    One row per performance review. Reviews reference an employment record. A
    slice of reviews are missing their REVIEW_DATE (the form was submitted before
    the cycle close-date job ran), and a few are duplicated submissions.
    """
    rows = []
    review_id = 800_000

    for e in employees.itertuples(index=False):
        hire = e.HIRE_DATE
        end = e.TERMINATION_DATE if (e.TERMINATION_DATE is not None and not pd.isna(e.TERMINATION_DATE)) else AS_OF_DATE
        if end <= hire:
            continue
        # Roughly one review per completed year of the stint.
        years = max(0, int((end - hire).days // 365))
        n_reviews = min(years, 5)
        for k in range(n_reviews):
            review_date = hire + timedelta(days=365 * (k + 1) + int(rng.integers(-20, 20)))
            if review_date > AS_OF_DATE:
                continue
            rating = str(rng.choice(REVIEW_RATINGS))
            # The cycle-close job sometimes failed to stamp a date.
            stamped_date = None if rng.random() < 0.07 else review_date
            row = {
                "REVIEW_ID": review_id,
                "EMPLOYEE_ID": e.EMPLOYEE_ID,
                "PERSON_ID": e.PERSON_ID,
                "REVIEW_PERIOD": review_date.year,
                "RATING": rating,
                "REVIEW_SCORE": float(np.round(rng.uniform(1.0, 5.0), 2)),
                "REVIEWER_ID": int(rng.integers(200_000, 260_000)),
                "REVIEW_DATE": stamped_date,
            }
            rows.append(row)
            review_id += 1
            # Occasional duplicate submission of the same review.
            if rng.random() < 0.02:
                dup = dict(row)
                dup["REVIEW_ID"] = review_id
                rows.append(dup)
                review_id += 1

    return pd.DataFrame(rows)


def generate_payroll(rng, employees):
    """
    One row per employee per monthly pay period in which the employment record
    was active. Multi-currency (the company runs local payroll). Some periods are
    PARTIAL (prorated) when a stint started or ended mid-month, and a slice of
    cancelled runs were re-issued, producing duplicate period rows.
    """
    rows = []
    payroll_id = 600_000

    for e in employees.itertuples(index=False):
        hire = e.HIRE_DATE
        end = e.TERMINATION_DATE if (e.TERMINATION_DATE is not None and not pd.isna(e.TERMINATION_DATE)) else AS_OF_DATE
        if end <= hire:
            continue
        currency = str(rng.choice(PAY_CURRENCIES))
        annual = float(np.round(rng.uniform(45_000, 220_000), 2))
        monthly = np.round(annual / 12.0, 2)

        # Walk monthly periods from hire to end (cap for performance).
        period = datetime(hire.year, hire.month, 1)
        n_periods = 0
        while period <= end and n_periods < 130:
            # Partial first/last month?
            partial = (period.year == hire.year and period.month == hire.month) or \
                      (period.year == end.year and period.month == end.month)
            gross = float(np.round(monthly * (rng.uniform(0.3, 0.95) if partial else 1.0), 2))
            row = {
                "PAYROLL_ID": payroll_id,
                "EMPLOYEE_ID": e.EMPLOYEE_ID,
                "PERSON_ID": e.PERSON_ID,
                "PAY_PERIOD": period,
                "GROSS_PAY": gross,
                "CURRENCY": currency,
                "IS_PARTIAL_PERIOD": bool(partial),
                "PAID_AT": period + timedelta(days=int(rng.integers(25, 31))),
            }
            rows.append(row)
            payroll_id += 1
            # A cancelled-and-reissued run duplicates the period for that employee.
            if rng.random() < 0.01:
                dup = dict(row)
                dup["PAYROLL_ID"] = payroll_id
                rows.append(dup)
                payroll_id += 1
            # advance one month
            if period.month == 12:
                period = datetime(period.year + 1, 1, 1)
            else:
                period = datetime(period.year, period.month + 1, 1)
            n_periods += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_DEPARTMENTS": """
        CREATE OR REPLACE TABLE RAW_DEPARTMENTS (
            DEPARTMENT_ID   NUMBER(18,0),
            DEPARTMENT_CODE VARCHAR,
            DEPARTMENT_NAME VARCHAR,
            DIVISION        VARCHAR,
            COST_CENTER     VARCHAR
        )""",
    "RAW_EMPLOYEES": """
        CREATE OR REPLACE TABLE RAW_EMPLOYEES (
            EMPLOYEE_ID       NUMBER(18,0),
            PERSON_ID         NUMBER(18,0),
            FULL_NAME         VARCHAR,
            DEPARTMENT_ID     NUMBER(18,0),
            JOB_LEVEL         VARCHAR,
            EMPLOYMENT_TYPE   VARCHAR,
            LOCATION          VARCHAR,
            HIRE_DATE         TIMESTAMP_NTZ,
            TERMINATION_DATE  TIMESTAMP_NTZ,
            EMPLOYMENT_STATUS VARCHAR,
            PRIOR_EMPLOYEE_ID NUMBER(18,0)
        )""",
    "RAW_PERFORMANCE_REVIEWS": """
        CREATE OR REPLACE TABLE RAW_PERFORMANCE_REVIEWS (
            REVIEW_ID     NUMBER(18,0),
            EMPLOYEE_ID   NUMBER(18,0),
            PERSON_ID     NUMBER(18,0),
            REVIEW_PERIOD NUMBER(9,0),
            RATING        VARCHAR,
            REVIEW_SCORE  NUMBER(5,2),
            REVIEWER_ID   NUMBER(18,0),
            REVIEW_DATE   TIMESTAMP_NTZ
        )""",
    "RAW_PAYROLL": """
        CREATE OR REPLACE TABLE RAW_PAYROLL (
            PAYROLL_ID        NUMBER(18,0),
            EMPLOYEE_ID       NUMBER(18,0),
            PERSON_ID         NUMBER(18,0),
            PAY_PERIOD        TIMESTAMP_NTZ,
            GROSS_PAY         NUMBER(12,2),
            CURRENCY          VARCHAR,
            IS_PARTIAL_PERIOD BOOLEAN,
            PAID_AT           TIMESTAMP_NTZ
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

def build_tables(rng, n_people):
    departments = generate_departments(rng)
    employees = generate_employees(rng, n_people, departments)
    reviews = generate_performance_reviews(rng, employees)
    payroll = generate_payroll(rng, employees)
    return {
        "RAW_DEPARTMENTS": departments,
        "RAW_EMPLOYEES": employees,
        "RAW_PERFORMANCE_REVIEWS": reviews,
        "RAW_PAYROLL": payroll,
    }


def main():
    ap = argparse.ArgumentParser(description="Provision the Northwind Atlas raw HR sandbox.")
    ap.add_argument("--employees", type=int, default=12_000,
                    help="number of distinct PEOPLE to generate (records will exceed this)")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (people={args.employees:,}, seed={args.seed}) ...")
    tables = build_tables(rng, args.employees)

    print("\nRow counts:")
    for name, df in tables.items():
        print(f"  {name:<26} {len(df):>10,}")

    if args.dry_run:
        emp = tables["RAW_EMPLOYEES"]
        print(f"\n  distinct people   : {emp['PERSON_ID'].nunique():,}")
        print(f"  employment records: {len(emp):,}")
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
