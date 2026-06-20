# Data Generator — CareGrid raw sandbox

This script provisions the four raw operational tables into your Snowflake
sandbox. It simulates a source-system export from a multi-location provider's
scheduling and revenue-cycle systems: the data is **realistic and deliberately
imperfect**. Cleaning and reconciling it is the engagement.

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
export SNOWFLAKE_DATABASE=CAREGRID
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: 60,000 base appointments, 12,000 patients, seed 42 (reproducible)
python generate_data.py

# Smaller/larger
python generate_data.py --appointments 10000 --patients 3000

# Validate generation without touching Snowflake
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the four tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed`, `--appointments`, and `--patients`
> always produce identical data. Use the defaults so reviewers see the same
> dataset you modeled against.

> **Note on row counts:** each rescheduled visit books a *second* appointment
> slot (the chain target), so the table holds more rows than `--appointments`.
> The default run emits ~70k appointment rows from 60k base slots.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_PATIENTS` — one row per patient
| Column | Type | Description |
|---|---|---|
| `PATIENT_ID` | NUMBER | Unique patient identifier. |
| `BIRTH_YEAR` | NUMBER | Year of birth. |
| `SEX` | VARCHAR | `F`, `M`, `X`. |
| `INSURANCE_PLAN` | VARCHAR | `ppo_a`, `ppo_b`, `hmo_c`, `medicare`, `medicaid`, `self_pay`. |
| `HOME_LOCATION` | VARCHAR | Patient's home clinic. |
| `REGISTERED_AT` | TIMESTAMP_NTZ | First enrollment date. |

### `RAW_DOCTORS` — one row per provider
| Column | Type | Description |
|---|---|---|
| `DOCTOR_ID` | NUMBER | Unique provider identifier. |
| `PROVIDER_NAME` | VARCHAR | Provider label. |
| `SPECIALTY` | VARCHAR | Clinical specialty. |
| `PRIMARY_LOCATION` | VARCHAR | Provider's home clinic. |
| `HIRED_AT` | TIMESTAMP_NTZ | Hire date. |
| `IS_ACTIVE` | BOOLEAN | Whether the provider is currently active. *Some inactive providers still have historical visits.* |

### `RAW_APPOINTMENTS` — one row per booked slot
| Column | Type | Description |
|---|---|---|
| `APPOINTMENT_ID` | NUMBER | Unique per booked slot. |
| `PATIENT_ID` | NUMBER | The patient. |
| `DOCTOR_ID` | NUMBER | The provider. |
| `LOCATION` | VARCHAR | Clinic the slot is at. |
| `APPOINTMENT_TYPE` | VARCHAR | `new_patient`, `follow_up`, `annual_physical`, `procedure`, `telehealth`. |
| `STATUS` | VARCHAR | Lifecycle/terminal state. Values seen in the feed include `attended`, `no_show`, `missed`, `no-show`, `cancelled`, `rescheduled`. **Different locations key these inconsistently.** |
| `SCHEDULED_FOR` | TIMESTAMP_NTZ | When the visit was scheduled to occur. |
| `BOOKED_AT` | TIMESTAMP_NTZ | When the slot was booked. |
| `CHECKED_IN_AT` | TIMESTAMP_NTZ | Front-desk check-in time. **Sometimes null even when attended** (tablet sync failure). |
| `CHECKOUT_AT` | TIMESTAMP_NTZ | Visit checkout time. Null unless attended. |
| `CANCEL_REASON` | VARCHAR | Populated when the visit was cancelled: `patient_request`, `clinic_cancelled`, `provider_unavailable`, `weather`. |
| `RESCHEDULED_TO_ID` | NUMBER | If this slot was rescheduled, the `APPOINTMENT_ID` of the **new** slot the patient moved to. Null otherwise. |
| `RESCHEDULED_FROM_ID` | NUMBER | If this slot is the **target** of a reschedule, the `APPOINTMENT_ID` of the original slot. Null otherwise. |

> When a patient reschedules, the system **books a new slot** (a new row with
> `RESCHEDULED_FROM_ID` set) and leaves the original row with whatever terminal
> status the front desk applied. The pair forms a chain. The Data Lead "never
> fully trusted" these link columns — verify them.

### `RAW_BILLING` — one row per billed line
| Column | Type | Description |
|---|---|---|
| `BILLING_ID` | NUMBER | Unique billing-line identifier. |
| `APPOINTMENT_ID` | NUMBER | The appointment the charge is attached to. |
| `PATIENT_ID` | NUMBER | The patient. |
| `LINE_TYPE` | VARCHAR | `office_visit`, `no_show_fee`, `late_cancel_fee`. *No-show / late-cancel fees attach to non-attended appointments.* |
| `BILLED_AMOUNT` | NUMBER(12,2) | Charge amount. |
| `INSURANCE_COVERED` | NUMBER(12,2) | Insurance-covered portion (0 for fees). |
| `PATIENT_RESPONSIBILITY` | NUMBER(12,2) | Patient-owed portion. |
| `SERVICE_AT` | TIMESTAMP_NTZ | Date of service. |
| `POSTED_AT` | TIMESTAMP_NTZ | When the claim posted. **Often a later month than the service date.** |

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `CAREGRID` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--appointments`; 60k base slots generates ~70k appointment rows and ~48k billing rows. `write_pandas` uses Parquet staging so it should still be quick.
