# Northwind Atlas — Definitional Assumptions Log

**Engagement:** HR Workforce Analytics  
**Prepared by:** Analytics Engineering Consultant  
**Status:** Draft for stakeholder review  
**Last updated:** 2026-08-13

---

## Purpose

This document records every definitional choice made in building the Northwind Atlas workforce analytics models. Each assumption directly affects reported headcount, attrition rate, tenure, or cost metrics. Stakeholders who disagree with a position should raise it before the model is promoted to production — the model is designed so that changing a rule changes the output without restructuring the pipeline.

The core problem: Talent and Finance report attrition between 22% and 33% depending on how internal transfers and rehires are counted, and average tenure differs by ~1 year depending on how tenure is measured across rehire gaps. This log documents the rules that resolve those discrepancies.

---

## Assumption 1: Grain of the Workforce Mart (Person, Not Employment Record)

**Issue:** RAW_EMPLOYEES contains 13,807 rows but only 12,000 distinct persons (PERSON_ID). The HRIS creates a new EMPLOYEE_ID whenever someone transfers departments or is rehired. Finance counts at the record level (headcount = active records); Talent counts at the person level (headcount = active humans).

**Decision:** The workforce mart is built at **person grain (PERSON_ID)**. One row per human, regardless of how many employment records they have.

**Rules:**
- PERSON_ID is the primary key of the mart
- A person's full employment history is stitched from all EMPLOYEE_ID records sharing that PERSON_ID
- Active headcount = COUNT(DISTINCT person_id) WHERE the person has at least one active employment record
- Department-level headcount uses the person's **current** (most recent active) employment record for attribution
- The record-level view remains available as a staging model for Finance's cost-center reconciliation

**Rationale:** The board question is "how many people work here and how many left." A person who transfers from Sales to Customer Success did not leave the company. Counting them as an exit inflates attrition by ~36% (1,230 transfers / 3,297 true terminations). Person-grain is the only defensible answer for company-level workforce health.

**Impact:** Active headcount = 9,254 persons (not 9,280 records — difference is 26 duplicate active records, see Assumption 6).

---

## Assumption 2: Internal Transfers Are Not Exits

**Issue:** When a person transfers departments, the HRIS closes the old EMPLOYEE_ID record (status = `transferred`, termination_date populated) and opens a new one (with PRIOR_EMPLOYEE_ID pointing back). Finance counts the closed record as a termination. Talent does not.

**Decision:** A record with `employment_status = 'transferred'` is **not an exit**. It is a continuous employment event — a department change within the company.

**Rules:**
- Records with `employment_status = 'transferred'` are excluded from attrition numerator
- The transfer is modeled as a movement event: source department loses headcount, destination gains it, net company headcount is unchanged
- The person's tenure is continuous across the transfer — no reset
- Transfer records are linked to their successor via the `prior_employee_id` chain
- 1,231 predecessor records are `transferred`; 1,229 are successfully linked to a successor (1 unlinked transfer is flagged for investigation)
- Department-level reporting shows "transfers in" and "transfers out" as separate line items from "hires" and "exits"

**Rationale:** The VP of Talent is correct: these people never left the building. A transfer from Sales (CC-1030) to Customer Success (CC-1050) changes where the cost sits, but the human is still employed. Counting it as attrition is an artifact of the HRIS record model, not a workforce event.

**Impact:** Removing 1,230 transfers from the exit count drops the record-based attrition rate from ~33% (Finance) to ~24% (closer to Talent's number). The remaining gap is rehires and measurement period differences.

---

## Assumption 3: Rehires — Tenure Definitions (Multi-Definition Model)

**Issue:** 544 persons left the company (status = `terminated`) and later returned (a new record exists with `prior_employee_id` pointing to the terminated record). Their original departure is a real exit, but their tenure calculation depends on whether you bridge the gap.

**Decision:** The mart carries **three tenure definitions simultaneously** — each is valid for different purposes.

| Definition | Logic | Use Case |
|---|---|---|
| `tenure_current_stint` | DATEDIFF from current record's hire_date to today (or termination_date) | Finance / benefits eligibility |
| `tenure_total_service` | Sum of all active days across all stints, excluding gaps | Talent / loyalty recognition |
| `tenure_continuous` | DATEDIFF from first-ever hire_date to today (or final termination_date) | Seniority / vesting (if policy allows) |

**Rules:**
- A "stint" is a contiguous period of employment (may span multiple EMPLOYEE_IDs if linked by transfers)
- A "gap" is the period between a termination_date and the next hire_date for the same PERSON_ID
- `tenure_current_stint` resets on rehire — starts from the rehire record's hire_date
- `tenure_total_service` sums (termination_date - hire_date) for each completed stint + (today - hire_date) for the active stint, excluding gap days
- `tenure_continuous` = today (or final term date) minus the earliest hire_date across all records — includes gap time
- The default tenure metric in KPI reporting is **tenure_total_service** (total time actually employed)
- All three are surfaced so stakeholders can choose

**Rationale:** Talent's complaint ("Finance treats a rehire as zero tenure") is valid for loyalty metrics. Finance's position ("they weren't here for 18 months, we can't count that as service") is valid for benefits accrual. Neither is universally right. Surfacing all three with clear labels lets each function use the appropriate one and eliminates the "which number is wrong" argument.

**Impact:** Average tenure spread between `tenure_current_stint` and `tenure_continuous` for the 544 rehires is the source of the ~1-year gap in reported average tenure. The mart makes this explicit rather than hiding it behind a single number.

---

## Assumption 4: Attrition Definition and Measurement Period

**Issue:** "Attrition rate" is reported as anywhere from 22% to 33%. The spread comes from: (a) counting transfers as exits, (b) whether rehires cancel out their prior departure, and (c) the denominator and time period used.

**Decision:** Attrition rate = **(True exits in trailing 12 months) / (Average active headcount over the same 12 months)**, annualized.

**Rules:**
- **Numerator (exits):** COUNT of persons whose final employment record terminated in the measurement period AND who were NOT subsequently rehired within the same period. A transfer is never an exit. A rehire's original departure still counts as an exit in the period it occurred (the person did leave).
- **Denominator:** Average of (beginning-of-period active person count + end-of-period active person count) / 2
- **Period:** Trailing 12 months, rolling monthly
- A person who left in month 3 and returned in month 9 counts as 1 exit in month 3 and 1 hire in month 9 — the exit is not retroactively cancelled
- Annualization: (exits / avg headcount) — already 12 months, no further annualization needed
- Internal transfers are excluded from both numerator and denominator movements

**Rationale:** This is the SHRM/ANSI standard definition. It avoids the two biggest distortions: transfers inflating exits (Finance's error) and rehires retroactively erasing exits (Talent's temptation). Both stakeholders can see their preferred variant as a secondary metric.

**Impact:** Expected attrition on this definition: ~24-25% (3,297 true terminations less any within-period rehires, divided by ~9,250 average headcount equivalent over the period). This sits between Talent's 22% and Finance's 33%.

---

## Assumption 5: Status vs. Date Conflicts — Resolution Rules

**Issue:** 30 employee records have `employment_status = 'terminated'` but `termination_date IS NULL`. Conversely, 1,230 records have `employment_status = 'transferred'` with a populated termination_date (expected — the transfer date). Which field is authoritative when they conflict?

**Decision:** `employment_status` is the **authoritative field** for determining the type of event. `termination_date` is used for timing only when present.

**Rules:**
- If `employment_status = 'terminated'` AND `termination_date IS NULL`:
  - Flag as a data quality issue (severity: medium)
  - Infer termination date as the **last payroll period** for that employee_id (latest PAY_PERIOD where payroll exists)
  - If no payroll exists, use hire_date + 1 day as a fallback (treat as immediate-exit placeholder) and flag for manual review
- If `employment_status = 'transferred'` AND `termination_date IS NOT NULL`:
  - This is normal — the termination_date represents the transfer-out date
  - Use it as the end date for that stint in the source department
- If `employment_status = 'active'` AND `termination_date IS NOT NULL`:
  - Not observed in current data (0 cases), but if encountered: trust status, ignore date, flag as DQ issue

**Rationale:** The Head of Finance says "a termination date is a termination." But 1,230 of those termination dates are actually transfer dates — the status field disambiguates. Status reflects the business event; the date is just the timestamp of that event. When the date is missing, we infer from the closest operational signal (payroll).

**Impact:** 30 records get an inferred termination date. These affect tenure calculations marginally (~0.3% of total records). Flagged for HRIS team to fix at source.

---

## Assumption 6: Duplicate Active Records — Deduplication

**Issue:** 26 persons have two active EMPLOYEE_ID records: same person, same department, same hire date, no PRIOR_EMPLOYEE_ID on the duplicate. These are HRIS double-inserts — system errors, not real employment events.

**Decision:** Keep the **lower EMPLOYEE_ID** (original record) and discard the higher (duplicate). Flag all 26 for HRIS correction.

**Rules:**
- Identify duplicates: same PERSON_ID, same DEPARTMENT_ID, same HIRE_DATE, both `employment_status = 'active'`, neither has a PRIOR_EMPLOYEE_ID pointing to the other
- Deduplicate using `ROW_NUMBER() OVER (PARTITION BY person_id, department_id, hire_date ORDER BY employee_id ASC) = 1`
- The discarded 26 records are logged in a data quality audit table
- Payroll rows referencing the discarded EMPLOYEE_ID are reassigned to the surviving EMPLOYEE_ID for cost reporting

**Rationale:** Two concurrent active records for the same person in the same department on the same hire date cannot represent reality. These inflate headcount by 26 (0.3%) and would double-count payroll cost if not resolved.

**Impact:** Active headcount drops from 9,280 records / 9,254 persons to exactly 9,254 persons. Removes $0 net cost impact (payroll is reassigned, not deleted).

---

## Assumption 7: Payroll Deduplication (Cancelled and Re-Issued Runs)

**Issue:** 6,038 employee-period pairs have 2 payroll records each. The Data Lead notes that "a few runs got cancelled and re-issued." These would double-count compensation cost if summed naively.

**Decision:** Keep the **latest payroll record per employee per pay_period** (most recent `paid_at` timestamp).

**Rules:**
- Deduplicate: `ROW_NUMBER() OVER (PARTITION BY employee_id, pay_period ORDER BY paid_at DESC) = 1`
- The retained row represents the final, corrected payment
- The discarded row is preserved in a `stg_payroll_cancelled` model for audit
- A flag `has_reissued_payroll` on the retained row marks corrections
- Total payroll cost after deduplication is the authoritative compensation figure

**Rationale:** A cancelled-and-reissued payroll run means the first payment was voided and replaced. Only the final payment was actually disbursed. Summing both would overstate compensation expense.

**Impact:** ~6,038 duplicate periods removed. Estimated overstatement without dedup: ~1% of total payroll (depends on whether amounts differ between original and reissue).

---

## Assumption 8: Performance Review Deduplication

**Issue:** 1,119 employee-period pairs have 2 review submissions; 13 have 3. Total excess: ~1,145 duplicate review rows. The Data Lead mentions "duplicate submissions" from a cycle-close job failure.

**Decision:** Keep **one review per employee per review period** — the row with the latest `review_date` (most recent submission). If `review_date` is NULL on all duplicates, keep the highest `review_id`.

**Rules:**
- Deduplicate: `ROW_NUMBER() OVER (PARTITION BY employee_id, review_period ORDER BY review_date DESC NULLS LAST, review_id DESC) = 1`
- 2,465 reviews have NULL `review_date` — these are not discarded, just deprioritized in the dedup ranking
- The surviving review's RATING and REVIEW_SCORE are used for performance analytics
- Discarded duplicates are logged for audit

**Rationale:** An employee cannot have two official performance reviews for the same annual cycle. The latest submission (by date) is the final/corrected one. This matches the pattern of cycle-close job retries creating duplicates.

**Impact:** ~1,145 excess review rows removed. Review coverage after dedup: ~35,286 unique employee-period reviews across 10 cycles.

---

## Assumption 9: Missing Review Dates

**Issue:** 2,465 reviews (6.8%) have `review_date IS NULL`. These are legitimate reviews (they have ratings and scores) whose timestamp was lost due to cycle-close job failures.

**Decision:** Missing review dates are **not imputed**. The review is retained with NULL date. Period-based analytics use `review_period` (year) as the time dimension, not `review_date`.

**Rules:**
- Reviews with NULL `review_date` are included in all review-period aggregations (they have a valid `review_period` year)
- They are excluded from any analysis requiring an exact date (e.g., "reviews completed within 30 days of cycle open")
- A data quality flag `is_missing_review_date` is set for reporting
- No date is fabricated — "unknown" is more honest than "invented"

**Rationale:** Imputing a date (e.g., mid-year or cycle-close date) would be a guess. The review_period gives us the year, which is sufficient for annual performance trending. Flagging rather than filling preserves data integrity.

**Impact:** 6.8% of reviews lack a precise date. Annual aggregations are unaffected (review_period is always populated).

---

## Assumption 10: Currency Normalization for Payroll

**Issue:** Payroll is in 4 currencies: USD (50%), EUR (17%), SGD (16%), GBP (16%). Company-level compensation metrics require a common currency.

**Decision:** Report in **original currency at the employee-period level**; aggregate KPIs reported in **USD** using a fixed monthly rate.

**Rules:**
- All staging models preserve the original `currency` and `gross_pay` columns
- A currency dimension provides monthly USD conversion rates:
  - GBP→USD: 1.27
  - EUR→USD: 1.09
  - SGD→USD: 0.74
  - (USD→USD: 1.00)
- Mart-level aggregations carry both `gross_pay_local` and `gross_pay_usd`
- Cost-per-head metrics use USD-converted amounts
- Fixed rates used for this sprint; confirm with Finance if they have an official rate table

**Rationale:** Cost-center headcount cost must be comparable across locations. USD is the natural reporting currency (majority of payroll). Preserving local amounts allows location-level analysis without conversion artifacts.

**Impact:** Total monthly payroll in USD will differ from naive SUM(gross_pay) by the currency mix effect. This is a normalization, not a restatement.

---

## Reconciliation Bridge (Preview)

```
─── ATTRITION RATE RECONCILIATION ───

Finance's record-based "exits" (trailing 12mo):
  Terminated records                                    3,297
  + Transferred records (counted as exits)            + 1,230
  = Finance total "exits"                               4,527
  / Active records (~9,280)                            = ~33%  ← Finance's number

Talent's person-based exits:
  Terminated persons                                    3,297
  Less: persons who were later rehired                  – 544
  = Talent "net exits"                                  2,753
  / Active persons (~9,254)                            = ~22%  ← Talent's number

Reconciled attrition (this model):
  True terminations (person left company)               3,297
  Less: transfers miscounted as exits                 – 1,230  (explains 13 pp)
  Less: rehires with prior departure in-period          – ~300  (estimate, period-dependent)
  = Exits for attrition calc                           ~2,767
  / Average headcount (~9,250)                         = ~24-25%

Bridge from Finance (33%) to Reconciled (24-25%):
  Finance starts at                                      33%
  Remove transfers (not real exits)                     – 9 pp
  Reconciled                                            ~24%

Bridge from Talent (22%) to Reconciled (24-25%):
  Talent starts at                                       22%
  Add back: rehires' original departure still counts   + 2-3 pp
  Reconciled                                            ~24-25%

─── TENURE RECONCILIATION ───

Finance avg tenure (current stint only, rehires reset):   Lower bound
Talent avg tenure (continuous from first hire):           Upper bound
Gap explained by:
  544 rehires × average gap duration                   = ~1 year spread
  Model reports both + total_service (middle ground)
```

---

## Open Items for Stakeholder Review

1. **Rehire gap threshold** — If a person returns after 5 years, should their prior service count toward `tenure_total_service`? Currently: yes, all gaps are bridged regardless of length. Confirm if there's a policy limit (e.g., service resets after 2+ years away).

2. **30 terminated-with-no-date records** — Inferred dates from last payroll. HRIS team should backfill these at source.

3. **26 duplicate active records** — Pure system errors. HRIS team should clean these and investigate the cause.

4. **Currency rates** — Using fixed rates this sprint. Need Finance's official rate table for production.

5. **Attrition: voluntary vs. involuntary** — Current data has no reason-for-termination field. All exits are treated equally. If the HRIS can provide a termination reason, the model can split voluntary/involuntary attrition.

6. **The 1 unlinked transfer** — 1,230 transferred records but only 1,229 have a confirmed successor. One transfer has no matching new record — investigate whether successor was never created or uses a different linkage.
