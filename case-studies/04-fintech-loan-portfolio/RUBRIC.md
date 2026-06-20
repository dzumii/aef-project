# Assessment Rubric — Engagement 04

You are assessed as a **consultant**, not a SQL author. The weighting reflects
that: how you *think*, *architect*, and *defend* matters more than syntax.

| Dimension | Weight | What we look for |
|---|---:|---|
| **Business understanding & problem framing** | 20% | Did you correctly identify that the engagement is about *conflicting definitions of default* — and that restructurings resetting the DPD clock are hiding risk? Did you produce the reconciliation bridge that explains the reported-vs-true PAR gap rather than hiding it? Are the restructured-and-re-delinquent loans surfaced as the actionable finding? |
| **Architecture & modeling** | 20% | Layered design (staging → intermediate → marts), sensible grain (one row per loan on the active book), idempotent, `ref()`/`source()` throughout, no business logic in staging. A clean repayment pipeline that derives per-loan delinquency from the posting feed. |
| **Data quality framework** | 15% | ≥10 tests, **≥3 business-rule tests** (not just generic), severities assigned, a clear "what happens when this fails in prod" story. |
| **Tradeoffs & assumptions** | 15% | A written log. Every definitional choice (DPD threshold, restructuring treatment, partial-payment treatment, active-book denominator, duplicate handling, currency) is explicit and defended. |
| **Correctness / does it tie out** | 10% | True PAR is reproducible from the raw repayment ledger; the reconciliation accounts for the gap against the register. The numbers are *right*. |
| **Orchestration design** | 10% | DAG with schedule, dependencies, source-freshness checks, failure alerting, and a re-run/idempotency story. Running it is a bonus. |
| **Documentation & communication** | 10% | Model/column docs, source-to-target map, architecture diagram, default-definition doc, and an exec summary + deck that a non-technical CRO can follow. |

## Scoring bands
- **Distinction (85–100):** True PAR computed from first principles and defended; restructured re-defaulters isolated as the headline finding; DPD threshold and restructuring treatment chosen explicitly; reconciliation bridge correct; business-rule tests; clean idempotent architecture; orchestration covers freshness + alerting; deck would survive a real client room (and a due-diligence lender).
- **Strong pass (70–84):** Correct true PAR30/PAR90, partials and duplicates handled, restructuring effect surfaced, ≥10 tests, assumptions documented, gap mostly explained.
- **Pass (55–69):** Reasonable marts, basic tests, some assumptions, PAR roughly right but gap not fully bridged or restructuring effect only partly handled.
- **Below bar (<55):** Adopts the default register as truth, treats partials as missed (or ignores them), honours the restructure clock-reset without comment, gap unexplained, no business-rule tests, or numbers don't tie out.

## Non-negotiables (auto-deductions)
- Hard-coded fixes in the warehouse instead of dbt logic.
- Silently dropping rows (nulls, dupes, missed instalments) with no test or note.
- A PAR number with no reconciliation to the default register.
- Reporting PAR straight off `RAW_DEFAULTS` with no independent ledger computation.
- Fewer than 10 tests, or zero business-rule tests.

## The defense (live or recorded)
Be ready to answer, with Credit Risk and Collections both in the room:
1. "Walk me from Collections' reported PAR to your true PAR." (the bridge)
2. "Why is *this* your DPD threshold, and why do you (or don't you) honour a restructure's clock reset?"
3. "Which problems are in our data vs. which must we fix at the source?"
4. "If this pipeline fails at 2am the night before the board pack, what happens?"
