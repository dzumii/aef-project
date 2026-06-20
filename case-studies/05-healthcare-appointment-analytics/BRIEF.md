# Engagement 05 — Healthcare Appointment Analytics

**Client:** CareGrid Health Partners — a multi-location outpatient provider group (5 clinics, ~12k active patients, ~70k visits/yr)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** Chief Operating Officer
**Stakeholders:** VP of Clinical Operations, Director of Revenue Cycle, Patient Access Manager, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **COO:** "Missed appointments are bleeding us — empty chairs, idle providers, patients who can't get a slot. The board approved a no-show reduction initiative. But before I spend a dollar on reminder texts and overbooking, I need to know our *actual* no-show rate. Right now I get a different number from every person I ask. One dashboard says 22%, the clinical team swears it's closer to 12%. I can't run an initiative against a number I don't trust."

> **VP Clinical Operations:** "Our true no-show rate is nowhere near what the ops dashboard shows. A no-show is when a patient just doesn't turn up and doesn't tell us. Half of what gets counted as a 'no-show' is a patient who *rescheduled* — they moved the visit, they're coming, the chair gets filled later. That's not a missed visit, that's a moved one. Counting those makes us look twice as bad as we are."

> **Patient Access Manager (later, on a call):** "I'm not going to lie to you about how the front desk keys these. When a patient calls to move an appointment, the slot's already empty for that day. Staff close it out however the location trained them — some mark it 'rescheduled', a lot just hit 'no-show' or 'missed' because that's the empty-chair button. Late cancels get the same treatment. We genuinely do not capture the difference cleanly, and every location does it a little differently."

> **Director of Revenue Cycle (separately):** "Be careful leaning on billing to figure out who showed. We bill office visits for attended patients, sure — but a couple of our locations also levy a *no-show fee*, so there are charges sitting against missed appointments. And claims post weeks after the visit, sometimes in a different month. Billing tells you about money, not attendance. Don't conflate the two."

You will notice the stakeholders **do not agree on what a no-show is**, and the front-desk data **does not cleanly separate a no-show from a reschedule or a cancellation**. That is not a detail to smooth over — *it is the engagement*. Your job is to design a model that makes the definitions explicit, separates moved/cancelled visits from genuinely missed ones, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the scheduling and revenue-cycle systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_PATIENTS` | one row per patient | "Demographics and home clinic. Registration date is when they first enrolled." |
| `RAW_DOCTORS` | one row per provider | "Provider roster with specialty and primary location. A few are inactive now." |
| `RAW_APPOINTMENTS` | one row per booked slot | "Status changes as the visit plays out. When a patient reschedules, the system books a *new* slot — it doesn't edit the old row. There are link columns that *should* connect the two, but I've never fully trusted them. And every location keys statuses a bit differently." |
| `RAW_BILLING` | one row per billed line | "Charges for visits. There's an office-visit line and, at some sites, a no-show fee. Claims post days to weeks after the service date — sometimes the next month." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What counts as a no-show?** A row whose status is `no_show`/`missed`? Only a *kept-intent* visit the patient never arrived for? Does a patient who rescheduled — and the front desk keyed as "no_show" — count? Does a late cancellation?
2. **What is the denominator?** No-show *rate* of what — all booked slots, all non-cancelled slots, only visits the patient intended to keep? The denominator changes the headline as much as the numerator does.
3. **How should rescheduled appointments be tracked?** A reschedule is a *chain*: an original slot and a later slot the patient moved to. Do you collapse the chain to one logical visit? Keep both? Which slot "owns" the eventual attendance outcome? How do you avoid double-counting a single patient intent as two missed visits?
4. **How do you reconcile the status flags across locations?** `no_show`, `missed`, `no-show`, `cancelled`, `rescheduled` — some are synonyms, some are genuinely different states keyed inconsistently. What is your canonical status?
5. **Can billing be trusted as an attendance signal?** No-show fees mean a charge can exist against a missed visit. Should billing ever override the scheduling status, or only corroborate it?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Clinical Ops and Revenue Cycle push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Appointment fact model** — a clean, documented fact table at one row per *logical* appointment, with a canonical status, a clear no-show flag, and reschedule chains resolved (so a moved visit is not counted as a miss).
2. **Patient engagement mart** — patient-grain (or patient-month-grain) metrics: visit count, true no-show count and rate, reschedule rate, cancellation rate, attended rate, and an engagement/risk signal the COO can act on.
3. **The no-show reconciliation** — a model or report that **explains the ~22% → ~13% spread**: how much of the naive no-show count is genuine misses, how much is rescheduled-but-misflagged, how much is cancelled-but-misflagged. Clinical Ops must be able to walk the bridge from the "ops dashboard number" to the "true" number.
4. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
5. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
6. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** Every booked slot must land in exactly one canonical status. A reschedule chain must reconcile to one logical visit — your true-no-show count plus rescheduled plus cancelled plus attended must account for the population without double-counting.
- **Document the spread, don't hide it.** A model that simply reports a 13% no-show rate without explaining why the ops dashboard says 22% has failed the engagement. The client needs to understand *why* the numbers differed and which one to trust for which decision.

---

## 6. Definition of done

You are done when you can sit across from the VP of Clinical Operations and the Director of Revenue Cycle — who disagree — and:

1. Show them a single appointment fact both can pull their number from.
2. Walk them across the bridge that explains the ~22% vs ~13% spread, line by line (reschedule misflags, cancel misflags, genuine misses).
3. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source (front-desk keying, the link columns, no-show-fee billing).
4. Defend every definitional choice with a written assumption — especially what a no-show *is*, the denominator, and how reschedule chains collapse.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
