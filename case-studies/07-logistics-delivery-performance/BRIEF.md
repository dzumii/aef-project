# Engagement 07 — Logistics Delivery Performance Investigation

**Client:** Cartwright Freightways — a regional parcel & freight carrier (~4M deliveries/yr, 12 distribution centers, 4 regions)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** VP of Operations
**Stakeholders:** Head of Customer Experience, Head of Network Operations, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **VP Operations:** "Our on-time delivery rate is the number the board sees, the number our sales team quotes to win contracts, and the number in our SLA penalty clauses. Right now I have one dashboard saying we're at **88%** and a customer-facing report saying we're closer to **79%**. Customers are escalating about late parcels while we tell them we're hitting target. I need one on-time number I can defend in front of a client *and* a regulator."

> **Head of Customer Experience:** "The 88% is fiction. It only counts deliveries where the carrier feed actually sent us a final delivered-timestamp. The deliveries where the feed went dark — those are exactly the ones that went wrong, the ones customers are calling about — and we just *drop them from the math*. If we can't prove a parcel arrived on time, it wasn't on time. Count those as misses and we're at 79%, which matches what customers are screaming at me."

> **Head of Network Operations (later, privately):** "CX wants to punish us for a carrier API timeout. A dropped scan event is a *data* problem, not a *delivery* problem — most of those parcels did arrive, we just never got the webhook. Penalising every missing timestamp as a late delivery means we're reporting failures we didn't have. Exclude the ones we can't measure, or impute them sensibly. Don't manufacture a crisis out of feed gaps."

You will notice the two stakeholders **do not agree on what an on-time delivery is** — or, more precisely, on what to do with the deliveries the data can't speak to. That is not a detail to smooth over — *it is the engagement*. Your job is to design a model that makes the definition explicit, quantifies how much the on-time rate swings depending on that choice, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_ORDERS` | one row per order | "Carries `PROMISED_DELIVERY_AT` — the window the customer was quoted. That's the SLA clock; on-time is measured against it." |
| `RAW_WAREHOUSES` | one row per origin DC | "Master data. Small. Has lat/long if you want to play with distances." |
| `RAW_DRIVERS` | one row per *employment record* | "Heads up: the name isn't a key. Drivers leave and come back — a rehire gets a brand-new `DRIVER_ID` with the same name." |
| `RAW_DELIVERIES` | one row per delivery event | "Honestly the messiest feed. It's stitched from a few carrier APIs. Some deliveries get reported twice, and `DELIVERED_AT` goes missing whenever a carrier feed times out." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What defines an "on-time" delivery?** Delivered on or before `PROMISED_DELIVERY_AT`? Measured in which timezone — the DC's, the destination's, UTC? Inclusive of the promised day or strictly before?
2. **How do you handle a delivery with a missing `DELIVERED_AT`?** This is the whole ballgame. Three defensible stances: **exclude** (judge only what you can measure), **impute** (estimate the delivery time / assume on-time), or **fail** (no proof of on-time = counted as a miss). Each yields a *materially different* on-time rate.
3. **How should incomplete deliveries be handled?** A `failed` delivery never completed. Is it out of the denominator (it's not a delivery), or is a failed delivery the worst kind of SLA miss and therefore *in* it?
4. **What is the delivery grain when a delivery is double-reported?** Two carrier feeds logged the same physical drop. Which row is the truth, and how do you avoid counting one delivery as two?
5. **How do you attribute a delivery to a driver** when the same person spans multiple `DRIVER_ID`s (rehires)? Per-employment-record, or per-person?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when CX and Operations push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Delivery performance mart** — a clean, documented fact table at one delivery per order, with on-time determination and the promised-vs-actual transit time.
2. **SLA tracking framework** — on-time rate by service level, region, DC, and carrier, by month. At minimum: *on-time rate, late rate, incomplete/failed rate, average transit days vs promised, count of unmeasurable (null-timestamp) deliveries.* Each with a written definition.
3. **The on-time reconciliation** — a model or report that **explains the 88% vs 79% spread**: how much of the gap is null-timestamp handling, how much is incomplete deliveries, how much is duplicate scans. Operations and CX must be able to walk the bridge from one number to the other, line by line.
4. **Data quality monitoring** — your tests + what severity each is + what happens when one fails in production. The null-timestamp rate and duplicate-scan rate are themselves metrics worth monitoring, not just things to clean.
5. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
6. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

**Optional stretch:** `RAW_WAREHOUSES` carries lat/long and orders carry a destination region. You *may* enrich the mart with haversine distance or a geocoding/routing API to estimate expected transit time per lane and flag SLAs that were unrealistic to begin with. Entirely optional — the engagement stands without it.

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **The numbers must tie out.** Your on-time numerator + late + unmeasurable + incomplete must account for every order in the denominator. If they don't sum, you have not finished.
- **Document the spread, don't hide it.** A model that reports a single on-time number without disclosing how sensitive it is to the null-timestamp decision has failed the engagement. The client needs to understand *why* the two dashboards disagreed.

---

## 6. Definition of done

You are done when you can sit across from the VP of Operations, the Head of Customer Experience, and the Head of Network Operations — who disagree — and:

1. Show them a single mart all three can pull their number from.
2. Walk them across the bridge that explains the 88% vs 79% spread, line by line — and name which line is a *policy choice* (how to treat unmeasurable deliveries) versus a *data-quality defect* (the feed dropping timestamps).
3. Tell them which data quality issues you found, which you fixed, and which they need to fix at the source (the carrier feed).
4. Defend every definitional choice — especially the null-timestamp stance — with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
