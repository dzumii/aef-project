# Assessment Rubric — Engagement 03

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of churn*? Did you produce the reconciliation that explains the ~10-point spread between the three churn rates rather than collapsing them into one number? Is involuntary-vs-voluntary churn surfaced as an actionable finding, and are reactivations handled explicitly? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), one defensible grain (per subscriber line), the three churn flags carried *side by side* in a single mart, idempotent, `ref()`/`source()` throughout, no business logic in staging. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (churn definition per team, observation date/window, reactivation treatment, involuntary vs voluntary, duplicate-subscriber handling) is explicit and defended. |
| **Correctness / does it tie out** | 10% | All three churn flags evaluated as-of the same observation date on the same deduplicated base. The rates reproduce the reference numbers; the spread decomposes cleanly. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, the churn-definitions doc, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical CRO can follow. |

## Scoring bands
- **Distinction (85–100):** Three churn flags side by side, all as-of one observation date; reconciliation bridge between the rates is correct and defended; reactivations and involuntary churn isolated as findings; duplicate subscribers + replayed usage deduped; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room.
- **Strong pass (70–84):** Three correct churn rates close to reference, reactivations and involuntary churn handled, ≥10 tests, assumptions documented, spread mostly explained.
- **Pass (55–69):** Reasonable mart with the three flags, basic tests, some assumptions, rates roughly right but spread not fully decomposed.
- **Below bar (<55):** A single blended churn number; reactivations ignored; duplicates double-counted; involuntary/voluntary conflated; spread unexplained; no business-rule tests; definitions evaluated as-of inconsistent dates.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (duplicate subscribers, null timestamps) with no test or note.
- Reporting one churn number with no side-by-side definitions and no reconciliation.
- Fewer than 10 tests, or zero business-rule tests.
- Evaluating the three definitions as-of different dates (rates not comparable).

## The defense (live or recorded)
Be ready to answer, with Marketing, Billing, and Network all in the room:
1. "We each have a churn number. Walk me from Marketing's to Network's." (the bridge)
2. "Why is *this* your definition of churn for each team — and why this observation date?"
3. "A line we cancelled is using the network again. Is that customer churned or not? Defend it."
4. "How much of our 'churn' is us disconnecting people for non-payment vs. people leaving us?"
5. "If this pipeline fails at 2am, what happens?"
