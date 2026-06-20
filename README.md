# Analytics Engineering Fellowship — Consulting Capstones

> Ten end-to-end analytics engineering case studies, each framed as a **real client engagement**.
> You don't get a clean dataset and a question. You get a messy business, stakeholders who
> disagree, and a mandate to deliver numbers the business can trust.

Every engagement ships with a **data generator** that provisions realistic, deliberately
imperfect data straight into your Snowflake sandbox — so you spend zero time hunting for data
and all your time doing the actual job: modeling, testing, reconciling, and defending decisions.

---

## Why this exists

By Phase 4 of the fellowship you can already build dbt models. These capstones are about the
leap from *operating tools* to *thinking like an analytics engineer in production*:

- Scheduling and orchestrating pipelines
- Monitoring failures and data quality
- Handling dirty, late-arriving, and contradictory data
- Designing for scale and idempotency
- Making and **defending** tradeoffs
- Working from imperfect, conflicting requirements
- Communicating to non-technical stakeholders

**You are assessed as a consultant, not a SQL author.** Thinking, architecture, tradeoffs,
data quality, and business understanding outweigh syntax. (See any engagement's `RUBRIC.md`.)

---

## The engagement catalog

| # | Engagement | Domain | The core tension you must resolve |
|---|---|---|---|
| 01 | E-Commerce Revenue Leakage | Retail / Finance | When is revenue *real*? Finance and Ops disagree by 8–12%. |
| 02 | Ride-Hailing Marketplace | Mobility | What counts as an active rider? How are cancelled/fraud trips treated? |
| 03 | Telecom Customer Churn | Telecom | Whose churn definition wins when every team has its own? |
| 04 | Fintech Loan Portfolio | Lending | What is a default? How do restructurings hide risk? |
| 05 | Healthcare Appointments | Healthcare | What is a no-show vs a reschedule vs a cancellation? |
| 06 | Subscription / MRR Platform | SaaS / Streaming | How do you count MRR with pauses, upgrades, and downgrades? |
| 07 | Logistics Delivery Performance | Logistics | What is "on-time" when delivery timestamps go missing? |
| 08 | HR Workforce Analytics | People Ops | What is tenure across rehires and transfers? |
| 09 | EdTech Learning Analytics | Education | What is a completed course? An active learner? |
| 10 | Multi-Country Retail | Retail | Which currency, which day's FX rate, for consolidated reporting? |

Engagements **02**, **07**, and **10** also involve a live external API (see
[API engagements](#api-engagements) below). Engagement 10 *requires* a free FX-rates API.

---

## How each engagement is structured

```
case-studies/NN-engagement-name/
├── BRIEF.md            ← the engagement letter: client, stakeholders, problem, deliverables
├── RUBRIC.md           ← exactly how your work is assessed
├── data_generator/     ← provisions your Snowflake sandbox (no data hunting)
│   ├── generate_data.py
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md       ← data dictionary + run instructions
└── dbt_starter/        ← a minimal dbt scaffold (sources only — you build the models)
    ├── dbt_project.yml
    ├── profiles.example.yml
    └── models/staging/sources.yml
```

> **The cardinal rule:** the data is dirty **on purpose** — duplicate events, null timestamps,
> late-arriving records, contradictory statuses. **The brief will never tell you where the
> problems are.** Finding them, deciding how to treat them, and *documenting why* is the job.

---

## Prerequisites

- **Python 3.9+**
- **A Snowflake account** you can create databases/schemas in (a free [30-day trial](https://signup.snowflake.com/) is plenty)
- **dbt** with the Snowflake adapter: `pip install dbt-snowflake`
- Basic comfort with git, SQL, and a terminal

---

## Quickstart

```bash
# 1. Clone
git clone https://github.com/tripleaceme/analytics-engineering-fellowship.git
cd analytics-engineering-fellowship

# 2. Pick an engagement and read the brief FIRST
cd case-studies/01-ecommerce-revenue-leakage
open BRIEF.md   # or your editor of choice — read it like a client email

# 3. Set up the generator
cd data_generator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Point it at your Snowflake sandbox (see .env.example for the full list)
export SNOWFLAKE_ACCOUNT=xy12345.us-east-1
export SNOWFLAKE_USER=YOUR_USER
export SNOWFLAKE_PASSWORD=********
export SNOWFLAKE_ROLE=SYSADMIN
export SNOWFLAKE_WAREHOUSE=COMPUTE_WH
export SNOWFLAKE_DATABASE=LUMEN_LOOM    # each engagement uses its own db name
export SNOWFLAKE_SCHEMA=RAW

# 5. Validate generation without touching Snowflake
python generate_data.py --dry-run

# 6. Provision the raw tables into Snowflake
python generate_data.py
```

You now have realistic raw tables in `SNOWFLAKE_DATABASE.RAW`. Time to build.

---

## Running a data generator (details)

Every generator is **seed-deterministic** — the same `--seed` always produces the same data,
so your work is reproducible and a reviewer sees exactly what you modeled against.

```bash
python generate_data.py                 # defaults (≈50k base rows, seed 42), loads to Snowflake
python generate_data.py --dry-run       # generate + print row counts, no Snowflake needed
python generate_data.py --seed 7        # a different but statistically-identical dataset
python generate_data.py --orders 10000  # smaller/larger scale (flag name varies per engagement)
```

The script will `CREATE DATABASE / SCHEMA IF NOT EXISTS`, then `CREATE OR REPLACE` the raw
tables and bulk-load them with `write_pandas`. **Re-running is safe and idempotent.**

> `--dry-run` works **without** the Snowflake connector installed — handy for a quick check
> before you've sorted credentials. The full load needs `snowflake-connector-python` (in
> `requirements.txt`) and valid env vars.

---

## Setting up dbt

Each engagement ships a `dbt_starter/` with **sources already defined** — you build staging →
intermediate → marts on top.

```bash
cd ../dbt_starter

# Use the example profile (reads the SAME env vars as the generator — one setup covers both)
cp profiles.example.yml ~/.dbt/profiles.yml     # or merge into your existing profiles.yml

dbt debug      # confirm the connection
dbt deps       # if the engagement declares packages (e.g. dbt_utils)
dbt build      # run + test your models
dbt docs generate && dbt docs serve   # browse lineage + docs
```

Point the `database`/`schema` in `models/staging/sources.yml` at wherever you ran the generator.

---

## The fellow's workflow (what "doing the engagement" looks like)

1. **Read `BRIEF.md` like a client email.** Note where stakeholders disagree — that conflict *is* the engagement.
2. **Run the generator**, then explore the raw tables. Profile them. Find the dirty data the brief hinted at but didn't pinpoint.
3. **Take explicit positions** on the definitional questions (what is "completed", "churned", "on-time", "a default"…). Write each as an assumption.
4. **Model in layers** (staging → intermediate → marts) with `ref()`/`source()`, sensible grain, idempotent.
5. **Build a data quality framework** — ≥10 tests, including ≥3 *business-rule* tests, with severities and a "what happens when this fails in prod" story.
6. **Reconcile / explain the headline finding** (e.g. the 8–12% revenue gap) — don't make it disappear, *explain* it.
7. **Design orchestration** (Airflow/Dagster/Prefect): schedule, dependencies, freshness checks, alerting, re-run story.
8. **Document and present** — architecture diagram, source-to-target map, assumptions log, and a deck you could defend in a client room.

---

## What you submit (every engagement)

1. Architecture diagram (source → staging → intermediate → marts)
2. Source-to-target mapping
3. dbt project (layered, `ref()`/`source()`, sane naming)
4. Tests — **minimum 10**, at least **3 business-rule** tests
5. Documentation (model + column descriptions, exec summary)
6. Orchestration design (Airflow/Dagster/Prefect)
7. Data quality framework (checks, severities, failure behavior)
8. Business metric definitions (the contract for each headline number)
9. Assumptions & tradeoffs log (heavily weighted)
10. Presentation deck (8–12 slides defending your decisions)

---

## API engagements

Most engagements are fully offline and reproducible. Three involve a live external API —
because handling the API *is* one of the lessons (rate limits, backfill, missing data):

- **10 · Multi-Country Retail → FX rates API (required).** Pull historical daily rates from a
  free, keyless API ([Frankfurter](https://www.frankfurter.app/) or
  [exchangerate.host](https://exchangerate.host/)). Solve: which day's rate applies, how to
  backfill, what to do when a date has no rate (weekends/holidays), how to make the pull incremental.
- **02 · Ride-Hailing → geocoding/distance API (recommended, optional).** Turn trip coordinates
  into road distances/ETAs via [OpenRouteService](https://openrouteservice.org/) or
  [OSRM](http://project-osrm.org/). Falls back to haversine if you have no key.
- **07 · Logistics → geocoding API (optional stretch).** Same machinery as 02 for delivery
  distance/ETA enrichment. The core SLA-modeling problem stands on its own without it.

---

## Repository layout

```
analytics-engineering-fellowship/
├── README.md                       ← you are here
├── templates/
│   └── case-study-template.md      ← how the engagements are authored
└── case-studies/
    ├── 01-ecommerce-revenue-leakage/
    ├── 02-ride-hailing-marketplace/
    ├── … (03–09) …
    └── 10-multi-country-retail/
```

Each engagement folder contains `BRIEF.md`, `RUBRIC.md`, `data_generator/`, and `dbt_starter/`.

---

## For instructors / reviewers

Each engagement also has an **answer key** (`INSTRUCTOR_NOTES.md`) containing the injected-flaw
catalog, the expected reconciliation, reproducible reference numbers (at the default seed),
grading tiers, and common traps. **These are intentionally kept out of this public repository**
to protect assessment integrity — they're distributed to reviewers separately.

To create cohort variants that can't be shared between fellows, change `--seed`: the data stays
statistically identical and structurally the same, but every number differs.

---

## License

Released for educational use. See [LICENSE](LICENSE).

Built for the Analytics Engineering Fellowship. Engagement 01 is the hand-built gold standard;
02–10 follow the same structure and quality bar.
