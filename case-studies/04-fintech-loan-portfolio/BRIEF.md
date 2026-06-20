# Engagement 04 — Fintech Loan Portfolio Monitoring

**Client:** LendWell — a digital lending platform serving West African consumers and small businesses (~₦40bn originated to date, 4 years old)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** Chief Risk Officer (CRO)
**Stakeholders:** Head of Credit Risk, Head of Collections, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **CRO:** "Every board pack we publish a portfolio-at-risk number. Last quarter we reported PAR around **6%** and told investors the book was healthy. Then a lender doing due diligence ran their own cut and came back with something closer to **double that**. Now I have a credibility problem. I cannot tell which number is real, and if the higher one is right, we are under-provisioned and that is a regulatory issue. I need one PAR number I can sign my name to."

> **Head of Collections:** "Our register is accurate — it lists every loan we've formally defaulted. If a borrower fell behind and we restructured them onto a new plan, they are *not* in default, they are performing again. You can't count a restructured loan as bad; we gave them a fresh start and most of them pay. Counting them as defaults would be punishing the customers we rescued."

> **Head of Credit Risk (later, privately):** "Collections is marking their own homework. When a loan goes bad they 'restructure' it — which just resets the days-past-due clock to zero and moves it off the watch-list. The borrower's behaviour hasn't changed; a lot of them are 90-plus days down again on the *new* schedule. The default register only shows the ones Collections chose to write up. The repayment ledger doesn't lie. Compute PAR from what people actually paid and you'll see the real number."

You will notice the two stakeholders **do not agree on what a default is, or on whether a restructured loan can be at-risk.** That is not a detail to smooth over — *it is the engagement.* Your job is to design a model that computes portfolio-at-risk from first principles (the repayment ledger), makes the definitions explicit, reconciles it against the reported register, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned. The book is observed **as at a single month-end reporting date** (30 June 2025); all days-past-due and PAR maths is relative to that date.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_APPLICATIONS` | one row per application | "Only approved ones become loans. Decline reason is only filled for declines. Underwriting timestamps are usually sane." |
| `RAW_LOANS` | one row per funded loan | "`LOAN_STATUS` is the *current* state from the servicer. When we restructure a loan we stamp a new first-due date — the schedule on the record is the new one, not the original." |
| `RAW_REPAYMENTS` | one row per repayment posting against an instalment | "Each instalment gets postings. Some are partial. A 'missed' row means it was due and nobody paid. I think the gateway double-posts the odd one — never had time to dig in." |
| `RAW_DEFAULTS` | one row per loan Collections formally flagged | "This is Collections' register. It's hand-maintained and it lags the ledger. It's what Finance reports PAR from today." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What *is* a default?** A loan whose oldest unpaid instalment is 30 days past due? 60? 90? Or only a loan Collections wrote into the register? The two teams answer this differently, and the threshold you pick *is* the PAR number.
2. **How does a restructuring affect the default clock?** When a loan is restructured the servicer resets its first-due date. Do you honour the reset (clock starts fresh) or do you measure delinquency against the *original* schedule? This single choice is most of the gap.
3. **How should partially-paid instalments be reported?** Is a short-paid instalment "performing", "at-risk", or partially both? A partial posting is not the same as a missed one — don't conflate them.
4. **What is the active book?** Do closed/settled loans count in the denominator? Pending and declined applications? Get the denominator wrong and every ratio is wrong.
5. **What do you do with the gateway's duplicate repayment postings** so you don't over-credit a loan and accidentally mark a bad loan as performing?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Credit Risk and Collections push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Loan performance mart** — a clean, documented, risk-trustworthy fact table at a defensible grain (one row per loan on the active book, with its current days-past-due and risk bucket).
2. **Portfolio metrics** — at minimum: *PAR30, PAR90 (by loan count **and** by outstanding value), reported default rate, restructure rate, partial-payment rate.* Each with a written definition.
3. **A reconciliation** — a model or report that **explains the reported-vs-true PAR gap**: how much of the hidden risk is restructured re-defaulters, how much is genuinely-delinquent loans never written into the register, how much is timing. Risk must be able to walk the bridge from "Collections' reported PAR" to "ledger-true PAR."
4. **A repayment pipeline** — the intermediate model that turns the raw posting feed (partials, missed rows, duplicates) into a clean per-instalment and per-loan delinquency state.
5. **A default-definition document** — the written policy: DPD threshold chosen, restructuring treatment, partial-payment treatment, with rationale. This is a deliverable in its own right.
6. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
7. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
8. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** Your true-PAR figure must be reproducible from the raw repayment ledger; your reconciliation must account for the difference against the default register line by line.
- **Document the gap, don't hide it.** A model that makes the discrepancy *disappear* — or that simply adopts Collections' register wholesale — has failed the engagement. The client needs to understand *why* the numbers differed and which loans are hiding.

---

## 6. Definition of done

You are done when you can sit across from the Head of Credit Risk and the Head of Collections — who disagree — and:

1. Show them a single mart both can pull their number from.
2. Walk them across the bridge that explains the reported-vs-true PAR gap, line by line — naming the restructured loans that are 90-plus days down on their new schedule.
3. Tell them which data quality issues you found (duplicate postings, partials, clock skew, currency), which you fixed, and which they need to fix at the source.
4. Defend every definitional choice — DPD threshold, restructuring treatment, partial handling — with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
