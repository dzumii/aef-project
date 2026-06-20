# Assessment Rubric — Engagement 08

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of attrition and tenure*, driven by internal transfers and rehires? Did you produce the reconciliation bridge that explains the 22–33% attrition spread and the ~1-year tenure spread rather than hiding it? Is "transfers miscounted as exits" surfaced as the headline actionable finding? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible **person-grain** for the workforce mart, employment-record stitching done in an intermediate layer, idempotent, `ref()`/`source()` throughout, no business logic in staging. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (employee grain, internal-movement model, tenure-across-rehire rule, attrition window, status-conflict resolution, currency, duplicate handling) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Person-grain headcount reconciles to distinct active people; department headcount sums to company total; transfers net to zero across departments. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical CPO can follow. |

## Scoring bands
- **Distinction (85–100):** Reconciliation bridge is correct and defended; transfers-as-exits isolated as the headline finding; rehire tenure reset quantified; continuous-tenure rule chosen and defended with alternates surfaced; all major flaws handled; business-rule tests; clean idempotent person-grain architecture; orchestration covers freshness + alerting; deck would survive a real client room.
- **Strong pass (70–84):** Correct person-grain headcount, transfers and rehires handled, ≥10 tests, assumptions documented, spread mostly explained.
- **Pass (55–69):** Reasonable marts, basic tests, some assumptions, headcount roughly right but spread not fully bridged.
- **Below bar (<55):** Counts raw employment records as people, treats every transfer/term record as an exit, resets tenure on rehire silently, spread unexplained, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (dupes, null dates, status conflicts) with no test or note.
- An attrition or tenure number with no reconciliation to the raw record-based view.
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Talent and Finance both in the room:
1. "Walk me from Finance's record-based attrition to Talent's person-based attrition." (the bridge)
2. "Why is *this* your definition of tenure across a rehire gap?"
3. "How does a department transfer show up in your department report — and why isn't it an exit?"
4. "Which problems are in our data vs. which must we fix at the source?"
5. "If this pipeline fails at 2am, what happens?"
