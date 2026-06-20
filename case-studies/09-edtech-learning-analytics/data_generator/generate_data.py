#!/usr/bin/env python3
"""
Lumen Lyceum — learning-platform source-system data export simulator.

Provisions the four raw operational tables (STUDENTS, COURSES, LESSONS,
ASSESSMENTS) into a Snowflake sandbox. This emulates the messy, as-emitted feed
from the client's production learning-management system: re-enrolments, retried
assessment attempts, lessons completed out of order, sessions with missing
end timestamps, and learners whose lesson progress and assessment results
tell two different stories about whether they "finished" a course.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your Snowflake creds (or export the vars)
    python generate_data.py --enrollments 50000 --seed 42

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

# The simulated platform operates over this window. Keep it spanning month
# boundaries so the active-learner windowing problem is exercised.
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)

# Course catalogue. Each course has a fixed number of lessons and one final
# assessment. Mix of short and long courses so "% of lessons" thresholds bite.
COURSE_CATALOG = [
    ("Foundations of Data Literacy", "data", 8),
    ("Intermediate SQL", "data", 12),
    ("Python for Analysts", "data", 16),
    ("Storytelling with Dashboards", "data", 6),
    ("Product Management Essentials", "business", 10),
    ("Financial Modeling 101", "business", 14),
    ("Marketing Analytics", "business", 9),
    ("Intro to UX Research", "design", 7),
    ("Visual Design Systems", "design", 11),
    ("Leadership for New Managers", "business", 5),
    ("Machine Learning Foundations", "data", 18),
    ("Public Speaking", "soft_skills", 4),
]

PLANS = ["free", "free", "free", "individual", "individual", "team"]
LESSON_TYPES = ["video", "video", "reading", "interactive", "quiz"]
DEVICES = ["web", "web", "ios", "android"]
LOCALES = ["en-US", "en-US", "en-US", "en-GB", "es-ES", "fr-FR"]
ASSESSMENT_TYPES = ["final_exam"]


# --------------------------------------------------------------------------- #
# Data generation                                                             #
# --------------------------------------------------------------------------- #

def _random_datetimes(rng, n, start, end):
    """n random timestamps uniformly between start and end."""
    span = int((end - start).total_seconds())
    secs = rng.integers(0, span, size=n)
    return [start + timedelta(seconds=int(s)) for s in secs]


def generate_courses(rng):
    """One row per course. Static catalogue; the lesson count drives % thresholds."""
    rows = []
    course_id = 200
    for title, category, n_lessons in COURSE_CATALOG:
        rows.append({
            "COURSE_ID": course_id,
            "COURSE_TITLE": title,
            "CATEGORY": category,
            "LESSON_COUNT": n_lessons,
            "PASS_THRESHOLD": 70,   # score needed on the final assessment to pass
            "IS_ACTIVE": True,
            "CREATED_AT": START_DATE - timedelta(days=int(rng.integers(30, 400))),
        })
        course_id += 1
    return pd.DataFrame(rows)


def generate_students(rng, courses, n_enrollments):
    """
    One row per ENROLMENT (a student taking a course). The same person can
    appear more than once — re-enrolments and multi-course learners are common,
    so STUDENT_ID is NOT unique in this table.
    """
    # ----------------------------------------------------------------------- #
    # GAP DRIVERS (tunable). These three constants set how far the two         #
    # completion definitions diverge. They are the levers for validating /     #
    # tuning the headline "completion-rate spread".                            #
    #                                                                          #
    #   P_FINISH_LESSONS   — share of enrolments that complete ~all lessons    #
    #   P_SIT_FINAL        — of lesson-finishers, share who sit the final      #
    #   P_PASS_GIVEN_SIT   — of those who sit it, share who pass               #
    # The lessons-based rate ~= P_FINISH_LESSONS; the assessment-based rate    #
    # ~= P_FINISH_LESSONS * P_SIT_FINAL * P_PASS_GIVEN_SIT (plus a few         #
    # stragglers who pass without finishing every lesson). Target spread       #
    # ~45% lessons-based vs ~30% assessment-based.                             #
    # ----------------------------------------------------------------------- #
    P_FINISH_LESSONS = 0.50
    P_SIT_FINAL = 0.80
    P_PASS_GIVEN_SIT = 0.71

    course_ids = courses["COURSE_ID"].to_numpy()
    # A learner population smaller than enrolments => natural re-enrolment.
    n_people = max(2, n_enrollments // 3)
    person_ids = rng.integers(10_000, 10_000 + n_people, size=n_enrollments)

    enrolled_at = _random_datetimes(rng, n_enrollments, START_DATE, END_DATE)
    picked_courses = rng.choice(course_ids, size=n_enrollments)

    plans = rng.choice(PLANS, size=n_enrollments)
    locales = rng.choice(LOCALES, size=n_enrollments)

    # Latent per-enrolment behaviour, drawn here and consumed by lesson /
    # assessment generators so the three tables stay internally consistent.
    finishes_lessons = rng.random(n_enrollments) < P_FINISH_LESSONS
    sits_final = finishes_lessons & (rng.random(n_enrollments) < P_SIT_FINAL)
    passes_final = sits_final & (rng.random(n_enrollments) < P_PASS_GIVEN_SIT)

    # A small population passes the final without having completed every lesson
    # (tested out / strong prior knowledge). Keeps the two definitions from
    # being a clean subset of one another.
    tests_out = (~finishes_lessons) & (rng.random(n_enrollments) < 0.05)
    sits_final = sits_final | tests_out
    passes_final = passes_final | (tests_out & (rng.random(n_enrollments) < 0.75))

    # The platform stamps a coarse status field. It is set by an overnight job
    # and does NOT always agree with the underlying lesson/assessment events —
    # this is one of the reasons the client's dashboards disagree.
    status = np.where(
        passes_final, "completed",
        np.where(finishes_lessons, "in_progress",
                 np.where(rng.random(n_enrollments) < 0.5, "in_progress", "enrolled"))
    )
    # A slice of genuinely-finished learners are still tagged "in_progress"
    # because the nightly status job lagged or missed the assessment webhook.
    lag_idx = rng.random(n_enrollments) < 0.07
    status = np.where(lag_idx & passes_final, "in_progress", status)

    df = pd.DataFrame({
        "ENROLLMENT_ID": np.arange(1_000_000, 1_000_000 + n_enrollments),
        "STUDENT_ID": person_ids,
        "COURSE_ID": picked_courses,
        "PLAN": plans,
        "LOCALE": locales,
        "ENROLLMENT_STATUS": status,
        "ENROLLED_AT": enrolled_at,
        # last_active_at usually >= enrolled_at ...
        "LAST_ACTIVE_AT": [e + timedelta(hours=int(rng.integers(1, 24 * 90)))
                           for e in enrolled_at],
        # carried for downstream generators, dropped before load
        "HINT_FINISH_LESSONS": finishes_lessons,
        "HINT_SITS_FINAL": sits_final,
        "HINT_PASSES_FINAL": passes_final,
    })

    # Clock skew: a small population where last_active_at precedes enrolled_at
    # (event re-ordering on the ingestion side). Left in as-emitted.
    skew_idx = rng.choice(n_enrollments, size=max(1, n_enrollments // 500), replace=False)
    df.loc[skew_idx, "LAST_ACTIVE_AT"] = [
        e - timedelta(hours=int(rng.integers(1, 72)))
        for e in df.loc[skew_idx, "ENROLLED_AT"]
    ]
    return df


def generate_lessons(rng, students, courses):
    """
    One row per lesson-progress event (a learner starting/finishing a lesson in
    a course). Learners move through lessons out of order, occasionally log the
    same lesson twice (resumed on another device), and some sessions never get
    an end timestamp.
    """
    course_lessons = courses.set_index("COURSE_ID")["LESSON_COUNT"].to_dict()

    rows = []
    event_id = 3_000_000

    for s in students.itertuples(index=False):
        total = course_lessons[s.COURSE_ID]

        if s.HINT_FINISH_LESSONS:
            # Completes essentially all lessons (occasionally skips the very last).
            n_completed = total if rng.random() < 0.9 else total - 1
        else:
            # Partial progress: a long tail from "barely started" to "almost done".
            frac = rng.choice([0.0, 0.1, 0.25, 0.4, 0.6, 0.8],
                              p=[0.18, 0.22, 0.20, 0.18, 0.14, 0.08])
            n_completed = int(round(total * frac))

        if n_completed <= 0:
            # Even no-progress enrolments often have one "opened lesson 1" event.
            if rng.random() < 0.6:
                start = s.ENROLLED_AT + timedelta(hours=int(rng.integers(1, 48)))
                rows.append(_lesson_row(event_id, s, 1, "started", start, rng, completed=False))
                event_id += 1
            continue

        # Lesson order is shuffled — learners jump around.
        lesson_order = list(range(1, total + 1))
        rng.shuffle(lesson_order)
        chosen = lesson_order[:n_completed]

        cursor = s.ENROLLED_AT + timedelta(hours=int(rng.integers(1, 72)))
        for lesson_no in chosen:
            cursor = cursor + timedelta(hours=int(rng.integers(2, 96)))
            rows.append(_lesson_row(event_id, s, lesson_no, "completed", cursor, rng, completed=True))
            event_id += 1

            # Resume-on-another-device duplicates: the same lesson logged twice,
            # distinct EVENT_ID, same enrolment + lesson number.
            if rng.random() < 0.03:
                dup_ts = cursor + timedelta(minutes=int(rng.integers(1, 240)))
                rows.append(_lesson_row(event_id, s, lesson_no, "completed", dup_ts, rng, completed=True))
                event_id += 1

    return pd.DataFrame(rows)


def _lesson_row(event_id, s, lesson_no, status, start_ts, rng, completed):
    duration_min = int(rng.integers(3, 55))
    completed_at = start_ts + timedelta(minutes=duration_min) if completed else None
    # Session end timestamps go missing when the player loses connectivity.
    if completed and rng.random() < 0.06:
        completed_at = None
    return {
        "LESSON_EVENT_ID": event_id,
        "ENROLLMENT_ID": s.ENROLLMENT_ID,
        "STUDENT_ID": s.STUDENT_ID,
        "COURSE_ID": s.COURSE_ID,
        "LESSON_NUMBER": lesson_no,
        "LESSON_TYPE": rng.choice(LESSON_TYPES),
        "LESSON_STATUS": status,           # 'started' or 'completed'
        "DEVICE": rng.choice(DEVICES),
        "DURATION_MINUTES": duration_min,
        "STARTED_AT": start_ts,
        "COMPLETED_AT": completed_at,      # null on dropped sessions / 'started'
    }


def generate_assessments(rng, students, courses):
    """
    One row per assessment ATTEMPT on a course's final exam. Learners can retry
    a failed attempt, so an enrolment may have several rows. The grading service
    occasionally double-writes a settled attempt.
    """
    pass_threshold = courses.set_index("COURSE_ID")["PASS_THRESHOLD"].to_dict()

    rows = []
    attempt_id = 5_000_000

    for s in students.itertuples(index=False):
        if not s.HINT_SITS_FINAL:
            continue

        threshold = pass_threshold[s.COURSE_ID]
        base_ts = s.ENROLLED_AT + timedelta(days=int(rng.integers(3, 120)))

        if s.HINT_PASSES_FINAL:
            # 0–2 failed retries before the passing attempt.
            n_fail = rng.choice([0, 0, 1, 2], p=[0.62, 0.20, 0.13, 0.05])
            for k in range(n_fail):
                fail_score = int(rng.integers(35, threshold))
                rows.append(_assessment_row(attempt_id, s, fail_score, threshold,
                                            base_ts + timedelta(days=int(k + 1)), rng))
                attempt_id += 1
            pass_score = int(rng.integers(threshold, 101))
            pass_ts = base_ts + timedelta(days=int(n_fail + 1))
            pass_row = _assessment_row(attempt_id, s, pass_score, threshold, pass_ts, rng)
            rows.append(pass_row)
            attempt_id += 1

            # Grading service double-writes a settled attempt (webhook delivered
            # twice). Same enrolment, same score, new ATTEMPT_ID.
            if rng.random() < 0.02:
                dup = dict(pass_row)
                dup["ASSESSMENT_ATTEMPT_ID"] = attempt_id
                dup["SUBMITTED_AT"] = pass_row["SUBMITTED_AT"] + timedelta(seconds=int(rng.integers(1, 20)))
                rows.append(dup)
                attempt_id += 1
        else:
            # Sat the final but never passed: 1–3 failing attempts.
            n_try = int(rng.integers(1, 4))
            for k in range(n_try):
                fail_score = int(rng.integers(20, threshold))
                rows.append(_assessment_row(attempt_id, s, fail_score, threshold,
                                            base_ts + timedelta(days=int(k + 1)), rng))
                attempt_id += 1

    return pd.DataFrame(rows)


def _assessment_row(attempt_id, s, score, threshold, ts, rng):
    passed = score >= threshold
    # A slice of attempts are still being graded — score/passed not yet stamped.
    if rng.random() < 0.015:
        graded_at = None
        score_out = None
        passed_out = None
        status = "submitted"
    else:
        graded_at = ts + timedelta(minutes=int(rng.integers(1, 240)))
        score_out = score
        passed_out = passed
        status = "graded"
    return {
        "ASSESSMENT_ATTEMPT_ID": attempt_id,
        "ENROLLMENT_ID": s.ENROLLMENT_ID,
        "STUDENT_ID": s.STUDENT_ID,
        "COURSE_ID": s.COURSE_ID,
        "ASSESSMENT_TYPE": "final_exam",
        "SCORE": score_out,                 # 0–100; null while grading
        "PASS_THRESHOLD": threshold,
        "IS_PASSED": passed_out,            # null while grading
        "ATTEMPT_STATUS": status,           # 'graded' or 'submitted'
        "SUBMITTED_AT": ts,
        "GRADED_AT": graded_at,             # null while grading
    }


# --------------------------------------------------------------------------- #
# Snowflake load                                                              #
# --------------------------------------------------------------------------- #

DDL = {
    "RAW_COURSES": """
        CREATE OR REPLACE TABLE RAW_COURSES (
            COURSE_ID      NUMBER(18,0),
            COURSE_TITLE   VARCHAR,
            CATEGORY       VARCHAR,
            LESSON_COUNT   NUMBER(9,0),
            PASS_THRESHOLD NUMBER(9,0),
            IS_ACTIVE      BOOLEAN,
            CREATED_AT     TIMESTAMP_NTZ
        )""",
    "RAW_STUDENTS": """
        CREATE OR REPLACE TABLE RAW_STUDENTS (
            ENROLLMENT_ID     NUMBER(18,0),
            STUDENT_ID        NUMBER(18,0),
            COURSE_ID         NUMBER(18,0),
            PLAN              VARCHAR,
            LOCALE            VARCHAR,
            ENROLLMENT_STATUS VARCHAR,
            ENROLLED_AT       TIMESTAMP_NTZ,
            LAST_ACTIVE_AT    TIMESTAMP_NTZ
        )""",
    "RAW_LESSONS": """
        CREATE OR REPLACE TABLE RAW_LESSONS (
            LESSON_EVENT_ID  NUMBER(18,0),
            ENROLLMENT_ID    NUMBER(18,0),
            STUDENT_ID       NUMBER(18,0),
            COURSE_ID        NUMBER(18,0),
            LESSON_NUMBER    NUMBER(9,0),
            LESSON_TYPE      VARCHAR,
            LESSON_STATUS    VARCHAR,
            DEVICE           VARCHAR,
            DURATION_MINUTES NUMBER(9,0),
            STARTED_AT       TIMESTAMP_NTZ,
            COMPLETED_AT     TIMESTAMP_NTZ
        )""",
    "RAW_ASSESSMENTS": """
        CREATE OR REPLACE TABLE RAW_ASSESSMENTS (
            ASSESSMENT_ATTEMPT_ID NUMBER(18,0),
            ENROLLMENT_ID         NUMBER(18,0),
            STUDENT_ID            NUMBER(18,0),
            COURSE_ID             NUMBER(18,0),
            ASSESSMENT_TYPE       VARCHAR,
            SCORE                 NUMBER(9,0),
            PASS_THRESHOLD        NUMBER(9,0),
            IS_PASSED             BOOLEAN,
            ATTEMPT_STATUS        VARCHAR,
            SUBMITTED_AT          TIMESTAMP_NTZ,
            GRADED_AT             TIMESTAMP_NTZ
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

def build_tables(rng, n_enrollments):
    """Generate all four raw frames. Returns the load-ready dict (helper cols dropped)."""
    courses = generate_courses(rng)
    students = generate_students(rng, courses, n_enrollments)
    lessons = generate_lessons(rng, students, courses)
    assessments = generate_assessments(rng, students, courses)

    students_load = students.drop(columns=["HINT_FINISH_LESSONS", "HINT_SITS_FINAL", "HINT_PASSES_FINAL"])

    return {
        "RAW_COURSES": courses,
        "RAW_STUDENTS": students_load,
        "RAW_LESSONS": lessons,
        "RAW_ASSESSMENTS": assessments,
    }, students   # also return the enriched students frame for validation


def main():
    ap = argparse.ArgumentParser(description="Provision the Lumen Lyceum raw sandbox.")
    ap.add_argument("--enrollments", type=int, default=50_000,
                    help="number of course enrolments to generate")
    ap.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true", help="generate + print summary, do not load")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Generating data (enrollments={args.enrollments:,}, seed={args.seed}) ...")
    tables, _ = build_tables(rng, args.enrollments)

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
