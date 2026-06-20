# Engagement 09 — Education Platform Learning Analytics

**Client:** Lumen Lyceum — a self-paced online learning platform (~250k enrolments/yr, B2C + B2B "teams" seats)
**Your role:** Analytics Engineering Consultant, engaged for a 2-week sprint
**Sponsor:** VP of Learning
**Stakeholders:** Head of Curriculum, Head of Credentialing, Data Lead (your day-to-day contact)

---

## 1. The situation (from your kickoff call)

> **VP of Learning:** "Every board deck, every investor update, every renewal conversation with a corporate customer has a 'course completion rate' on it. The problem is that depending on which team you ask, that number is **45 percent or it's 30 percent**. Marketing quotes one, our enterprise customers' procurement teams audit us against another, and they don't reconcile. I need a single, defensible completion definition — and I need to know how big the gap is and why."

> **Head of Curriculum:** "Completion means the learner did the work. They went through the lessons, start to finish. That's what we built, that's what they consumed, that's completion. The exam is optional polish — plenty of great learners never bother sitting it. If they finished the curriculum, they completed the course. Full stop."

> **Head of Credentialing (later, privately):** "With respect, watching videos is not completing a course. We issue certificates, and a certificate has to mean something to an employer. **Completion means they passed the final assessment.** If they didn't demonstrate mastery, they didn't complete it — they just attended. Curriculum's number is vanity; mine is the one we can defend in an audit."

You will notice the two stakeholders **do not agree on what "completed" means**. That is not a detail to smooth over — *it is the engagement*. Your job is to design a model that makes the definitions explicit, reconciles the gap, and lets each stakeholder see their own number **and** understand the others'.

---

## 2. What you've been given access to

Four raw tables, landed in your Snowflake sandbox by the source-system export (run the generator — see `data_generator/README.md`). This is **raw operational data, exactly as the source systems emit it.** It has not been cleaned.

| Table | Grain | Notes from the Data Lead |
|---|---|---|
| `RAW_STUDENTS` | one row per **enrolment** (student × course) | "Heads up — this is enrolment-grain, not person-grain. `STUDENT_ID` repeats: people re-enrol and take multiple courses. There's a coarse `ENROLLMENT_STATUS` an overnight job stamps, but I wouldn't fully trust it." |
| `RAW_COURSES` | one row per course | "Catalogue. `LESSON_COUNT` is how many lessons a course has, `PASS_THRESHOLD` is the score needed to pass the final." |
| `RAW_LESSONS` | one row per lesson-progress event | "Learners jump around — lessons aren't done in order. I've seen the same lesson logged twice when someone switches device. And the player drops the end timestamp sometimes." |
| `RAW_ASSESSMENTS` | one row per assessment *attempt* | "The final exam. People retry after failing, so an enrolment can have several rows. There's usually a short grading lag before the score lands." |

A full column-level data dictionary is in `data_generator/README.md`. **Read it, but trust it carefully** — the Data Lead's descriptions are how *they* understand the system, not necessarily ground truth.

---

## 3. The questions the client cannot answer (and you must)

These are the definitional questions at the heart of the discrepancy. Your deliverables must take an explicit, defensible position on each:

1. **What is a "completed" course?** All lessons done? A percentage threshold (e.g. ≥80% of lessons)? Final assessment passed? The platform's `ENROLLMENT_STATUS = 'completed'`? The two teams answer this differently and **all four give different numbers**.
2. **What is an "active learner"?** Active in the last 7 days? 28 days? Any activity this month? Active per enrolment or per person? This drives every engagement metric and every retention chart.
3. **What is the unit — the person or the enrolment?** `STUDENT_ID` repeats. Is your completion rate "% of enrolments completed" or "% of learners who have completed at least one course"? They are very different numbers.
4. **How do you handle a learner who finished the lessons but never sat the exam** (or sat it and failed)? Curriculum counts them; Credentialing doesn't. Where do they land in *your* mart?
5. **What do you do with the duplicate lesson events and retried/ungraded assessment attempts** so you don't over- or under-count completion?

> You will not get these answered for you. Make a decision, **write down the assumption, and be ready to defend it** when Curriculum and Credentialing push back in your final presentation.

---

## 4. Deliverables (the contract)

1. **Learning-analytics mart** — a clean, documented fact table at a defensible grain (most likely one row per enrolment) that carries **every** completion definition side-by-side as explicit flags, not a single baked-in winner.
2. **Student-engagement metrics** — at minimum: *completion rate (per definition), active-learner counts (per window), average lessons completed, assessment pass rate, time-to-complete.* Each with a written definition.
3. **A reconciliation** — a model or report that **explains the ~15-point completion gap**: how many learners finished lessons but never sat the exam, how many sat it and failed, how many "tested out" (passed without finishing every lesson), and where the platform's own status field disagrees. Stakeholders must be able to walk the bridge from the 45% lessons-based number to the 30% assessment-based number.
4. **Pipeline monitoring** — your data-quality tests + what severity each is + what happens when one fails in production, plus the freshness/monitoring story for a daily-loaded platform feed.
5. **Daily orchestration workflow** — a DAG design (Airflow/Dagster/Prefect) showing schedule, dependencies, freshness checks, and failure alerting. Design + reasoning required; a running DAG is a stretch goal.
6. Plus the standard program submission set (architecture diagram, source-to-target map, ≥10 tests, docs, assumptions log, deck).

---

## 5. Constraints & ground rules

- **Idempotency:** your pipeline must produce the same marts if re-run. Assume it runs daily and may be re-run after a failure.
- **Reproducibility:** all logic in dbt + version control. No manual SQL fixes in the warehouse.
- **Carry the definitions, don't pick one silently.** A mart that exposes only "lessons-based" or only "assessment-based" completion has failed the engagement. Each definition must be a documented, separately-queryable column.
- **Document the gap, don't hide it.** A model that makes the discrepancy *disappear* without explaining it has failed the engagement. The client needs to understand *why* 45% and 30% are both "true."

---

## 6. Definition of done

You are done when you can sit across from the Head of Curriculum and the Head of Credentialing — who disagree — and:

1. Show them a single mart both can pull their number from.
2. Walk them across the bridge that explains the ~15-point gap, line by line.
3. Tell them which data quality issues you found (duplicate lesson logs, ungraded attempts, dropped timestamps, the stale status field, the person-vs-enrolment trap), which you fixed, and which they need to fix at the source.
4. Defend every definitional choice — completed course, active learner, the unit of analysis — with a written assumption.

Good luck. The Data Lead is your contact for clarifications — but they're busy, so come with specific questions, not "is this right?"
