# Engagement 06 — Subscription Business Metrics Platform

**Client:** StreamNine — a fast-growing streaming/SaaS platform (~$5M ARR, 4 years old, ~40K subscribers)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** VP of Finance
**Stakeholders:** Head of Finance, Head of Growth (Product), RevOps Lead, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **VP Finance:** "I have three dashboards open right now and every one of them shows a different MRR. Finance says one number, Growth says a bigger one, RevOps says a smaller one. They're spread somewhere between **8 and 12 percent**, and the gap moves every month. We're raising a round and the diligence team is going to ask me what our MRR is. I cannot say 'it depends who you ask.' I need one number, and I need to trust it."

> **Head of Growth (Product):** "A paused subscriber hasn't left — they hit pause for a month while travelling, and the vast majority come back. They're retained revenue. If you strip every paused seat out of MRR you're under-reporting the health of the business and making my retention look worse than it is. Paused counts."

> **Head of Finance (later, privately):** "Growth is booking revenue we are not collecting. A paused subscription bills *nothing*. You cannot put a dollar of MRR against an account that is generating zero cash this month. And while we're at it — they're counting the full plan price the day someone upgrades mid-cycle, when we only prorated a few dollars. That's not how recognition works."

> **RevOps Lead:** "Honestly I think you're both wrong. `past_due` accounts haven't paid either — their last charge bounced. I only count subscriptions that are genuinely active and current. My number is the smallest and it's the only one I'd bet on."

You will notice the stakeholders **do not agree on what counts toward MRR** — specifically how to treat *paused* subscriptions, *past_due* accounts, and *mid-cycle proration*. That is not a detail to smooth over — *it is the engagement*. Your job is to design a model that makes each definition explicit, reconciles the spread, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Five raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the billing and product systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_USERS` | one row per subscriber (current state) | "Status is whatever the billing system last wrote. `paused` means billing is suspended but they kept the seat. I *think* `cancelled_at` always means cancelled — but I've seen it set on accounts that look active. Never had time to dig in." |
| `RAW_PLANS` | one row per plan in the catalogue | "Static reference. `MONTHLY_PRICE` is the list monthly price. Annual plans bill twelve times that, at signup." |
| `RAW_PAYMENTS` | one row per charge *attempt* | "The billing system logs every attempt, including retries on declined cards. Proration charges show up here too as their own rows. There may be some duplicates — webhooks fire twice sometimes." |
| `RAW_UPGRADES` | one row per upgrade event | "When someone moves up a tier mid-cycle we prorate the difference for the rest of the period. The proration amount is in the row." |
| `RAW_DOWNGRADES` | one row per downgrade event | "Some downgrades are immediate with a credit, some are scheduled for the next cycle. The `change_type` tells you which. The scheduled ones don't change anything until later." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What is an "active subscriber"?** Only `active`? `active` + `paused`? `active` + `past_due`? Each team draws the line differently, and the count moves by double digits depending on where you draw it.
2. **How should paused subscriptions be treated in MRR?** Counted at full plan price (retained seat)? Excluded (zero cash this month)? Counted at a reduced rate? This is the single biggest driver of the spread.
3. **How is mid-cycle proration handled?** When someone upgrades on day 18 of a 30-day cycle, does MRR jump by the full new plan price immediately, by the prorated remainder, or only at the next renewal? Same question, mirrored, for immediate vs scheduled downgrades.
4. **Do `past_due` accounts count?** Their last charge failed. Are they still subscribers (grace period) or already effectively churned?
5. **What is the run-rate convention?** Is MRR the sum of current recurring plan prices (a snapshot), or the recurring cash that actually settled this month? These produce different numbers and you must pick one and label it.
6. **What do you do with the duplicate / retried charges** so you don't double-count cash, and with annual plans billed 12× upfront (is that $X MRR or $12X this month)?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Finance, Growth, and RevOps push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Subscription mart** — a clean, documented fact table at one subscriber-period grain, carrying current plan, status, and effective recurring amount.
2. **MRR calculation with an explicit definition** — a model that computes MRR, with a written, defended definition of: which statuses count, how paused is treated, how proration rolls into the run-rate, and how annual plans are normalised to monthly. The definition is a deliverable, not an afterthought.
3. **Retention metrics** — at minimum: active-subscriber count, gross MRR churn, net MRR retention (incl. expansion from upgrades / contraction from downgrades), and pause rate. Each with a written definition.
4. **A reconciliation** — a model or report that **explains the 8–12% MRR spread**: how much is paused handling, how much is `past_due` treatment, how much is mid-cycle proration timing, how much is duplicate charges. Each stakeholder must be able to walk the bridge from their number to the agreed number.
5. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
6. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
7. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** Your "recognised recurring revenue" must reconcile to the deduped, succeeded `renewal` + `proration` charge ledger for the period. If it doesn't, you have not finished.
- **Document the spread, don't hide it.** A model that makes the discrepancy *disappear* without explaining it has failed the engagement. The client needs to understand *why* the numbers differed — and which definition you chose, and why.
- **MRR is a definition, not a fact.** There is no single "correct" MRR. There is a *defensible, documented, reproducible* one. Your job is to pick it, label it, and bridge to the others.

---

## 6. Definition of done

You are done when you can sit across from the VP of Finance, the Head of Growth, and the RevOps Lead — who disagree — and:

1. Show them a single subscription mart all three can pull their number from.
2. State the official MRR definition and walk each of them across the bridge from their number to it, line by line (paused, past_due, proration, duplicates).
3. Show retention metrics that hold up under each definition.
4. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source.
5. Defend every definitional choice with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
