# Assessment Rubric — Engagement 07

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *what to do with deliveries the data can't measure*? Did you produce the reconciliation that explains the 88% vs 79% spread rather than hiding it? Did you separate the *policy choice* (null-timestamp handling) from the *data defect* (the carrier feed dropping scans) and surface the unmeasurable-delivery rate as an actionable finding? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain (one delivery per order), idempotent, `ref()`/`source()` throughout, no business logic in staging. Duplicate scans de-duplicated before the fact grain. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. The null-timestamp rate and dup-scan rate are monitored, not silently cleaned. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (on-time definition, timezone, null-timestamp handling, incomplete-delivery treatment, dedupe rule, driver attribution across rehires) is explicit and defended. |
| **Correctness / does it tie out** | 10% | The on-time / late / unmeasurable / incomplete counts sum to the order denominator. The reproducible on-time rate matches the stance taken. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical VP can follow. |

## Scoring bands
- **Distinction (85–100):** On-time reconciliation is correct and defended; the null-timestamp swing is quantified across exclude/impute/fail; the unmeasurable-delivery rate is isolated as a data-quality finding to fix at source; all major flaws handled; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room.
- **Strong pass (70–84):** Correct on-time rate for a stated stance, deduped deliveries, incomplete deliveries classified, ≥10 tests, assumptions documented, spread mostly explained.
- **Pass (55–69):** Reasonable mart, basic tests, some assumptions, an on-time number roughly right but the spread not fully explained.
- **Below bar (<55):** Counts raw delivery rows (double-counts dupes), silently drops null-timestamp rows to land at "88%", incomplete deliveries unhandled, spread unexplained, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (null timestamps, dupes) with no test or note.
- An on-time number with no disclosure of its sensitivity to the null-timestamp choice.
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Operations and CX both in the room:
1. "Walk me from the 88% number to the 79% number." (the bridge)
2. "Why is *this* your definition of on-time, and why this stance on missing timestamps?"
3. "Which problems are in your data vs. which must we fix at the carrier feed?"
4. "If this pipeline fails at 2am, what happens?"
