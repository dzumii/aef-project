# Data Generator — LendWell raw sandbox

This script provisions the four raw operational tables into your Snowflake
sandbox. It simulates a source-system export from a digital lending platform:
the data is **realistic and deliberately imperfect**. Cleaning and reconciling
it — and getting to a portfolio-at-risk number the executives can trust — is
the engagement.

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
export SNOWFLAKE_DATABASE=LENDWELL
export SNOWFLAKE_SCHEMA=RAW
```

## Run

```bash
# Default: ~40,000 funded loans, seed 42 (reproducible)
python generate_data.py

# Smaller/larger (this targets FUNDED loans; the script scales applications up)
python generate_data.py --loans 10000

# Validate generation without touching Snowflake
python generate_data.py --dry-run
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE`
the four tables and bulk-load them. Re-running is safe and idempotent — it fully
replaces the raw tables with the same seed-deterministic data.

> **Reproducibility:** the same `--seed` and `--loans` always produce identical
> data. Use the default seed so reviewers see the same dataset you modeled against.

> **The book is observed as at a single reporting date** (`AS_OF_DATE`, the
> 30 June 2025 month-end). Days-past-due and portfolio-at-risk are computed
> relative to that date. Loans are originated across the prior ~2 years so a
> spread of them are mid-term on the as-of date.

---

## Data dictionary

> These descriptions reflect how the Data Lead understands the source systems.
> Treat them as a starting map, not gospel — part of your job is verifying them.

### `RAW_APPLICATIONS` — one row per loan application
| Column | Type | Description |
|---|---|---|
| `APPLICATION_ID` | NUMBER | Unique application identifier. |
| `CUSTOMER_ID` | NUMBER | The applying customer. |
| `PRODUCT_TYPE` | VARCHAR | `payday`, `sme_working_capital`, `asset_finance`, `salary_advance`. |
| `CHANNEL` | VARCHAR | Origination channel: `mobile_app`, `ussd`, `agent`, `web`. |
| `REQUESTED_AMOUNT` | NUMBER(18,2) | Principal the customer asked for, in `CURRENCY`. |
| `CURRENCY` | VARCHAR | Mostly `NGN`; some `USD`/`GHS`. |
| `DECISION` | VARCHAR | `approved`, `declined`, `pending`. Only approved apps become loans. |
| `DECLINE_REASON` | VARCHAR | Populated only when `DECISION = declined`. |
| `SUBMITTED_AT` | TIMESTAMP_NTZ | When the application was submitted. |
| `DECIDED_AT` | TIMESTAMP_NTZ | When underwriting decided. *Usually* ≥ `SUBMITTED_AT`. |

### `RAW_LOANS` — one row per funded loan
| Column | Type | Description |
|---|---|---|
| `LOAN_ID` | NUMBER | Unique loan identifier. |
| `APPLICATION_ID` | NUMBER | The approved application this loan was booked from. |
| `CUSTOMER_ID` | NUMBER | The borrowing customer. |
| `PRODUCT_TYPE` | VARCHAR | Loan product. |
| `PRINCIPAL_AMOUNT` | NUMBER(18,2) | Funded principal (may be trimmed below the requested amount). |
| `CURRENCY` | VARCHAR | Loan currency. |
| `INTEREST_RATE_APR` | NUMBER(9,4) | Annual percentage rate as a decimal (e.g. `0.36`). |
| `TERM_MONTHS` | NUMBER | Contractual term in months. |
| `LOAN_STATUS` | VARCHAR | Servicer's **current** state: `active`, `delinquent`, `restructured`, `closed`. |
| `ORIGINATED_AT` | TIMESTAMP_NTZ | When the loan was disbursed. |
| `FIRST_DUE_DATE` | TIMESTAMP_NTZ | First instalment due date **on the current schedule**. |
| `RESTRUCTURED_AT` | TIMESTAMP_NTZ | When the loan was restructured; null if it never was. |

> The servicer re-papers a restructured loan onto a fresh schedule. `FIRST_DUE_DATE`
> reflects the **current** schedule, not the original one. The prior arrears
> history is not carried on the loan record.

### `RAW_REPAYMENTS` — one row per repayment event against an instalment
| Column | Type | Description |
|---|---|---|
| `REPAYMENT_ID` | NUMBER | Unique per posting. |
| `LOAN_ID` | NUMBER | The loan being repaid. |
| `INSTALMENT_NO` | NUMBER | Which scheduled instalment this posting is against (1-based). |
| `SCHEDULED_AMOUNT` | NUMBER(18,2) | What the instalment was supposed to be. |
| `AMOUNT_PAID` | NUMBER(18,2) | What was actually posted. `0` on a missed instalment. |
| `CURRENCY` | VARCHAR | Posting currency. |
| `PAYMENT_STATUS` | VARCHAR | `posted` (full), `partial` (short-paid), `missed` (due, unpaid). |
| `DUE_DATE` | TIMESTAMP_NTZ | When the instalment was due. |
| `PAID_AT` | TIMESTAMP_NTZ | When the posting settled; **null** for `missed` rows. |

> The servicing gateway logs each posting, including the occasional re-post of a
> settled repayment. A `missed` row is written by the scheduler with a null `PAID_AT`.

### `RAW_DEFAULTS` — one row per loan formally flagged as defaulted
| Column | Type | Description |
|---|---|---|
| `DEFAULT_ID` | NUMBER | Unique default-register entry. |
| `LOAN_ID` | NUMBER | The defaulted loan. |
| `DEFAULT_REASON` | VARCHAR | `non_payment`, `skip`, `deceased`, `fraud`, `bankruptcy`. |
| `OUTSTANDING_AT_DEFAULT` | NUMBER(18,2) | Balance the collections team recorded at flag time. |
| `CURRENCY` | VARCHAR | Currency of the outstanding balance. |
| `DEFAULT_STATUS` | VARCHAR | `open`, `in_recovery`, `written_off`. |
| `FLAGGED_AT` | TIMESTAMP_NTZ | When collections booked the default. |

> This register is maintained by the collections team and is the source Finance
> currently reports portfolio-at-risk from. It is **not** mechanically derived
> from the repayment ledger.

---

## Troubleshooting

- **`Missing Snowflake env vars`** — you didn't export the three required vars (`ACCOUNT`, `USER`, `PASSWORD`).
- **`250001 Could not connect`** — check your account identifier format (`org-account` or `account.region`).
- **Permission denied creating database** — use a role with `CREATE DATABASE`, or pre-create `LENDWELL` and grant your role usage, then point `SNOWFLAKE_DATABASE` at it.
- **Slow load** — drop `--loans`; 40k loans generates ~260k repayment rows. `write_pandas` uses Parquet staging so it should still be quick.
