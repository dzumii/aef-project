# Engagement 01 — E-Commerce Revenue Leakage Investigation

**Client:** Lumen & Loom — a fast-growing online home-goods retailer (~$40M GMV/yr, 3 years old)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** VP of Finance
**Stakeholders:** Head of Finance, Head of Operations, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **VP Finance:** "Every month I close the books and report a revenue number to the board. Every month Operations reports a *different* number from their dashboard. We're off by somewhere between **8 and 12 percent**, and it changes month to month. The board has started asking which number is real. I don't have a good answer. I need one source of truth, and I need to trust it."

> **Head of Operations:** "Look, my number is the honest one — it's what we actually fulfilled and shipped. Finance is counting orders that got cancelled and money we later refunded. That's not revenue, that's wishful thinking."

> **Head of Finance (later, privately):** "Ops doesn't understand revenue recognition. If a customer paid us in March, that's March revenue, even if it shipped in April. They're mixing up cash, bookings, and revenue and calling it all 'sales'."

You will notice the two stakeholders **do not agree on what revenue means**. That is not a detail to smooth over — *it is the engagement*. Your job is to design a model that makes the definitions explicit, reconciles the gap, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_ORDERS` | one row per order | "Status changes over time. The amount is the order total at placement." |
| `RAW_PAYMENTS` | one row per payment *attempt* | "The gateway logs every attempt. Customers retry failed cards. I think there might be some duplicates in here — never had time to dig in." |
| `RAW_REFUNDS` | one row per refund | "Refunds can be partial. They don't always happen in the same month as the order. Some come in weeks later." |
| `RAW_SHIPPING` | one row per shipment | "Honestly the shipping feed is the messiest. Timestamps go missing when the carrier API times out." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What is a "completed" order?** Placed? Paid? Shipped? Delivered? Not-refunded? The two teams answer this differently.
2. **When should revenue be recognized?** At payment? At ship? Pro-rated? This drives the month-boundary mismatch.
3. **How should refunds be treated?** Net against original-order month, or recognized in the month the refund occurred? Partial refunds?
4. **How do you handle a customer who paid but the order was cancelled?** Is that revenue? A liability? Leakage?
5. **What do you do with the duplicate / retried payments** so you don't double-count cash?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Finance and Ops push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Revenue mart** — a clean, documented, finance-trustworthy fact table at a defensible grain.
2. **Finance-ready metrics** — at minimum: *gross revenue, net revenue, refund rate, cancellation leakage, recognized revenue by month.* Each with a written definition.
3. **A reconciliation** — a model or report that **explains the 8–12% gap**: how much is cancellations, how much is refunds, how much is timing, how much is duplicate payments. Finance must be able to walk the bridge from "Ops number" to "Finance number."
4. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
5. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
6. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** If your "net revenue" doesn't reconcile to the raw payment ledger (minus refunds, minus duplicates) you have not finished.
- **Document the gap, don't hide it.** A model that makes the discrepancy *disappear* without explaining it has failed the engagement. The client needs to understand *why* the numbers differed.

---

## 6. Definition of done

You are done when you can sit across from the VP of Finance and the Head of Operations — who disagree — and:

1. Show them a single mart both can pull their number from.
2. Walk them across the bridge that explains the 8–12% gap, line by line.
3. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source.
4. Defend every definitional choice with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
