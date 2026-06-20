# Assessment Rubric — Engagement 02

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of GMV, net revenue, and "active rider"*? Did you produce the reconciliation bridge that explains the 8–12% GMV-to-net gap rather than hiding it? Is the un-recovered fraud + incentive over-attribution surfaced as an actionable finding? Does the rider mart expose multiple activity definitions side by side? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain (one row per driver despite re-onboarding; one row per rider; one row per trip), idempotent, `ref()`/`source()` throughout, no business logic in staging. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (active rider, cancelled-trip classification, fraud treatment, revenue recognition, currency, duplicate captures, incentive de-dup) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Net revenue reconciles to the captured-cash ledger (deduped, minus fraud, minus non-revenue cancellations). Driver paid-incentive totals reconcile to the payouts ledger. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical COO can follow. |

## Scoring bands
- **Distinction (85–100):** Reconciliation bridge is correct and defended; fraud + un-recovered cancellation leakage isolated; incentive over-attribution de-duped *and surfaced* (not silently restated); rider mart carries multiple active-rider definitions; all major flaws handled; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real investor-prep room.
- **Strong pass (70–84):** Correct net revenue, fraud and duplicates handled, incentives de-duped, ≥10 tests, assumptions documented, gap mostly explained, rider activity defined explicitly.
- **Pass (55–69):** Reasonable marts, basic tests, some assumptions, net revenue roughly right but gap not fully bridged, a single active-rider definition stated.
- **Below bar (<55):** Sums raw fares or raw captures, treats every cancellation as revenue (or drops them silently), ignores fraud reversal, double-counts incentives, gap unexplained, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (nulls, dupes, re-onboarding rows) with no test or note.
- A net-revenue number with no reconciliation to the captured-cash ledger.
- Silently restating a driver's *paid* incentive total (Driver Ops constraint).
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Growth, Finance, and Driver Ops all in the room:
1. "Walk me from Growth's GMV to Finance's net revenue." (the bridge)
2. "Why is *this* your definition of an active rider — and show me the other counts."
3. "A trip got flagged fraud after we paid the driver a bonus on it. What did your model do?"
4. "Which problems are in our data vs. which must we fix at the source?"
5. "If this pipeline fails at 2am, what happens?"
