# Engagement 08 — HR Workforce Analytics

**Client:** Northwind Atlas — an enterprise software & services company (~9,000 employees, 10 departments across 3 divisions, offices in 6 locations)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** Chief People Officer (CPO)
**Stakeholders:** VP of Talent (retention), Head of Finance / FP&A (headcount & cost), Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **CPO:** "Every quarter I present workforce health to the board — headcount, attrition, average tenure. And every quarter the numbers I get from Talent don't match the numbers Finance pulls. Our attrition is reported anywhere between **22 and 33 percent** depending on who you ask, and average tenure swings by **almost a year**. The board wants to know if we have a retention problem or not. I genuinely cannot tell them, and that is not acceptable."

> **VP of Talent:** "My attrition number is the *real* one — it counts people who actually left the company and didn't come back. Finance is inflating it. Every time someone moves from Sales to Customer Success, their system closes the old record and Finance counts that internal move as an *exit*. It isn't. That person never left. And when someone we lost comes back six months later, Finance treats them as a brand-new hire with zero tenure, which tanks our average-tenure number."

> **Head of Finance / FP&A (later, privately):** "Talent doesn't reconcile to the ledger. I count what the HRIS tells me: an employment record with a termination date is a termination, full stop. If their 'continuous tenure' theory were right, we'd be paying people for years they weren't even here — we had a rehire who was gone for eighteen months and Talent wants to count that gap as tenure. And their 'it was just a transfer' records still close out a headcount in the old cost center. My cost-center headcount has to tie to payroll."

You will notice the two stakeholders **do not agree on what "left the company" or "tenure" means** — and both are partly right. Internal transfers and rehires are the crux. That disagreement is not a detail to smooth over — *it is the engagement*. Your job is to model internal movement explicitly, define tenure across rehire gaps, reconcile the spread, and let each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the HRIS export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the people systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_EMPLOYEES` | one row per **employment record** (not per person) | "Careful here — it's *not* one row per human. When someone transfers departments or is rehired, the system closes the old record and opens a new one with a new `EMPLOYEE_ID`. There's a `PERSON_ID` that *should* be stable across all of a person's records. There's also a `PRIOR_EMPLOYEE_ID` on some rows that points back. Status and termination date don't always agree — I've seen 'terminated' rows with no end date." |
| `RAW_DEPARTMENTS` | one row per department | "Clean reference table. Departments roll up to divisions and have a cost center." |
| `RAW_PERFORMANCE_REVIEWS` | one row per review | "Annual cycle, references the employment record. Some reviews are missing their date — the cycle-close job has failed a few times. I think there might be some duplicate submissions too." |
| `RAW_PAYROLL` | one row per employee per monthly pay period | "Local payroll, so it's multi-currency. First and last months of a stint are prorated. A few runs got cancelled and re-issued, so watch for duplicate periods." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What is the grain of "an employee"?** A `PERSON_ID`? An `EMPLOYEE_ID` (employment record)? The two produce different headcounts and different attrition. You must pick a person-grain mart and defend it.
2. **How should internal movement (department transfers) be modeled?** A transfer closes one record and opens another. Is that an *exit + a hire*, or one continuous employment? This single choice drives most of the attrition spread.
3. **What defines tenure across rehires?** A person who left and returned has a *gap*. Is tenure (a) continuous from first-ever hire, (b) only the current stint, or (c) total time-in-seat summed across stints excluding gaps? Each is defensible — pick one, define it, and surface the others.
4. **What counts as attrition / a termination?** Does an internal transfer count? Does a rehired person's original departure still count once they're back? Over what period do you measure (annualized? trailing-12)?
5. **How do you reconcile conflicting status?** Some records say `terminated` with no `TERMINATION_DATE`; some say `transferred`. Which field is authoritative, and what do you do with the contradictions?
6. **How do you handle duplicate employment records and duplicate payroll periods** so headcount and cost don't double-count?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Talent and Finance push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Workforce mart** — a clean, documented, person-grain fact table that stitches a person's employment records (transfers + rehires) into a coherent employment history at a defensible grain.
2. **Attrition & tenure metrics** — at minimum: *active headcount, attrition rate (annualized), average tenure (continuous AND current-stint), rehire rate, internal-mobility rate.* Each with a written definition.
3. **A reconciliation** — a model or report that **explains the 22–33% attrition spread and the ~1-year tenure spread**: how much is internal transfers miscounted as exits, how much is rehires resetting the tenure clock, how much is duplicate records. Leadership must be able to walk the bridge from "Finance's record-based number" to "Talent's person-based number."
4. **Department reporting layer** — headcount, attrition and tenure by department/division/cost-center, correctly attributing transfers (a transfer should *reduce* the source department and *increase* the destination, not register as an exit).
5. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
6. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
7. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** Person-grain headcount must reconcile to distinct active people; department headcount must sum to the company total; payroll cost (deduped, currency-normalized) must reconcile to active employment. If your numbers don't tie to the raw feeds you have not finished.
- **Document the spread, don't hide it.** A model that makes the discrepancy *disappear* without explaining it has failed the engagement. Leadership needs to understand *why* Talent and Finance differed.

---

## 6. Definition of done

You are done when you can sit across from the VP of Talent and the Head of Finance — who disagree — and:

1. Show them a single mart both can pull their number from.
2. Walk them across the bridge that explains the attrition and tenure spread, line by line (transfers miscounted as exits, rehire clock resets, duplicate records).
3. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source (status-vs-date conflicts, missing review dates).
4. Defend every definitional choice — internal-movement model, tenure-across-rehire rule, attrition window — with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
