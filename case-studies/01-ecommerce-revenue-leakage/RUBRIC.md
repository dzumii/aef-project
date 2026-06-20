# Assessment Rubric — Engagement 01

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of revenue*? Did you produce the reconciliation bridge that explains the 8–12% gap rather than hiding it? Is the un-refunded cancellation leakage surfaced as an actionable finding? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain, idempotent, `ref()`/`source()` throughout, no business logic in staging. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (completed order, revenue recognition, refund treatment, currency, duplicate handling) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Net revenue reconciles to the raw ledger minus refunds minus duplicates. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical VP can follow. |

## Scoring bands
- **Distinction (85–100):** Reconciliation bridge is correct and defended; cancellation leakage isolated; all major flaws handled; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room.
- **Strong pass (70–84):** Correct net revenue, refunds and duplicates handled, ≥10 tests, assumptions documented, gap mostly explained.
- **Pass (55–69):** Reasonable marts, basic tests, some assumptions, net revenue roughly right but gap not fully bridged.
- **Below bar (<55):** Counts raw payments, treats refunds as full, gap unexplained, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (nulls, dupes) with no test or note.
- A net-revenue number with no reconciliation to the gross ledger.
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Finance and Ops both in the room:
1. "Walk me from Ops' number to my number." (the bridge)
2. "Why is *this* your definition of recognized revenue?"
3. "Which problems are in your data vs. which must we fix at the source?"
4. "If this pipeline fails at 2am, what happens?"
