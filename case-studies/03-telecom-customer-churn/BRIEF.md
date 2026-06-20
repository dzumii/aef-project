# Engagement 03 — Telecommunications Customer Churn

**Client:** Northwind Cellular — a national mobile carrier (~6.2M lines, prepaid + postpaid, 14 years old)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** Chief Revenue Officer (CRO)
**Stakeholders:** VP of Marketing, Director of Billing & Collections, Network Operations Lead, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **CRO:** "Every quarter I stand in front of the board and report a churn number. The problem is I have *three* churn numbers, and they don't agree. Marketing says we're churning around 12%. Billing says it's closer to 18%. The network team — who I actually believe least and most at the same time — says nearly a quarter of our base is gone. The spread is more than ten points. When an analyst on the call asks 'so how many customers did we actually lose?' I have nothing. I need one place where all three numbers live side by side, and I need to know *why* they differ."

> **VP Marketing:** "A customer is churned when they tell us they're leaving — when they cancel. Full stop. That's the number that matters for retention campaigns and for the LTV models. If billing wants to call a late payment 'churn,' fine, but that's a collections problem, not a churned customer. Half those people pay the next week. And the network team counting 'no usage' as churn? Some of those are snowbirds with a second line they barely touch. They're still paying us."

> **Director of Billing & Collections (later, privately):** "Marketing lives in a fantasy. A 'customer' who hasn't paid in two billing cycles is gone — the revenue is gone, that's what churn *is*. And here's the part nobody wants to hear: a big chunk of our cancellations aren't customers choosing to leave, they're *us* disconnecting them for non-payment. Involuntary churn. If you lump that in with people who voluntarily left for a competitor, your retention metrics are garbage and your win-back budget gets aimed at the wrong people."

> **Network Operations Lead:** "I don't care what the billing flag says. If a line hasn't touched the network in 30 days — no voice, no data, no SMS — that customer is functionally gone, and they were gone *weeks* before billing or sales noticed. The account can say 'active' and the radio says otherwise. Oh, and watch out: some lines we marked cancelled are lighting up again. People port back. The billing table won't tell you that — the *usage* will."

You will notice the stakeholders **do not agree on what "churned" means** — and each disagreement maps to a different source system (billing status, payment ledger, network usage). That is not a detail to smooth over — *it is the engagement*. Your job is to build a customer mart that carries **multiple churn flags side by side**, reconciles the spread between them, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Five raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_SUBSCRIBERS` | one row per subscriber line | "This is the billing system's view. `ACCOUNT_STATUS` is what *they* think the line is. I've seen the same `SUBSCRIBER_ID` show up more than once after SIM swaps — never had time to confirm." |
| `RAW_PLANS` | one row per plan | "Small reference table. Prepaid lines have no contract; postpaid are 24-month." |
| `RAW_USAGE` | one row per daily usage-mediation record | "This is the network feed — voice, data, SMS. It's big. Mediation replays batches sometimes, so I wouldn't be shocked if there are duplicate records in there." |
| `RAW_SUPPORT_TICKETS` | one row per support contact | "Retention tickets spike around churn. Some tickets never got a resolved timestamp — still open, or the feed dropped it." |
| `RAW_PAYMENTS` | one row per billing charge / top-up | "Postpaid is one row per monthly charge; prepaid is per top-up. `PAYMENT_STATUS` tells you if it cleared. Failed charges sometimes get retried and settle later." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **When exactly is a customer churned?** No usage for 30 days? A payment lapsed beyond a grace window? An explicit cancellation flag? Each team answers differently, and each answer is a different population.
2. **How should reactivated customers be treated?** A line marked `cancelled` that is using the network again — is that a churn that reversed (so: not churned), a churn-then-reacquire (two events), or still churned because billing says so?
3. **Is involuntary churn the same as voluntary churn?** Carrier-initiated disconnects for non-payment look identical to voluntary cancels in `ACCOUNT_STATUS`. Should they count the same? Marketing and Billing disagree.
4. **What is the observation date and window?** "30-day-no-usage" and "payment lapse" are both *as-of* a date. Pick it, state it, and apply it consistently across all three definitions or the numbers won't be comparable.
5. **How do you handle the duplicate subscriber rows and replayed usage records** so you don't double-count lines or mistake a replay for genuine activity?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Marketing, Billing, and Network all push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Unified customer mart** — one clean, documented row per subscriber line at a defensible grain, carrying **at least three churn flags side by side** (`is_churned_no_usage`, `is_churned_payment_lapse`, `is_churned_explicit_cancel`) plus the supporting fields (last usage date, last paid period, account status, disconnect reason, reactivation flag).
2. **Churn-rate metrics** — at minimum: *churn rate under each of the three definitions, voluntary vs. involuntary split, reactivation rate, and a "churned under any" / "churned under all" pair.* Each with a written definition.
3. **A reconciliation** — a model or report that **explains the ~10-point spread** between the three churn rates: how much of the gap is silent-but-active lines, how much is payment lapses that haven't been cancelled yet, how much is reactivations the billing table misses, how much is involuntary disconnects. The CRO must be able to walk from the Marketing number to the Network number, line by line.
4. **Churn model definitions doc** — a written page that states each definition, the population it captures, the window/observation date, and which stakeholder it serves.
5. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
6. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
7. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The definitions must be comparable.** All three churn flags must be evaluated as of the *same* observation date against the *same* deduplicated subscriber base, or the spread is meaningless.
- **Document the gap, don't hide it.** A mart that reports a single blended churn number and buries the disagreement has failed the engagement. The client needs every definition visible *and* a reconciliation between them.

---

## 6. Definition of done

You are done when you can sit across from Marketing, Billing, and Network — who disagree — and:

1. Show them one mart from which all three pull their own churn number.
2. Walk them across the bridge that explains the ~10-point spread, line by line.
3. Tell them how you treated reactivations and involuntary churn, and defend it.
4. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source.
5. Defend every definitional choice with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
