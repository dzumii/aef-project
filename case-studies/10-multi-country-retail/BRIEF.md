# Engagement 10 — Multi-Country Retail Analytics Platform

**Client:** GlobeMart — a retail chain operating ~40 stores across 8 countries (~$3M consolidated revenue/yr in the data you'll receive; the real chain is far larger)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** Group CFO
**Stakeholders:** Group CFO, VP of International Operations, Group Financial Controller, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **Group CFO:** "We just merged eight country P&Ls into one board deck for the first time, and I have three different consolidated revenue numbers from three analysts — all 'correct', all in USD, all built from the same sales. They're a few percent apart. A few percent of group revenue is a number the board notices. I need ONE consolidated revenue figure I can sign, and I need to know exactly why it's that figure and not the other two."

> **VP of International Operations:** "The honest number is what each store rang up, on the day it rang it up, at that day's exchange rate. That's what actually happened on the ground. Anything else is finance massaging the currency to make a quarter look better. Convert each sale at the rate on the day it sold and add it up — done."

> **Group Financial Controller (later, privately):** "Ops doesn't understand consolidation. You cannot revalue every one of millions of transactions at a different daily spot rate and expect the board to compare quarters — the FX noise drowns out the actual trading performance. We close each month at the month-end rate, and for the annual plan we hold a single budget rate so variances are real, not currency artefacts. The 'transaction-date' number is unstable and un-budgetable."

You will notice the two stakeholders **do not agree on which exchange rate converts a local sale into reporting-currency revenue.** That is not a detail to smooth over — *it is the engagement.* Ops wants transaction-date spot. The Controller wants month-end (for closing) and a fixed budget rate (for planning). Each choice produces a *different consolidated total from the identical underlying sales*, and the gap between them is the few percent the CFO is staring at. Your job is to make the FX policy explicit, quantify how much the total moves under each policy, and let each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned. Crucially, **there is no USD column anywhere** — every monetary value is in the store's local currency, and the conversion rates are not reliably in the warehouse.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_SALES` | one row per sale | "Amounts are in the store's local currency — there's no USD anywhere. Timestamps are local wall-clock; I don't think we store the offset. There might be a few re-rung sales from terminal re-syncs, and some sales lost their sold-time in the integration." |
| `RAW_STORES` | one row per store | "Maps store → country → local currency → timezone. There's a `reporting_calendar` column too — most stores are on the gregorian month but a few legacy ones still close on a 4-4-5 retail calendar." |
| `RAW_INVENTORY` | one row per store × category × snapshot | "Roughly monthly stock snapshots. Value is units × local unit cost, so it's in local currency too — same FX problem as sales." |
| `RAW_CURRENCY_RATES` | one row per currency × date | "Honestly, don't trust this table. It's a legacy spreadsheet someone loaded. It only covers part of the year, has no weekend rows, and I'm not even sure every currency is in there. I'd treat it as a cross-check at best." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

### The FX rates are NOT in the warehouse — you must pull them from an API

The `RAW_CURRENCY_RATES` table is deliberately partial and unsafe to rely on. **You are required to source authoritative historical daily FX rates from a free, keyless exchange-rate API** and build your own conversion layer:

- **Frankfurter** — `https://www.frankfurter.app` (ECB reference rates; e.g. `https://api.frankfurter.app/2024-03-15?from=USD&to=GBP,EUR,JPY,CAD,AUD,INR,BRL`)
- or **exchangerate.host** — `https://exchangerate.host`

Both serve historical daily rates with **no API key**. The API workflow is itself part of the engagement: you must decide **which day's rate applies to each sale**, how to **backfill** the full year, what to do when a sale falls on a **weekend or holiday with no published rate**, and how to make the pull **incremental and idempotent** so a daily pipeline doesn't re-fetch the whole history every run. See `data_generator/README.md` → "FX rate workflow" for the mechanics. Treat `RAW_CURRENCY_RATES` as, at most, a partial cross-check against what the API returns.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What is the reporting currency, and is it the only one?** USD is the board currency — but do you keep local amounts alongside it, and at what grain do you store both?
2. **Which day's FX rate converts a sale?** The transaction (`SOLD_AT`) date? The booking (`BOOKED_AT`) date? Month-end? A fixed budget rate? **This single choice moves the consolidated total by a few percent — it is the headline of the engagement.**
3. **What do you do on weekends and holidays when there is no published rate?** Carry forward the last available rate? Carry back? Interpolate? The naive join drops those sales or nulls their USD value.
4. **How do you backfill the gaps** in coverage (the warehouse table stops mid-year; the API may miss a day)? And how do you make the pull incremental without losing idempotency?
5. **Which sales even count as revenue?** Voided sales (cancelled at the till)? Returns (revenue reversed)? Sales with a missing `SOLD_AT`? Duplicate re-rung transactions?
6. **Whose "day" is it?** Sales timestamps are local wall-clock with no stored offset. A sale at 11pm in Tokyo and one at 11pm in São Paulo are ~12 hours apart in UTC and can land on different rate-dates and different reporting months. Do you convert in store-local time or normalise to UTC first?
7. **How do you reconcile mixed reporting calendars** (gregorian vs 4-4-5) when rolling up to a single group month?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when the CFO, Ops, and the Controller push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Global sales mart** — a clean, documented, finance-trustworthy fact table at a defensible grain, carrying **both local and USD amounts**, with the FX rate, rate-date, and rate-policy that produced each USD value stamped on the row.
2. **Inventory mart** — store × category × snapshot stock valued in **both local and USD**, on a consistent FX policy with the sales mart.
3. **Executive reporting layer** — consolidated group revenue by month, country, channel, and category in USD, that the CFO can pull a single signable number from.
4. **FX-handling design** — a written design for the rate layer: which API, which day's rate, weekend/holiday backfill rule, incremental + idempotent pull strategy, and how the partial `RAW_CURRENCY_RATES` table is used (or rejected) as a cross-check.
5. **An FX-policy reconciliation** — a model or report that **explains the few-percent spread**: show consolidated USD revenue under transaction-date vs month-end vs fixed budget-rate, and let the CFO walk from one to the others. The board number must be defensible against "but the other policy says X."
6. **Data quality framework** — your tests + what severity each is + what happens when one fails in production.
7. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, the **FX-rate pull task and its dependency on downstream conversion**, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
8. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure. **The FX-rate pull in particular must be incremental and idempotent** — re-running it must not duplicate rate rows or change historical conversions.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse. The FX rates you pull must be materialised into the warehouse (a seed or a loaded table), not fetched live at query time, so the marts are reproducible.
- **The numbers must tie out.** Your consolidated USD revenue must be reconstructable from local sales × the documented rate for each row. If a reviewer cannot re-derive a country's USD total from your rate table and your policy, you have not finished.
- **Document the spread, don't hide it.** A model that reports one consolidated number without disclosing how much it would move under a different FX policy has failed the engagement. The CFO needs to understand *why* the three analysts disagreed and which policy you chose.

---

## 6. Definition of done

You are done when you can sit across from the Group CFO, the VP of International Operations, and the Financial Controller — who disagree — and:

1. Show them one executive layer they can all pull group revenue from, in USD, by country and month.
2. Show them the same revenue under all three FX policies and walk the spread line by line: "transaction-date gives $A, month-end gives $B, fixed budget-rate gives $C; here is why, and here is the one I recommend you sign."
3. Tell them which data quality issues you found (duplicates, null sold-times, the untrustworthy rate table, timezone ambiguity), which you fixed, and which they need to fix at the source.
4. Defend every definitional choice — reporting currency, rate-date policy, weekend backfill, timezone handling — with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
