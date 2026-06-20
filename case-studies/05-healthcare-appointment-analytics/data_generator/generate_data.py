#!/usr/bin/env python3
"""
CareGrid Health Partners — source-system data export simulator.

Provisions the four raw operational tables (PATIENTS, DOCTORS, APPOINTMENTS,
BILLING) into a Snowflake sandbox. This emulates the messy, as-emitted feed from
the client's scheduling and revenue-cycle systems across several clinic
locations: appointments that were rescheduled or cancelled but still carry a
missing/absent flag, reschedule chains that point back at a prior appointment,
duplicate booking rows, null check-in timestamps, and a billing feed that does
not always line up with the visit it belongs to.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --appointments 60000 --seed 42

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
# boundaries so the cross-period reschedule-chain problem is exercised.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

LOCATIONS = ["riverside", "northgate", "westpark", "central", "lakeview"]
SPECIALTIES = [
    "family_medicine", "pediatrics", "cardiology", "dermatology",
    "orthopedics", "obgyn", "endocrinology",
]
APPOINTMENT_TYPES = ["new_patient", "follow_up", "annual_physical", "procedure", "telehealth"]
INSURANCE_PLANS = ["ppo_a", "ppo_b", "hmo_c", "medicare", "medicaid", "self_pay"]
CANCEL_REASONS = ["patient_request", "clinic_cancelled", "provider_unavailable", "weather"]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_doctors(rng, n_doctors=80):
    """One row per provider."""
    doctor_ids = np.arange(3_000, 3_000 + n_doctors)
    df = pd.DataFrame({
        "DOCTOR_ID": doctor_ids,
        "PROVIDER_NAME": [f"provider_{i}" for i in doctor_ids],
        "SPECIALTY": rng.choice(SPECIALTIES, size=n_doctors),
        "PRIMARY_LOCATION": rng.choice(LOCATIONS, size=n_doctors),
        "HIRED_AT": _random_datetimes(rng, n_doctors,
                                      datetime(2018, 1, 1), datetime(2023, 12, 31)),
        "IS_ACTIVE": rng.choice([True, False], size=n_doctors, p=[0.9, 0.1]),
    })
    return df


def generate_patients(rng, n_patients):
    """One row per patient."""
    patient_ids = np.arange(50_000, 50_000 + n_patients)
    registered = _random_datetimes(rng, n_patients,
                                   datetime(2019, 1, 1), datetime(2024, 11, 30))
    df = pd.DataFrame({
        "PATIENT_ID": patient_ids,
        "BIRTH_YEAR": rng.integers(1940, 2020, size=n_patients),
        "SEX": rng.choice(["F", "M", "X"], size=n_patients, p=[0.51, 0.47, 0.02]),
        "INSURANCE_PLAN": rng.choice(INSURANCE_PLANS, size=n_patients),
        "HOME_LOCATION": rng.choice(LOCATIONS, size=n_patients),
        "REGISTERED_AT": registered,
    })
    return df


def generate_appointments(rng, n_appointments, patients, doctors):
    """
    One row per scheduled appointment slot. The scheduling system writes a row
    when a slot is booked and updates STATUS as the visit's lifecycle plays out.
    A reschedule does not edit the original row — it books a NEW slot and the
    original keeps whatever terminal status the front desk applied to it.
    """
    # ---------------------------------------------------------------------- #
    # GAP DRIVERS — tune these to make the headline metric harder/easier.    #
    # The whole engagement turns on the fact that the front desk does not    #
    # cleanly separate "patient never showed" from "patient moved the visit" #
    # or "the clinic cancelled". These probabilities set how badly the naive #
    # no-show rate is inflated relative to the strict (true) no-show rate.   #
    # ---------------------------------------------------------------------- #
    BASE_NO_SHOW_RATE = 0.13       # share of kept-intent visits the patient truly misses
    RESCHEDULE_RATE = 0.16         # share of visits the patient moves to a later slot
    CANCEL_RATE = 0.11             # share of visits cancelled ahead of time (patient or clinic)
    # Of the appointments the patient actually RESCHEDULED, this share were
    # closed out by the front desk with a "no_show"/"missed" flag instead of a
    # proper "rescheduled" status (the staff marked the empty chair, not the move).
    RESCHEDULE_MISFLAG_RATE = 0.50
    # Of the appointments that were CANCELLED, this share were likewise closed
    # out as "no_show"/"missed" (late cancels keyed as missed visits).
    CANCEL_MISFLAG_RATE = 0.26
    # ---------------------------------------------------------------------- #

    patient_ids = patients["PATIENT_ID"].to_numpy()
    doctor_ids = doctors["DOCTOR_ID"].to_numpy()
    location_by_doctor = doctors.set_index("DOCTOR_ID")["PRIMARY_LOCATION"].to_dict()

    scheduled = _random_datetimes(rng, n_appointments, START_DATE, END_DATE)

    rows = []
    appointment_id = 800_000

    for i in range(n_appointments):
        appt_id = appointment_id
        appointment_id += 1

        pid = int(rng.choice(patient_ids))
        did = int(rng.choice(doctor_ids))
        loc = location_by_doctor[did]
        sched_for = scheduled[i]
        booked_at = sched_for - timedelta(days=int(rng.integers(1, 30)))
        appt_type = rng.choice(APPOINTMENT_TYPES)

        # Decide the underlying lifecycle outcome for this slot.
        roll = rng.random()
        if roll < CANCEL_RATE:
            outcome = "cancelled"
        elif roll < CANCEL_RATE + RESCHEDULE_RATE:
            outcome = "rescheduled"
        else:
            # Remaining visits were "kept intent": patient meant to attend.
            outcome = "no_show" if rng.random() < BASE_NO_SHOW_RATE else "attended"

        checked_in_at = None
        checkout_at = None
        cancel_reason = None
        rescheduled_to_id = None

        if outcome == "attended":
            status = "attended"
            checked_in_at = sched_for + timedelta(minutes=int(rng.integers(-10, 25)))
            checkout_at = checked_in_at + timedelta(minutes=int(rng.integers(10, 60)))

        elif outcome == "no_show":
            # A genuine missed visit: booked, never arrived. The front desk keys
            # one of a few near-synonymous flags depending on the location's habit.
            status = rng.choice(["no_show", "missed", "no-show"], p=[0.6, 0.25, 0.15])

        elif outcome == "cancelled":
            cancel_reason = rng.choice(CANCEL_REASONS)
            # Most cancels are keyed as cancelled; a slice get closed as missed.
            if rng.random() < CANCEL_MISFLAG_RATE:
                status = rng.choice(["no_show", "missed"], p=[0.7, 0.3])
            else:
                status = "cancelled"

        else:  # rescheduled — the patient moved this visit to a later slot.
            # The reschedule target is a NEW appointment id we reserve now and
            # emit as its own row below, forming a chain.
            target_id = appointment_id
            appointment_id += 1
            rescheduled_to_id = target_id

            # The original slot's terminal flag. The clinic SHOULD mark it
            # "rescheduled", but more often than not the empty chair is keyed
            # as a missed/no-show because nobody updated the move.
            if rng.random() < RESCHEDULE_MISFLAG_RATE:
                status = rng.choice(["no_show", "missed"], p=[0.7, 0.3])
            else:
                status = "rescheduled"

            # Emit the downstream slot the patient actually moved to. It lands
            # later (often in a different month) and itself resolves to a normal
            # outcome — usually attended, sometimes missed again.
            lag_days = int(rng.choice([3, 7, 14, 25, 40], p=[0.25, 0.30, 0.22, 0.15, 0.08]))
            t_sched = sched_for + timedelta(days=lag_days)
            t_roll = rng.random()
            if t_roll < 0.78:
                t_status = "attended"
                t_checkin = t_sched + timedelta(minutes=int(rng.integers(-10, 25)))
                t_checkout = t_checkin + timedelta(minutes=int(rng.integers(10, 60)))
            elif t_roll < 0.90:
                t_status = rng.choice(["no_show", "missed"], p=[0.7, 0.3])
                t_checkin = None
                t_checkout = None
            else:
                t_status = "cancelled"
                t_checkin = None
                t_checkout = None

            rows.append({
                "APPOINTMENT_ID": target_id,
                "PATIENT_ID": pid,
                "DOCTOR_ID": did,
                "LOCATION": loc,
                "APPOINTMENT_TYPE": appt_type,
                "STATUS": t_status,
                "SCHEDULED_FOR": t_sched,
                "BOOKED_AT": sched_for + timedelta(hours=int(rng.integers(1, 48))),
                "CHECKED_IN_AT": t_checkin,
                "CHECKOUT_AT": t_checkout,
                "CANCEL_REASON": "patient_request" if t_status == "cancelled" else None,
                "RESCHEDULED_FROM_ID": appt_id,
                "RESCHEDULED_TO_ID": None,
            })

        rows.append({
            "APPOINTMENT_ID": appt_id,
            "PATIENT_ID": pid,
            "DOCTOR_ID": did,
            "LOCATION": loc,
            "APPOINTMENT_TYPE": appt_type,
            "STATUS": status,
            "SCHEDULED_FOR": sched_for,
            "BOOKED_AT": booked_at,
            "CHECKED_IN_AT": checked_in_at,
            "CHECKOUT_AT": checkout_at,
            "CANCEL_REASON": cancel_reason,
            "RESCHEDULED_FROM_ID": None,
            "RESCHEDULED_TO_ID": rescheduled_to_id,
        })

    df = pd.DataFrame(rows)

    # The scheduling system occasionally writes a booking twice (a double-submit
    # from the front-desk UI). Same appointment, new id, identical slot details.
    n_dupe = max(1, len(df) // 130)
    dupe_src = df.sample(n=n_dupe, random_state=int(rng.integers(0, 1_000_000)))
    dupes = dupe_src.copy()
    dupes["APPOINTMENT_ID"] = np.arange(
        df["APPOINTMENT_ID"].max() + 1,
        df["APPOINTMENT_ID"].max() + 1 + len(dupes),
    )
    dupes["RESCHEDULED_TO_ID"] = None  # the duplicate has no downstream link
    df = pd.concat([df, dupes], ignore_index=True)

    # A small population of attended visits lost their check-in timestamp when
    # the front-desk tablet failed to sync. The visit happened; the stamp is gone.
    attended_idx = df.index[df["STATUS"] == "attended"].to_numpy()
    if len(attended_idx):
        drop_n = max(1, len(attended_idx) // 14)
        drop_idx = rng.choice(attended_idx, size=drop_n, replace=False)
        df.loc[drop_idx, "CHECKED_IN_AT"] = None

    return df.reset_index(drop=True)


def generate_billing(rng, appointments):
    """
    One row per billed encounter. Billing is generated by the revenue-cycle
    system, which only charges for visits where the patient was seen — but the
    feed is imperfect and a slice of charges are attached to the wrong status.
    """
    df = appointments
    rows = []
    bill_id = 600_000

    # Charge mostly for attended visits, plus the well-known "no-show fee" some
    # locations levy, plus a few stray charges keyed to the wrong appointment.
    for a in df.itertuples(index=False):
        status = a.STATUS
        charge = False
        line_type = "office_visit"

        if status == "attended":
            charge = True
            line_type = "office_visit"
        elif status in ("no_show", "missed", "no-show"):
            # Some locations bill a flat no-show fee; only a minority do.
            if rng.random() < 0.18:
                charge = True
                line_type = "no_show_fee"
        elif status == "cancelled":
            if rng.random() < 0.03:
                charge = True
                line_type = "late_cancel_fee"

        if not charge:
            continue

        if line_type == "office_visit":
            billed = np.round(rng.uniform(80, 600), 2)
        elif line_type == "no_show_fee":
            billed = np.round(rng.choice([25.0, 35.0, 50.0]), 2)
        else:
            billed = np.round(rng.choice([20.0, 40.0]), 2)

        # Insurance covers a share; the rest is patient responsibility.
        covered = np.round(billed * rng.uniform(0.4, 0.95), 2) if line_type == "office_visit" else 0.0
        patient_resp = np.round(billed - covered, 2)

        service_at = a.CHECKED_IN_AT if a.CHECKED_IN_AT is not None else a.SCHEDULED_FOR
        # Claims post days-to-weeks after service, frequently a later month.
        post_lag = int(rng.choice([1, 4, 9, 20, 38], p=[0.2, 0.25, 0.25, 0.2, 0.1]))
        posted_at = service_at + timedelta(days=post_lag)

        rows.append({
            "BILLING_ID": bill_id,
            "APPOINTMENT_ID": a.APPOINTMENT_ID,
            "PATIENT_ID": a.PATIENT_ID,
            "LINE_TYPE": line_type,
            "BILLED_AMOUNT": float(billed),
            "INSURANCE_COVERED": float(covered),
            "PATIENT_RESPONSIBILITY": float(patient_resp),
            "SERVICE_AT": service_at,
            "POSTED_AT": posted_at,
        })
        bill_id += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_PATIENTS": """
        CREATE OR REPLACE TABLE RAW_PATIENTS (
            PATIENT_ID     NUMBER(18,0),
            BIRTH_YEAR     NUMBER(6,0),
            SEX            VARCHAR,
            INSURANCE_PLAN VARCHAR,
            HOME_LOCATION  VARCHAR,
            REGISTERED_AT  TIMESTAMP_NTZ
        )""",
    "RAW_DOCTORS": """
        CREATE OR REPLACE TABLE RAW_DOCTORS (
            DOCTOR_ID        NUMBER(18,0),
            PROVIDER_NAME    VARCHAR,
            SPECIALTY        VARCHAR,
            PRIMARY_LOCATION VARCHAR,
            HIRED_AT         TIMESTAMP_NTZ,
            IS_ACTIVE        BOOLEAN
        )""",
    "RAW_APPOINTMENTS": """
        CREATE OR REPLACE TABLE RAW_APPOINTMENTS (
            APPOINTMENT_ID      NUMBER(18,0),
            PATIENT_ID          NUMBER(18,0),
            DOCTOR_ID           NUMBER(18,0),
            LOCATION            VARCHAR,
            APPOINTMENT_TYPE    VARCHAR,
            STATUS              VARCHAR,
            SCHEDULED_FOR       TIMESTAMP_NTZ,
            BOOKED_AT           TIMESTAMP_NTZ,
            CHECKED_IN_AT       TIMESTAMP_NTZ,
            CHECKOUT_AT         TIMESTAMP_NTZ,
            CANCEL_REASON       VARCHAR,
            RESCHEDULED_FROM_ID NUMBER(18,0),
            RESCHEDULED_TO_ID   NUMBER(18,0)
        )""",
    "RAW_BILLING": """
        CREATE OR REPLACE TABLE RAW_BILLING (
            BILLING_ID             NUMBER(18,0),
            APPOINTMENT_ID         NUMBER(18,0),
            PATIENT_ID             NUMBER(18,0),
            LINE_TYPE              VARCHAR,
            BILLED_AMOUNT          NUMBER(12,2),
            INSURANCE_COVERED      NUMBER(12,2),
            PATIENT_RESPONSIBILITY NUMBER(12,2),
            SERVICE_AT             TIMESTAMP_NTZ,
            POSTED_AT              TIMESTAMP_NTZ
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
    ap = argparse.ArgumentParser(description="Provision the CareGrid raw sandbox.")
    ap.add_argument("--appointments", type=int, default=60_000,
                    help="number of base appointment slots to generate")
    ap.add_argument("--patients", type=int, default=12_000,
                    help="number of patients")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (appointments={args.appointments:,}, "
          f"patients={args.patients:,}, seed={args.seed}) ...")
    doctors = generate_doctors(rng)
    patients = generate_patients(rng, args.patients)
    appointments = generate_appointments(rng, args.appointments, patients, doctors)
    billing = generate_billing(rng, appointments)

    tables = {
        "RAW_PATIENTS": patients,
        "RAW_DOCTORS": doctors,
        "RAW_APPOINTMENTS": appointments,
        "RAW_BILLING": billing,
    }

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
