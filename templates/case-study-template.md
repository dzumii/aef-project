# Engagement Authoring Template

Use this to build engagements 02–10 to the same standard as the exemplar (01).
Each engagement folder must contain: `BRIEF.md`, `RUBRIC.md`, `INSTRUCTOR_NOTES.md`,
`data_generator/` (script + requirements + README + .env.example), and `dbt_starter/`.

The design rule that makes these work: **the headline business pain must be a
measurable, reproducible property of the generated data** — then validate it
before shipping (as we did for the 8–12% gap in 01).

---

## 1. BRIEF.md skeleton

```
# Engagement NN — <Title>

Client / role / sponsor / stakeholders (give 2+ stakeholders who DISAGREE).

## 1. The situation
   Stakeholder quotes that reveal the conflicting definitions. This is the
   engagement — don't resolve it for them.

## 2. What you've been given (raw tables + grain + Data Lead's caveats)

## 3. The questions the client cannot answer
   The definitional/temporal ambiguities the fellow must take a stance on.

## 4. Deliverables (the contract)  — domain marts + a reconciliation/finding

## 5. Constraints & ground rules (idempotency, reproducibility, tie-out)

## 6. Definition of done (the live defense scenario)
```

## 2. Data generator checklist
- [ ] Seed-deterministic (`--seed`), scalable (`--orders`/`--rows`), `--dry-run`.
- [ ] Loads to Snowflake via `write_pandas`; creates db/schema/tables.
- [ ] Credentials from env vars; lazy Snowflake import so dry-run needs no connector.
- [ ] **3–5 named, isolated "gap driver" constants** so difficulty is tunable and the headline metric can be validated.
- [ ] Injects domain-appropriate flaws (see catalog below). No comments that name the flaws — read like a real export.
- [ ] A validation run proving the headline business metric lands in the brief's stated range.

## 3. Flaw catalog (pick what fits the domain)
| Flaw type | Example domains |
|---|---|
| Duplicate events (double-logged) | payments, trips, deliveries, sessions |
| Retries / failed attempts | payments, logins, API calls |
| Partial / reversal events | refunds, repayments, downgrades |
| Late-arriving / cross-period | refunds, defaults, churn events |
| Null/missing timestamps | shipping, delivery, completion |
| Conflicting status definitions | churn, completion, active-user, default |
| Clock skew / out-of-order | any event stream |
| Multi-currency / multi-timezone | global retail, marketplaces |
| Reactivation / rehire / restructure | churn, HR, loans, subscriptions |

## 4. INSTRUCTOR_NOTES.md must contain
- Reference numbers for the default seed (reproducible).
- The injected-flaw table (what / where / correct handling).
- The expected reconciliation or finding.
- Grading tiers + common traps.
- How to spin cohort variants (change seed / driver constants).

## 5. RUBRIC.md weighting (keep consistent across engagements)
Business framing 20 / Architecture 20 / Data quality 15 / Tradeoffs 15 /
Correctness 10 / Orchestration 10 / Docs & comms 10.

## 6. Per-engagement design seeds (for 02–10)
- **02 Ride-Hailing:** active-rider definition; cancelled-trip classification; fraud rides; driver bonus attribution. *Geocoding API for distances (recommended).*
- **03 Telecom Churn:** competing churn definitions across teams; reactivations; the unified customer mart must support multiple churn flags side-by-side.
- **04 Loan Portfolio:** default definition (DPD threshold); restructurings reset clocks; partial repayments; the "what is a default" question drives everything.
- **05 Healthcare:** no-show vs reschedule vs cancel; appointment fact grain; reschedule chains pointing at prior appointments.
- **06 Subscription/MRR:** paused vs active; upgrade/downgrade mid-cycle proration; the MRR definition is the whole engagement.
- **07 Logistics:** on-time SLA with missing delivery timestamps; incomplete deliveries. *Geocoding API optional stretch.*
- **08 HR:** tenure across rehires; department transfers; attrition definition; internal-movement modeling.
- **09 EdText:** competing course-completion definitions; active-learner; assessment-vs-lesson completion.
- **10 Multi-Country Retail:** reporting currency choice; historical FX. *FX rates API required — which day's rate, backfill, missing weekend rates.*
