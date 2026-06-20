# Assessment Rubric — Engagement 06

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of MRR* — specifically paused handling, `past_due` treatment, and mid-cycle proration? Did you produce the reconciliation bridge that explains the 8–12% spread rather than hiding it? Is the paused-subscriber population surfaced as the headline driver, with a recommended treatment? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), one defensible subscription grain, idempotent, `ref()`/`source()` throughout, no business logic in staging. Plans joined as reference, not hard-coded prices. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (active-subscriber, paused treatment, proration roll-up, `past_due`, annual normalisation, duplicate handling, currency) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Recognised recurring revenue reconciles to the deduped succeeded `renewal` + `proration` ledger. MRR snapshot and cash-recognised numbers are each internally consistent and labelled. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical VP can follow. |

## Scoring bands
- **Distinction (85–100):** Reconciliation bridge is correct and defended; paused population isolated as the headline driver with a recommended treatment; proration handled at the prorated remainder (not full plan jump); `past_due` decision explicit; MRR definition written and labelled (snapshot vs cash); duplicates deduped; annual normalised to monthly; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room and a diligence call.
- **Strong pass (70–84):** Correct MRR under a stated definition, paused and proration handled deliberately, duplicates removed, ≥10 tests, assumptions documented, spread mostly explained.
- **Pass (55–69):** Reasonable subscription mart, basic tests, some assumptions, MRR roughly right but the spread not fully bridged or paused treatment unstated.
- **Below bar (<55):** Sums raw payments or raw plan prices with no status logic; treats paused inconsistently without saying so; counts the full plan price on every mid-cycle upgrade; spread unexplained; no business-rule tests; mixes currencies or annual/monthly.

## Non-negotiables (auto-deductions)
- Hard-coded plan prices instead of joining `RAW_PLANS`.
- Silently dropping rows (nulls, dupes, paused) with no test or note.
- An MRR number with no written definition and no reconciliation to the charge ledger.
- Treating annual plans as their full upfront charge in a monthly MRR.
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Finance, Growth, and RevOps all in the room:
1. "Walk me from Growth's number to RevOps' number." (the bridge)
2. "Why is *this* your treatment of paused subscriptions?"
3. "When someone upgrades on day 18, what happens to MRR — and why?"
4. "Which problems are in our data vs. which must we fix at the source?"
5. "If this pipeline fails at 2am, what happens?"
