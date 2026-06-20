# Assessment Rubric — Engagement 09

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of "completed"* (and "active")? Did you produce the reconciliation that explains the ~45% vs ~30% gap rather than hiding it? Is the population that *finished the lessons but never passed the exam* surfaced as the actionable finding (the certification leak)? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain (enrolment-grain mart, with a person-level rollup where needed), idempotent, `ref()`/`source()` throughout, no business logic in staging. Completion definitions carried as side-by-side flags, not one baked-in winner. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (completed course, active learner, person-vs-enrolment unit, duplicate handling, ungraded-attempt treatment) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Each completion definition reproduces its reference rate; the bridge between them sums correctly; duplicate lesson events and ungraded attempts handled so counts are right. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical VP can follow. |

## Scoring bands
- **Distinction (85–100):** All completion definitions carried side-by-side and each reproduces its reference rate; the lessons→assessment bridge is correct and defended; the "finished lessons, never certified" cohort isolated as the actionable finding; person-vs-enrolment grain handled deliberately; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room.
- **Strong pass (70–84):** At least the lessons-based and assessment-based rates computed correctly, duplicates and ungraded attempts handled, ≥10 tests, assumptions documented, gap mostly explained.
- **Pass (55–69):** Reasonable marts, basic tests, some assumptions, completion rates roughly right but the gap not fully bridged, or only one definition surfaced.
- **Below bar (<55):** Counts raw lesson rows (double-counts duplicates), trusts `ENROLLMENT_STATUS` blindly, ignores ungraded attempts, conflates person and enrolment, gap unexplained, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (dupes, null timestamps, ungraded attempts) with no test or note.
- A single "completion rate" with no reconciliation between the competing definitions.
- Fewer than 10 tests, or zero business-rule tests.
- Treating `STUDENT_ID` as a primary key of `RAW_STUDENTS`.

## The defense (live or recorded)
Be ready to answer, with Curriculum and Credentialing both in the room:
1. "Walk me from the 45% lessons number to the 30% assessment number." (the bridge)
2. "Why is *this* your definition of a completed course / an active learner?"
3. "Is your rate per enrolment or per person, and why?"
4. "Which problems are in our data vs. which must we fix at the source?"
5. "If this pipeline fails at 2am, what happens?"
