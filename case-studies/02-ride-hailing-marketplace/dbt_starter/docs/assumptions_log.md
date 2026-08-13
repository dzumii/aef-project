# Cobalt Mobility — Definitional Assumptions Log

**Engagement:** Ride-Hailing Marketplace Analytics  
**Prepared by:** Analytics Engineering Consultant  
**Status:** Draft for stakeholder review  
**Last updated:** 2026-08-13

---

## Purpose

This document records every definitional choice made in building the Cobalt Mobility analytics models. Each assumption directly affects reported GMV, net revenue, take rate, or active-user counts. Stakeholders who disagree with a position should raise it before the model is promoted to production — the model is designed so that changing a rule changes the output without restructuring the pipeline.

---

## Assumption 1: Driver Deduplication (Re-Onboarding)

**Issue:** 160 driver_ids appear twice in RAW_DRIVERS. The onboarding service reuses the same DRIVER_ID when a churned driver returns, creating a second row with a later ONBOARDED_AT timestamp.

**Decision:** Take the **most recent row per DRIVER_ID** as the canonical driver record.

**Rules:**
- Deduplicate using `ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY onboarded_at DESC) = 1`
- The latest row's `driver_status`, `vehicle_class`, `rating`, and `home_city` are treated as current state
- The **earliest** `onboarded_at` across all rows is preserved as `first_onboarded_at` (tenure calculation)
- The **latest** `onboarded_at` is preserved as `last_onboarded_at` (identifies re-onboarding)
- A boolean flag `is_reonboarded` is set when row_count > 1

**Rationale:** The driver's trip history, incentives, and payouts all key on DRIVER_ID regardless of which row exists. We need one record per driver for the mart, but preserve the re-onboarding fact for Driver Ops.

**Impact:** Driver count drops from 4,160 rows to 4,000 distinct drivers (–3.8%).

---

## Assumption 2: Payment Deduplication (Retries & Webhook Double-Logging)

**Issue:** 6,732 trips have more than one payment row (5,287 with 2, 1,422 with 3, 23 with 4). The payment processor retries failed captures and the webhook occasionally double-logs successful ones.

**Decision:** For revenue recognition, count only **one captured payment per trip** — the first successful capture (earliest `captured_at`).

**Rules:**
- Filter to `payment_status = 'captured'` only — failed attempts are informational, not revenue
- Within captured rows for a single trip, deduplicate: `ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY captured_at ASC) = 1`
- The deduplicated captured amount is **net collected revenue** for that trip
- Processor fees are taken from the same winning row
- A flag `has_duplicate_captures` marks trips where more than one captured row existed (for audit)
- Failed attempts are preserved in a separate staging model for retry-rate analytics

**Rationale:** A trip can only generate revenue once. Multiple captured rows for the same trip at the same amount are webhook artifacts, not separate economic events. Taking the earliest capture aligns with "first successful settlement" and matches what the processor actually transferred.

**Impact:** Deduplication removes ~1,200 over-counted captured rows. Without this, naive revenue sums overstate by ~1.5%.

---

## Assumption 3: Fraud Revenue Treatment

**Issue:** 2,196 completed trips are flagged `IS_FRAUD_FLAGGED = TRUE` after the fact. These trips have a gross fare ($31,458 total), and 962 incentive lines ($2,835) were paid against them.

**Decision:** Fraud-flagged trips are **excluded from net revenue** but **included in GMV** with a clear label.

**Rules:**
- **GMV (Growth's number):** Includes all completed trips regardless of fraud flag. Rationale: the fare was quoted, the trip was matched and completed on the platform. This is the marketplace volume metric.
- **Net revenue (Finance's number):** Excludes fraud-flagged trips entirely. Rationale: these fares are reversed/refunded — they represent money never collected or clawed back.
- **The bridge:** Fraud appears as an explicit line item in the GMV-to-net reconciliation: "Less: fraud reversals = –$31,458"
- **Driver earnings:** The driver performed the trip and was paid. Driver gross earnings **include** fraud trips (the driver is not penalized). The fraud loss is borne by the platform, not the driver.
- **Incentives on fraud trips:** $2,835 in bonuses were paid and cannot be clawed back. These remain in driver incentive totals (Driver Ops requirement: paid is paid). They appear as a separate line in the reconciliation: "Incentive leakage on fraud trips."

**Rationale:** This is the only position that satisfies all three stakeholders simultaneously: Growth keeps their GMV, Finance gets clean net revenue, and Driver Ops doesn't restate what drivers were paid.

**Impact:** Fraud accounts for 3.2% of GMV ($31,458 / $983,458 total completed fare).

---

## Assumption 4: Currency Treatment

**Issue:** Rivermouth operates in GBP; the other three cities (bayview, metro_north, sunbelt) operate in USD. GMV and revenue cannot be summed across cities without a conversion.

**Decision:** Report in **original currency at the trip/payment level**; aggregate KPIs reported in **USD** using a fixed monthly average rate.

**Rules:**
- All staging and intermediate models preserve the original `currency` column
- A currency dimension table (`dim_currency_rates`) stores monthly GBP→USD rates (source: Bank of England monthly average, or a fixed 1.27 rate if historical data is unavailable for this exercise)
- Mart-level KPI aggregations multiply GBP amounts by the applicable month's rate
- All KPI layer outputs carry both `amount_local` (original) and `amount_usd` (converted) columns
- City-level reporting can use local currency; company-level reporting uses USD

**Rationale:** The COO's investor deck needs a single number. USD is the reporting currency (3 of 4 cities, Series C investors are USD-denominated). Keeping local currency at the grain preserves auditability.

**Impact:** At ~1.27 GBP/USD, rivermouth's $245,692 GBP ≈ $312,028 USD. Total GMV swings by ~$66K depending on whether you convert or not.

---

## Assumption 5: Incentive Attribution (Multi-Campaign Overlap)

**Issue:** 6,473 trips have incentive lines from 2 different campaigns (e.g., a trip earns both a `peak_hour_boost` and a `consecutive_trips` bonus). Total incentive spend is $86,609 across 29,238 lines.

**Decision:** **All incentive lines are real costs — do not deduplicate across campaigns.** A trip can legitimately qualify for multiple campaigns, and each bonus was paid to the driver.

**Rules:**
- Total incentive spend per driver = SUM of all incentive lines for that driver (regardless of how many campaigns per trip)
- Total incentive spend per trip = SUM of all incentive lines for that trip (may exceed one line)
- No deduplication of incentive_ids (they are already unique)
- The **over-attribution risk** is not double-counting — it's overlapping campaign design. This is surfaced as a metric: `pct_trips_multi_campaign` in the KPI layer for the Growth/Finance teams to review campaign rules
- Per Driver Ops requirement: the driver's total paid incentives in the mart MUST equal SUM(bonus_amount) from RAW_DRIVER_INCENTIVES for that driver — no silent restatement

**Rationale:** The Data Lead said "a single trip can show up on more than one campaign line." This is not a bug — it's campaign overlap. Both bonuses were paid. Deduplicating would understate actual cash paid to drivers and break the Driver Ops reconciliation.

**Impact:** 28% of incentivized trips earn bonuses from 2 campaigns. Average incentive per trip: $2.96 (single) vs. ~$5.92 (double). This is a cost-control issue to flag, not a data quality issue to "fix."

---

## Assumption 6: Cancellation Classification

**Issue:** 13,181 cancelled trips exist with four reasons. Some carry a fee (~$3), some don't. The question: which belong in GMV, and which generate revenue?

**Decision:** Classify cancellations into three tiers:

| Cancel Reason | Fare | GMV Treatment | Revenue Treatment |
|---|---|---|---|
| `no_driver_found` | $0.00 (3,312 trips) | **Excluded from GMV** | No revenue |
| `rider_cancel` | ~$3.17 (5,571 trips / $17,644) | **Excluded from GMV, reported as cancellation fee revenue** | Fee revenue (recognized) |
| `driver_cancel` | ~$3.21 (2,618 trips / $8,399) | **Excluded from GMV, reported as cancellation fee revenue** | Fee revenue (recognized) |
| `rider_no_show` | ~$3.17 (1,680 trips / $5,324) | **Excluded from GMV, reported as cancellation fee revenue** | Fee revenue (recognized) |

**Rules:**
- **GMV** = SUM(gross_fare) WHERE trip_status = 'completed' (regardless of fraud flag). GMV measures marketplace volume of completed rides only.
- **Cancellation fee revenue** is a separate revenue line: $31,367 total. It is real collected revenue (riders were charged) but is NOT marketplace volume.
- **no_driver_found** trips are platform failures with $0 fare — excluded from everything except cancellation-rate metrics.
- The reconciliation bridge shows: "GMV (completed trips) + Cancellation fee revenue = Gross revenue before adjustments"

**Rationale:** Growth's argument that "those trips still happened on our platform" is valid for rider_cancel/driver_cancel/no_show (a fare was charged), but the fare is a penalty fee, not a completed ride. Including $3 cancellation fees in a "GMV" metric alongside $14 average completed fares distorts the marketplace-size signal. Finance can recognize the fee revenue separately.

**Impact:** This definition puts GMV at ~$952K (completed, including fraud) rather than ~$983K (all non-zero fares). The $31K cancellation fee revenue appears as its own line in the P&L bridge.

---

## Assumption 7: Revenue Recognition Point

**Issue:** A trip has multiple timestamps: `requested_at`, `accepted_at`, `started_at`, `ended_at`. A payment has `attempted_at` and `captured_at`. When is revenue "earned"?

**Decision:** Revenue is recognized at **payment capture** (`captured_at` on the deduplicated payment row), not at trip end.

**Rules:**
- The economic event is the successful charge, not the ride completion
- For daily/monthly aggregation, use `captured_at` date
- For trips with no captured payment (cancelled with $0 fare, or all payment attempts failed), revenue = $0 for that trip regardless of gross_fare
- The timing gap between `ended_at` and `captured_at` is typically seconds/minutes (same-day), so period boundaries rarely shift — but edge cases at month-end are handled correctly by this rule
- Incentives are recognized at `paid_at` (the date the bonus hit the driver's account), not `earned_at`

**Rationale:** Revenue = cash collected. A fare that was quoted but never captured is not revenue (this catches the edge case of completed trips where all payment attempts failed — these would be a data quality issue to escalate, not revenue to book). Using capture date also aligns with Finance's ledger and processor settlement reports.

**Impact:** 1,956 trips (2.9% of completed) have `trip_status = 'completed'` but no captured payment ($28,065 in uncollected fare). These are $0 net revenue despite having a gross_fare — they appear in the reconciliation as "Less: uncollected fares." This is a significant source-system issue to escalate.

---

## Reconciliation Bridge (Preview)

```
Growth GMV (all completed trip fares, incl. fraud)       $952,091
+ Cancellation fee revenue (billed cancellations)        + $31,367
= Gross platform revenue (before adjustments)            $983,458

Less: Fraud reversals (completed, fraud-flagged)         – $31,458
Less: Uncollected fares (1,956 trips, no capture)        – $28,065
= Collectable revenue                                    $923,935

Less: Processor fees (on captured payments)              – $37,887
                                                         ─────────
= Net collected revenue (after fees)                     $886,048

─── Verification against payment ledger ───
Total deduped captured payments                          $954,377
  of which: non-fraud completed trips                    $893,635
  of which: fraud trips (captured before flag)           $ 30,391
  of which: cancellation fees                            $ 30,351

─── The 8–12% gap explained ───
Growth GMV                                               $952,091
Finance net revenue (non-fraud captured – fees)          $855,749
Gap                                                      $ 96,342 (10.1%)

Breakdown of the gap:
  Fraud (captured then reversed)                         $ 30,391 (31%)
  Uncollected fares (no successful capture)              $ 28,065 (29%)
  Processor fees                                         $ 37,887 (39%)
                                                         ────────
  Total explained                                        $ 96,343

Memo: Incentive spend (total paid to drivers)              $86,609
  of which: on fraud trips (leakage)                       ($2,835)
  of which: multi-campaign overlap (6,473 trips)           (~$19K)
```

---

## Open Items for Stakeholder Review

1. **GBP/USD rate source** — Using fixed 1.27 for this sprint. Confirm if Finance has an official monthly rate table.
2. **Uncollected fares (CRITICAL)** — 1,956 completed trips (2.9%) have no successful payment capture. $28K in lost revenue. Escalate to payments engineering — likely a processor/webhook integration gap.
3. **Fraud incentive clawback policy** — Driver Ops says paid is paid. Should Finance accrue a clawback reserve? (Accounting decision, not a data model decision.)
4. **Campaign overlap** — Is double-qualifying intentional or a rules-engine bug? Flag for Growth/Driver Ops.

---

## Active Rider Definitions (Multi-Definition Model)

The rider mart will carry all four flags simultaneously:

| Definition | Logic | Stakeholder |
|---|---|---|
| `is_active_account` | `account_status = 'active'` in RAW_RIDERS | CRM / none (vanity metric) |
| `is_active_30d` | Completed a non-fraud trip in trailing 30 days | Growth |
| `is_active_90d` | Completed a non-fraud trip in trailing 90 days | Finance (investor deck) |
| `is_active_any_trip_30d` | Requested any trip (incl. cancelled) in trailing 30 days | Ops (engagement) |

Expected variance: 10–15% between the tightest (30d completed, non-fraud) and loosest (account_status = active) definitions.
