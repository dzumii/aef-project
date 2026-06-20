# Assessment Rubric — Engagement 10

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting FX rate-date policies* producing a few-percent spread on the identical sales? Did you produce the FX-policy reconciliation that shows consolidated USD revenue under transaction-date vs month-end vs fixed budget-rate, and recommend one — rather than silently picking a rate and hiding the spread? Is the untrustworthy in-warehouse rate table called out as a finding? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain, idempotent, `ref()`/`source()` throughout, no business logic in staging. **A dedicated FX-rate dimension** (one row per currency × date) materialised from the API, joined to sales on a documented rate-date. Local and USD amounts both carried; the rate and rate-date stamped on each fact row. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. At least one test on FX coverage (every sale's currency × rate-date resolves to a rate; no null USD amounts). |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (reporting currency, rate-date policy, weekend/holiday backfill rule, timezone normalisation, duplicate handling, void/return treatment, calendar reconciliation) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Consolidated USD revenue is reconstructable from local amounts × the documented rate per row. A country's USD total can be re-derived from the rate table and the stated policy. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. **The FX-rate API pull is modelled as an incremental, idempotent task** that downstream conversion depends on. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical CFO can follow, including the policy-spread bridge. |

## Scoring bands
- **Distinction (85–100):** FX-rate dimension built from the API with a documented weekend/holiday backfill rule; transaction-date / month-end / fixed-rate spread quantified and reconciled; a clear recommended policy defended in CFO terms; timezone ambiguity handled explicitly; duplicates and null-sold-time handled with tests, not silent drops; clean idempotent architecture with an incremental rate pull; orchestration covers freshness + alerting; deck would survive a real board-room defense.
- **Strong pass (70–84):** Correct consolidated USD revenue on a single defensible policy, FX rates sourced from the API and backfilled, ≥10 tests, assumptions documented, the policy spread shown even if not fully bridged.
- **Pass (55–69):** Reasonable marts, rates joined (even if only the warehouse table or a single policy), basic tests, some assumptions, USD revenue roughly right but the spread not explained.
- **Below bar (<55):** Sums mixed currencies as if all USD, OR relies solely on the partial `RAW_CURRENCY_RATES` table (missing currencies/half the year), OR picks one rate policy with no disclosure of the spread, OR drops weekend/null-rate sales silently, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Summing `LOCAL_AMOUNT` across currencies without conversion.
- Relying only on `RAW_CURRENCY_RATES` (it is partial and internally inconsistent by design) instead of the API.
- Reporting one consolidated number with no disclosure of how much it moves under a different FX policy.
- Silently dropping rows (null `SOLD_AT`, weekend sales with no rate, duplicates) with no test or note.
- Hard-coded fixes in the warehouse instead of dbt logic.
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with the CFO, Ops, and the Controller all in the room:
1. "Show me group revenue under each FX policy and tell me which one to sign — and why." (the bridge)
2. "Why is *this* the day's rate you used, and what did you do on weekends?"
3. "A sale rang up at 11pm in Tokyo — which day and which month is it in your numbers, and why?"
4. "Which problems are in our data vs. which must we fix at the source?"
5. "If the FX API is down when this pipeline runs at 2am, what happens?"
