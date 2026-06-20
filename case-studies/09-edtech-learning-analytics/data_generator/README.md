# Data Generator — Lumen Lyceum raw sandbox

This script provisions the four raw operational tables into your Snowflake
sandbox. It simulates a source-system export from a learning-management
platform: the data is **realistic and deliberately imperfect**. Cleaning it and
reconciling the competing completion definitions is the engagement.

## Setup

```bash
cd data_generator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Provide Snowflake credentials (see .env.example for the full list)
export SNOWFLAKE_ACCOUNT=xy12345.us-east-1
export SNOWFLAKE_USER=YOUR_USER
export SNOWFLAKE_PASSWORD=********
export SNOWFLAKE_ROLE=SYSADMIN
export SNOWFLAKE_WAREHOUSE=COMPUTE_WH
export SNOWFLAKE_DATABASE=LEARNSPHERE
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 50,000 enrolments, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --enrollments 10000

# Validate generation without touching Snowflake
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the four tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--enrollments` always produce
> identical data. Use the default seed so reviewers see the same dataset you
> modeled against.

---

## What the tables represent

The platform sells self-paced online courses. A **student** can enrol in many
courses, and can re-enrol in the same one, so the unit of analysis is an
**enrolment** (one student × one course attempt), not a person. Each enrolment
generates **lesson-progress events** as the learner works through the course, and
**assessment attempts** when they sit the course's final exam.

That fan-out is exactly why the client's dashboards disagree: the Curriculum team
counts "did they finish the lessons?" and the Credentialing team counts "did they
pass the exam?" — and those two populations are not the same.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_STUDENTS` — one row per enrolment (student × course)
| Column | Type | Description |
|---|---|---|
| `ENROLLMENT_ID` | NUMBER | Unique enrolment identifier (the grain of this table). |
| `STUDENT_ID` | NUMBER | The learner. **Not unique** — the same person re-enrols and takes multiple courses. |
| `COURSE_ID` | NUMBER | The course this enrolment is for. |
| `PLAN` | VARCHAR | Billing plan at enrolment: `free`, `individual`, `team`. |
| `LOCALE` | VARCHAR | Learner locale, e.g. `en-US`, `en-GB`, `es-ES`, `fr-FR`. |
| `ENROLLMENT_STATUS` | VARCHAR | Platform's coarse status: `enrolled`, `in_progress`, `completed`. Set by an overnight job. *Doesn't always agree with the underlying events.* |
| `ENROLLED_AT` | TIMESTAMP_NTZ | When the enrolment was created. |
| `LAST_ACTIVE_AT` | TIMESTAMP_NTZ | Last recorded activity. *Usually* ≥ `ENROLLED_AT`. |

### `RAW_COURSES` — one row per course
| Column | Type | Description |
|---|---|---|
| `COURSE_ID` | NUMBER | Unique course identifier. |
| `COURSE_TITLE` | VARCHAR | Display title. |
| `CATEGORY` | VARCHAR | `data`, `business`, `design`, `soft_skills`. |
| `LESSON_COUNT` | NUMBER | How many lessons the course contains. Drives any "% of lessons" rule. |
| `PASS_THRESHOLD` | NUMBER | Score (0–100) needed to pass the final assessment. |
| `IS_ACTIVE` | BOOLEAN | Whether the course is live in the catalogue. |
| `CREATED_AT` | TIMESTAMP_NTZ | When the course was published. |

### `RAW_LESSONS` — one row per lesson-progress event
| Column | Type | Description |
|---|---|---|
| `LESSON_EVENT_ID` | NUMBER | Unique per event. |
| `ENROLLMENT_ID` | NUMBER | The enrolment this progress belongs to. |
| `STUDENT_ID` | NUMBER | Denormalised learner id. |
| `COURSE_ID` | NUMBER | Denormalised course id. |
| `LESSON_NUMBER` | NUMBER | Which lesson (1..`LESSON_COUNT`). Learners move through these **out of order**. |
| `LESSON_TYPE` | VARCHAR | `video`, `reading`, `interactive`, `quiz`. |
| `LESSON_STATUS` | VARCHAR | `started` or `completed`. |
| `DEVICE` | VARCHAR | `web`, `ios`, `android`. |
| `DURATION_MINUTES` | NUMBER | Time spent in the session. |
| `STARTED_AT` | TIMESTAMP_NTZ | When the lesson session began. |
| `COMPLETED_AT` | TIMESTAMP_NTZ | When it finished. **Sometimes null** (player lost connectivity), and null for `started` events. |

> A learner who resumes a lesson on another device can produce **two `completed`
> rows for the same `ENROLLMENT_ID` + `LESSON_NUMBER`**.

### `RAW_ASSESSMENTS` — one row per assessment attempt
| Column | Type | Description |
|---|---|---|
| `ASSESSMENT_ATTEMPT_ID` | NUMBER | Unique per attempt. |
| `ENROLLMENT_ID` | NUMBER | The enrolment being assessed. |
| `STUDENT_ID` | NUMBER | Denormalised learner id. |
| `COURSE_ID` | NUMBER | Denormalised course id. |
| `ASSESSMENT_TYPE` | VARCHAR | `final_exam`. |
| `SCORE` | NUMBER | 0–100. **Null while an attempt is still being graded.** |
| `PASS_THRESHOLD` | NUMBER | Score needed to pass (copied from the course). |
| `IS_PASSED` | BOOLEAN | Whether the attempt passed. **Null while grading.** |
| `ATTEMPT_STATUS` | VARCHAR | `graded` or `submitted` (the latter = not yet graded). |
| `SUBMITTED_AT` | TIMESTAMP_NTZ | When the learner submitted. |
| `GRADED_AT` | TIMESTAMP_NTZ | When the grade settled. **Null while grading.** |

> The gateway/grading service logs **every** attempt, including failed retries
> before a pass.

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `LEARNSPHERE` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--enrollments`; 50k enrolments generates ~330k lesson rows and ~31k assessment rows. `write_pandas` uses Parquet staging so it should still be quick.
