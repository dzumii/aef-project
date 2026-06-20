# Assessment Rubric — Engagement 05

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of a no-show* — and that the front-desk feed conflates reschedules and cancellations with genuine misses? Did you produce the reconciliation bridge that explains the ~22% → ~13% spread rather than reporting a single number? Is the reschedule-misflag surfaced as an actionable source-system finding? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain (one row per *logical* appointment, reschedule chains resolved), idempotent, `ref()`/`source()` throughout, no business logic in staging. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (no-show definition, denominator, reschedule-chain collapse, status canonicalization, billing-as-signal) is explicit and defended. |
| **Correctness / does it tie out** | 10% | Every slot lands in exactly one canonical status; reschedule chains collapse to one logical visit with no double-counting; the true no-show count is *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, and an exec summary + deck that a non-technical COO can follow. |

## Scoring bands
- **Distinction (85–100):** Reconciliation bridge is correct and defended; reschedule and cancel misflags isolated and quantified; reschedule chains collapsed to one logical visit; canonical status reconciles every row; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room.
- **Strong pass (70–84):** Correct true no-show rate (~12–14%), reschedules and cancels excluded from misses, ≥10 tests, assumptions documented, spread mostly explained.
- **Pass (55–69):** Reasonable marts, basic tests, some assumptions, no-show rate roughly right but spread not fully bridged.
- **Below bar (<55):** Counts every `no_show`/`missed` row as a miss (reproduces the inflated ~22%), ignores reschedule chains, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (nulls, dupes, misflagged statuses) with no test or note.
- A no-show rate with no reconciliation to the naive (raw-status) count.
- Treating each reschedule slot as an independent visit (double-counting one patient intent).
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Clinical Ops and Revenue Cycle both in the room:
1. "Walk me from the ops dashboard's 22% to your 13%." (the bridge)
2. "Why is *this* your definition of a no-show, and why that denominator?"
3. "A patient rescheduled twice then attended — how many no-shows is that in your model, and why?"
4. "Which problems are in our data vs. which must we fix at the front desk?"
5. "If this pipeline fails at 2am, what happens?"
