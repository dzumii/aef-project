# Engagement 02 — Ride-Hailing Marketplace Analytics

**Client:** Cobalt Mobility — an Uber-like mobility startup operating in four cities (~1M trips/yr, Series B)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** Chief Operating Officer
**Stakeholders:** VP of Growth, Head of Finance, Head of Driver Operations, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **COO:** "We are raising our Series C and every deck has a different top-line number. Growth puts GMV on the board — gross bookings, the headline we tell investors. Finance reports net revenue, and it comes in **8 to 12 percent lower**, every month, by an amount that moves around. When a partner asks me 'what does Cobalt actually earn per trip,' I get three answers from three teams. I need one source of truth before the round, and I need to trust it."

> **VP Growth:** "GMV is the marketplace's true size — it's every fare riders agreed to pay, across every trip we matched. That's the number that shows momentum. Finance keeps shrinking it by stripping out cancellations and fraud and calling the rest 'real.' Those trips still happened on our platform. That's the business."

> **Head of Finance (later, privately):** "Growth is booking money we never collected and some we had to give back. A fare on a cancelled trip isn't revenue. A fare on a ride the fraud team reversed isn't revenue. And don't get me started on driver incentives — we're paying bonuses against trips that we then find out were fraudulent, or paying the *same* trip twice because two campaigns overlapped. Our take rate looks healthy right up until you net all that out."

> **Head of Driver Operations (in the same room, bristling):** "My driver-earnings dashboard is the one drivers actually see, and it has to match what hits their bank account. If Finance 'nets out' incentives in some restated month, a driver's payout history stops reconciling and my support queue explodes. Whatever you build, a driver's paid bonuses cannot quietly change."

You will notice the stakeholders **do not agree on what counts, what's earned, or who's active.** That is not a detail to smooth over — *it is the engagement.* Your job is to design a model that makes the definitions explicit, reconciles the GMV-vs-net gap, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Five raw tables, landed in your Snowflake sandbox (`RIDEFLOW.RAW`) by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_RIDERS` | one row per rider account | "`ACCOUNT_STATUS` is the CRM flag — `active` just means the account isn't closed, not that they've ridden recently. Don't confuse it with someone who's actually using us." |
| `RAW_DRIVERS` | "one row per driver" | "Should be one row per driver… but the onboarding service reuses `DRIVER_ID` when a churned driver comes back, so a few have two rows. Never had time to dig in." |
| `RAW_TRIPS` | one row per trip request | "`GROSS_FARE` is the fare at request time — that's what Growth sums for GMV. Cancellations sometimes carry a fee, sometimes zero. The fraud flag gets set *after the fact* by the fraud team." |
| `RAW_PAYMENTS` | one row per capture *attempt* | "The processor logs every attempt. Cards get retried. I think the webhook double-logs some settled captures — there might be duplicates in here." |
| `RAW_DRIVER_INCENTIVES` | one row per incentive line | "Honestly the messiest. Payouts run weekly, and a single trip can show up on more than one campaign line. Bonuses often pay out a month after the trip." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What counts as an "active rider"?** The CRM `active` flag? Anyone who *requested* a trip in a trailing window? Anyone who *completed* one? Only non-fraud completed trips? The count swings by **10–15%** depending on which you pick.
2. **How should cancelled trips be classified?** Are billed cancellations (rider charged a fee, or driver already arrived) revenue, a fee line, or leakage? Do zero-fare and `no_driver_found` cancellations belong in GMV at all?
3. **What is a "fraudulent" trip, and how does it flow through revenue?** The flag arrives *after* the trip. Does fraud GMV get reversed out? Is the driver's incentive on a fraud trip clawed back, and if so, in which period?
4. **When is revenue recognized, and in what currency?** At trip end? At capture? `rivermouth` bills in GBP — do you convert, or scope to a reporting currency?
5. **How do you handle the duplicate / retried captures and the over-attributed incentives** so you don't double-count cash *or* double-count bonus spend?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Growth, Finance, and Driver Ops push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Driver performance mart** — clean, documented, at one row per *driver* (mind the re-onboarding duplicates), with trips, completion rate, fraud rate, gross earnings, and *de-duplicated* incentive spend.
2. **Rider activity mart** — one row per rider with an **explicit, multi-definition activity model** so Growth, Ops, and Finance can each read their own "active rider" count off the same table.
3. **Marketplace KPI layer** — GMV, net revenue, take rate, completed-trip count, cancellation rate, fraud rate, incentive spend — each with a written definition and a stated currency treatment.
4. **A reconciliation** — a model or report that **explains the 8–12% GMV-to-net gap**: how much is cancellations, how much is fraud, how much is duplicate captures, how much is incentive accounting. Leadership must be able to walk the bridge from "Growth GMV" to "Finance net revenue."
5. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
6. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
7. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

### Stretch goal (optional, not graded as core)
The trips feed carries pickup/dropoff coordinates. If you want, enrich trips with **distance and ETA** — call OpenRouteService or a local OSRM, or compute a haversine fallback with no external dependency — and add a *revenue-per-km* or *surge-vs-distance* view. This is a bonus, not required to reconcile the gap.

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** If your net revenue doesn't reconcile to the captured-cash ledger (deduped, minus fraud, minus non-revenue cancellations) you have not finished.
- **Driver payouts are sacred.** Per Driver Ops: a driver's *paid* incentive total in your driver mart must reconcile to the payouts ledger. You may de-duplicate over-attributed lines, but you must surface the de-dup — do not silently restate what a driver was paid.
- **Document the gap, don't hide it.** A model that makes the discrepancy *disappear* without explaining it has failed the engagement. Leadership needs to understand *why* the numbers differed.

---

## 6. Definition of done

You are done when you can sit across from the COO, VP Growth, Head of Finance, and Head of Driver Ops — who disagree — and:

1. Show them a single set of marts each can pull their number from.
2. Walk them across the bridge that explains the 8–12% GMV-to-net gap, line by line.
3. Show them the active-rider count under each definition and explain why they differ by 10–15%.
4. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source.
5. Defend every definitional choice with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
