# How the pipeline knows when it failed — error handling, explained

**Audience:** developers working on this pipeline, and the IT/data manager who owns its
reliability. This document explains *what* the error-handling framework does, *why* it is built
the way it is, and *how we proved it works*. It assumes no prior knowledge of this codebase.

For the formal design and verification record, see `job_status_gate_design.md`. For the test rig,
see `error_testing_harness_design.md`. This document is the plain-language companion to both.

---

## 1. The one-sentence summary

The pipeline now **fails loudly**: if any step fails — even in a way our own logging never saw —
the job is marked **FAILED**, the audit record reads **failed** with the real error, and any
parent job that launched it also turns red. Previously, a real failure could leave everything
reporting **green**.

---

## 2. The problem, in business terms

On 2026-06-01 the `full_bronze` pipeline reported **SUCCESS**, but every Bronze table it was
supposed to populate was **empty**. The root cause was a real bug — a `NameError` in one loader —
and that task *was* correctly marked failed by the platform. Yet three different status indicators
all said "everything is fine."

For an operator, this is the worst possible failure mode: not a crash you can see, but a **silent**
one. Downstream reports, dashboards, and decisions would have been built on empty or stale data,
with nothing flagging that anything was wrong. The cost of a failure you can see is a re-run; the
cost of a failure you *can't* see is wrong numbers in front of stakeholders.

The goal of this framework: **make "green" trustworthy.** A green pipeline must mean the data is
actually there and correct; a red pipeline must be impossible to miss.

---

## 3. Background — how the pipeline records what it does

Before the fix, it helps to understand the normal "happy path" bookkeeping. Every pipeline run
writes to two audit tables in Unity Catalog (`<catalog>.audit`):

| Table | Granularity | What it answers |
|---|---|---|
| `pipeline_log` | One row per **run** | "Did the run as a whole succeed or fail, when, and why?" |
| `pipeline_step_log` | One row per **step** (notebook) | "Did each individual step succeed, how many rows did it read/write, and what was its error?" |

The lifecycle of a run:

1. **`init_pipeline_run_log`** runs first. It opens a `pipeline_log` row with status `running` and
   mints a shared `pipeline_run_id` that every step stamps onto its records.
2. **Each step** (a notebook — Bronze loader, Silver transform, etc.) opens its own
   `pipeline_step_log` row at `running`, does its work, then closes it at `succeeded` or `failed`.
   This is handled by a small helper called **`StepLog`** so every notebook does it the same way.
3. **`finalize_pipeline_log`** runs last. It closes the `pipeline_log` row — deciding the run's
   final status.

Status values are a fixed vocabulary: `running`, `succeeded`, `failed`, `no_files`, `skipped`.

That is the bookkeeping. The 2026-06-01 incident was a failure of **step 3** — `finalize` decided
the run had succeeded when it hadn't.

---

## 4. Why a failure used to hide — three "masking surfaces"

The failure was hidden on three independent layers. All three had to be fixed.

### Surface 1 — the job's own status (`result_state`)

Databricks decides whether a *job run* succeeded by looking only at its **leaf tasks** — the tasks
with nothing downstream of them. The rule:

- A leaf task fails → job is **FAILED**.
- All leaf tasks succeed, but some *non-leaf* task failed → job is **SUCCESS_WITH_FAILURES** (not
  FAILED).

Here is the trap. Our `finalize` task is deliberately configured to run **even when upstream steps
fail** (so it can always close the audit row) — which makes it the *only* leaf task. When a data
step failed, `finalize` still ran and *succeeded*, so the job's only leaf succeeded → the run was
classified `SUCCESS_WITH_FAILURES`, never `FAILED`. The very mechanism that guarantees the audit
row gets closed was demoting the job from FAILED to a softer "completed with failures" state.

### Surface 2 — the parent ("wrapper") job

The `full_bronze` / `full_silver` / `full_gold` jobs don't do any work themselves; they just launch
the per-phase jobs in order. Databricks treats a child job's `SUCCESS_WITH_FAILURES` as **not a
failure** — only a hard child `FAILED` fails the parent. So the soft-failed child rolled the parent
all the way up to green.

### Surface 3 — our own audit record (`pipeline_log.status`)

`finalize` decided the run's status by **counting failed rows in `pipeline_step_log`**. That works
only if the failing step got far enough to write a row. But the 2026-06-01 bug crashed the step
*before* it opened its `pipeline_step_log` row:

```
nb   = get_notebook_context(...)   # ← crashed HERE, on the first line
step = StepLog(...)                #   never reached → no audit row was ever written
```

With **zero** failed step rows, the count was zero, so `finalize` wrote `succeeded`. We call this a
**"pre-logging" failure** — a failure that happens before the step starts logging. Our audit table
is a *derived* record: it only reflects failures that the code lived long enough to write down. A
status computed from it inherits that blind spot.

| # | Surface | Why it lied |
|---|---|---|
| 1 | Job `result_state` | `finalize` is the sole leaf and succeeds → run is "SUCCESS_WITH_FAILURES", not FAILED |
| 2 | Parent wrapper job | A child "SUCCESS_WITH_FAILURES" is treated as non-failure → parent green |
| 3 | `pipeline_log.status` | Derived by counting failed step rows — a pre-logging failure writes none |

---

## 5. The key insight

You cannot detect surface 3 by reading our own audit table, because **the audit table is exactly
what the failure prevented from being written.** The only system that reliably knows "this task ran
and failed," no matter where in the code it died, is **Databricks itself** — it tracks every task's
outcome independently of our logging.

So the fix is: at the end of every run, **ask Databricks what actually happened**, and reconcile
that against our audit record. Databricks is the source of truth for "did it fail"; our audit
tables remain the source of truth for the richer detail (row counts, per-step timings, business
context).

This is strictly *more* complete than the old approach, not different: every failure our logging
caught is also a failed task in Databricks' eyes (our `StepLog.fail` always re-raises). Consulting
Databricks catches that same set **plus** the pre-logging failures the audit table missed.

---

## 6. The fix — a self-checking `finalize`

`finalize` was already the natural place to fix all three surfaces: it always runs, it is the sole
leaf, and it owns the `pipeline_log` verdict. It now does four things:

```
init ─► data steps ─► finalize  (runs no matter what; the sole leaf)
                         │  1. ask Databricks for THIS run's task outcomes
                         │  2. for each failed task, pull its real error message
                         │  3. write pipeline_log = failed + that error   ← audit row is honest (fixes surface 3)
                         └─ 4. then deliberately fail itself              ← failed leaf → job FAILED (fixes surfaces 1 & 2)
```

1. **Ask Databricks.** `finalize` calls the Databricks Jobs API for the current run and reads every
   sibling task's outcome.
2. **Pull the real error.** For each failed task it fetches that task's actual error message and
   stack trace (cleaned of terminal color codes) — so the audit row records *what* broke, not just
   *that* something did.
3. **Write the honest audit row.** It records `pipeline_log.status = failed` with the aggregated
   error — **even when zero step rows exist**. This is the surface-3 fix.
4. **Fail on purpose.** If any task failed, `finalize` raises an error *after* the audit row is
   safely written. That turns `finalize` (the sole leaf) into a failed leaf, so Databricks marks
   the job **FAILED** (surface 1), and a parent wrapper sees a hard `FAILED` child and turns red
   too (surface 2).

The ordering matters: the audit row is committed in step 3 *before* the deliberate failure in step
4, so the record is always closed honestly even though the task then fails.

### Three robustness details worth knowing

- **It counts more than "FAILED."** A task can also end as **timed out** or **canceled** — states
  that, like a pre-logging crash, never reach our `StepLog`. `finalize` treats all of these as
  failures, so a timeout can't quietly re-open the gap.
- **It de-duplicates auto-retries.** Databricks' serverless compute automatically retries a failed
  task; a task that failed once then succeeded on retry appears twice in the history. `finalize`
  keeps only the **latest attempt per task**, so a transient blip that healed itself does *not*
  false-alarm the run as failed.
- **It degrades safely.** The entire "ask Databricks" step is wrapped defensively. If the Jobs API
  is briefly unreachable, `finalize` falls back to the old audit-table-only behavior rather than
  crashing or falsely failing a good run. We lose only the pre-logging-failure catch during an API
  outage; everything the audit table *did* capture still closes correctly.

---

## 7. What "correct" looks like now

| Run condition | Job `result_state` | `pipeline_log.status` | Parent wrapper |
|---|---|---|---|
| All steps succeeded | SUCCEEDED | `succeeded` | green |
| A step failed (logged *or* pre-logging) | FAILED | `failed` + real error | red |

No middle ground, no silent "SUCCESS_WITH_FAILURES," no green-over-empty-tables.

---

## 8. How we proved it (and why you can trust the proof)

Testing this safely is itself a design problem: we needed to trigger failures *on purpose*, in
several different shapes, without running the real (compute-heavy) pipelines. So we built a
**disposable test harness** — a small job of do-nothing tasks whose only feature is the ability to
fail on command, driven by a single run-time parameter (`fail_labels`). Deploy once; trigger each
scenario from the command line; tear it down afterward.

Every scenario was checked on two axes: **(1)** did the job and each task show the right status, and
**(2)** did the `pipeline_log` audit row record the right status and capture the real error.

| Scenario | Expected | Result |
|---|---|---|
| Everything succeeds | Job SUCCEEDED; audit `succeeded`; no false alarm | ✅ |
| A leaf step fails **before** it starts logging | Job FAILED; audit `failed` + real error; **zero step rows** for that step | ✅ |
| A step fails and skips everything after it | `finalize` still runs and still catches it (the audit table would have missed this) | ✅ |
| A step fails **after** it started logging | Audit error names **both** sources — the logged step *and* the platform task | ✅ |
| Two steps fail at once | Both errors aggregated into the audit record | ✅ |
| A failed task auto-retried and healed | Counted **once**, not double — no false alarm | ✅ |
| A child job fails under a parent wrapper | Child FAILED **and the parent wrapper turned red** (surface 2) | ✅ |

The last row is the exact shape of the original 2026-06-01 incident (a parent wrapper reporting
green over a failed child). It is now provably red.

---

## 9. Operational guidance — reading a pipeline run

For anyone monitoring or debugging a run:

- **Trust the job status now.** A FAILED job means a real failure; a SUCCEEDED job means every step
  genuinely completed. The historical advice "never trust a green wrapper, always check the data"
  is no longer a required safety net — though spot-checking row counts after a run remains good
  hygiene.
- **To see *what* failed:** open the `pipeline_log` row for the run — its `error_message` names the
  failed task(s) and the real error. For per-step detail (row counts, timings), read
  `pipeline_step_log` for the same `pipeline_run_id`.
- **To see it from the platform side:** `databricks jobs get-run <run_id>` shows the per-task
  outcomes the framework reconciled against.
- **A step row stuck at `running`** is a signal in itself: it means a notebook started but never
  reached its closing line — worth investigating even if the run otherwise looks closed.

---

## 10. Why it's built this way — the rationale in one place

- **Fail loud, not silent.** A visible failure costs a re-run; a hidden one costs wrong decisions.
  Every design choice here favors surfacing failure over tidiness.
- **Trust the platform for "did it fail," trust our tables for "what happened."** Our audit tables
  are rich but only exist when the code survives to write them; Databricks' task outcomes are
  authoritative but coarse. The framework uses each for what it's reliably good at.
- **One component fixes all three surfaces.** Rather than scatter failure-handling across many
  tasks, the single `finalize` task — which already always runs and already owns the verdict — does
  the detection, the honest audit write, and the deliberate fail. One place to reason about, one
  place to maintain.
- **Safe under stress.** Retries are de-duplicated, API hiccups degrade gracefully, and the audit
  row is always written before the deliberate failure. The framework prefers a correct-but-degraded
  result over a crash or a false alarm.
