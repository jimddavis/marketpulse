# Job failure surfacing — making a failed task turn the job (and its audit row) red

> **As-built:** the `finalize_pipeline_log` task cross-checks Databricks' own task outcomes
> (`WorkspaceClient.get_run` / `get_run_output`), writes the real failure into `pipeline_log`, then
> **raises** — so a failed task surfaces on **all three** masking surfaces (job `result_state`, the
> `run_job_task` wrapper, and our `pipeline_log` audit row). This **supersedes** the earlier
> standalone `fail_detector` leaf (see §5 for why).

---

## ★ STATUS (2026-06-03)

**Architecture decided + as-built; full rollout done in the working tree (uncommitted); VERIFICATION
COMPLETE — proven on `gold_load` dev both paths AND via the dedicated `error_testing` harness (all
masking surfaces, incl. the `run_job_task` wrapper). Commit/merge pending (held by user).**

- **Proven on `gold_load` dev (2026-06-02), both paths:**
  - *Failure (pre-logging):* `100/0` injected in `pipeline_step_log_upsert` → every dim task failed
    before opening a step row → `pipeline_step_log` = **0 rows**, yet `pipeline_log` = **failed** with
    the real `ZeroDivisionError` captured, and job `result_state` = **FAILED**.
  - *Happy:* clean run → `pipeline_log` = succeeded, job SUCCEEDED, **no false positive**.
- **Verified platform facts** (the old open unknowns, now closed — see §2.6): `WorkspaceClient()` gets
  ambient auth inside a serverless `spark_python_task`; `get_run_output(...).error/.error_trace`
  returns the true error even for a `notebook_task`; serverless **auto-retry** requires taking the
  **latest attempt per `task_key`** (fixed).
- **Rolled out (uncommitted, branch `finalize-databricks-diagnostic`):** `{{job.run_id}}` wired as
  `argv[3]` into **all 8** finalize tasks; `libs/fail_detector.py` deleted and its `silver_load` task
  removed; the diagnostic lives in `finalize_pipeline_run_log.py` + `pipeline_logging.pipeline_log_finalize`.
  `bundle validate -t dev` GREEN; scripts compile.
- **VERIFIED 2026-06-03 via the `error_testing` harness** (see `error_testing_harness_design.md`) — a
  disposable job of do-nothing tasks that exercises every surface cheaply, mirroring the as-built single
  `ALL_DONE` finalize. Fault injection is the run-time param `fail_labels` (deploy once, drive scenarios
  by `--params`). All passed on dev:
  - **Happy** → job SUCCEEDED, `pipeline_log` succeeded, no false positive.
  - **Pre-logging notebook leaf** (`step4_a`) → job FAILED, `pipeline_log` failed + real error, **0 step
    rows** for the failing task (the motivating class).
  - **Pre-logging python** (`step2_a`) → job FAILED; downstream `UPSTREAM_FAILED` yet finalize still ran
    (`ALL_DONE` skip-resilience) and caught it — proves `get_run_output` works for `spark_python_task`.
  - **Logged** (`step3_steplog`) → job FAILED; `error_message` aggregates BOTH sources ("N logged
    step(s) failed" + "N Databricks task(s) failed").
  - **Multi** (`step4_a,step4_b`) → both aggregated.
  - **Auto-retry dedup** held (a retried failed task counted once, not double).
  - **#4 RESOLVED** (`error_testing_wrapper` probe): under `run_job_task`, `{{job.run_id}}` is the
    **child's own run id** (not the wrapper's), so the child finalize enumerates the child's tasks; the
    child FAILED and the **wrapper rolled up FAILED** (surface 2, no SWF mask). Databricks exposes a
    separate `{{parent_run_id}}` for the wrapper run.

**Remaining:** commit + merge to main (held by user). The `error_testing/` harness is disposable —
teardown = delete the folder + the `- error_testing/*.yml` include line in `databricks.yml`.

---

## 1. Problem

A failed notebook task left the per-phase job — **and** its `run_job_task` wrapper (`full_bronze` /
`full_silver` / `full_gold`) — reporting **green**, *and* our `pipeline_log` audit row reading
`succeeded`. Observed 2026-06-01: `full_bronze` ran `SUCCESS` while every bronze table was empty (root
cause: a `NameError` in a loader). The failure was real and the task *was* marked `FAILED`, but it was
masked on **three** surfaces:

| # | Surface | Set by | Why it lied |
|---|---|---|---|
| 1 | Job `result_state` | Databricks (leaf-task outcome) | finalize is the sole leaf and *succeeds* → `SUCCESS_WITH_FAILURES`, not `FAILED` (§1.1) |
| 2 | `run_job_task` wrapper | child `result_state` | treats child SWF as non-failure → wrapper green |
| 3 | `pipeline_log.status` | `finalize` scanning `pipeline_step_log` | a **pre-logging** failure writes 0 step rows → scan finds none → `succeeded` (§2.1) |

### 1.1 Root cause — surfaces 1 & 2 (Verified)

Databricks classifies a run by its **leaf tasks** only:

> "Databricks determines whether a job run was successful based on the outcome of the job's leaf
> tasks. A leaf task is a task that has no downstream dependencies."
> — [Configure task dependencies](https://docs.databricks.com/aws/en/jobs/run-if),
>   [Run tasks conditionally](https://learn.microsoft.com/en-us/azure/databricks/workflows/jobs/conditional-tasks)

| Outcome | Job `result_state` |
|---|---|
| all leaf tasks succeed, no other failures | `SUCCEEDED` |
| all leaf tasks succeed, a **non-leaf** task failed | `SUCCESS_WITH_FAILURES` |
| a **leaf** task fails | `FAILED` |

In every per-phase job, `finalize_pipeline_log` (`run_if: ALL_DONE`) is the **sole leaf**. It runs and
succeeds even when a data task failed → the data failure is a *non-leaf* failure → `result_state =
SUCCESS_WITH_FAILURES`, never `FAILED`. The very mechanism that guarantees the `pipeline_log` row is
closed is what demotes the job from `FAILED` to SWF. Then **`run_job_task` treats a child
`SUCCESS_WITH_FAILURES` as a non-failure** — only a hard child `FAILED` fails the parent — so the SWF
child rolls the `full_*` wrapper up to green.

### 1.2 There is no flag for this

There is no `run_job_task` option to treat SWF as failure, and no setting to stop an `ALL_DONE` finalize
from being the leaf. **The leaf task is the only control surface Databricks exposes for job status.**
The documented idiom — "add a downstream task and define success/failure logic in this final task" — is
used by the community to *mask* failures; we invert it to *surface* them.

---

## 2. Design — the finalize-resident diagnostic

`finalize_pipeline_log` already (a) runs `ALL_DONE` (so it always fires), (b) is the **sole leaf**, and
(c) **owns the `pipeline_log` verdict**. That makes it the natural single place to fix **all three**
surfaces. As-built, `finalize`:

1. asks Databricks for THIS run's task outcomes — `WorkspaceClient().jobs.get_run(job_run_id)`;
2. for each sibling's **latest attempt** in `result_state == FAILED`, pulls the real error with
   `get_run_output(task.run_id).error` (ANSI-stripped);
3. passes those into `pipeline_log_finalize(..., databricks_failures=[...])`, which writes
   `status = failed` + the captured error **even when `pipeline_step_log` has 0 rows** — fixes surface 3;
4. **raises** if any failure was found → `finalize` becomes a **failed leaf** → job `result_state =
   FAILED` (surface 1) → `run_job_task` propagates red (surface 2).

The `pipeline_log` row is committed in step 3 **before** the raise in step 4, so the audit row closes
honestly even though the task then fails.

```
init ─► data tasks ─► finalize_pipeline_log (run_if: ALL_DONE, SOLE LEAF)
                          │  get_run → failed siblings → get_run_output(.error)
                          │  pipeline_log = failed + real error   ← commits (surface 3)
                          └─ raise if any failure                 ← failed leaf → job FAILED (surfaces 1, 2)
```

### 2.1 Why detection must consult Databricks, not our audit table

The first instinct — derive job status by reading `pipeline_log.status` (which `pipeline_log_finalize`
computes by scanning `pipeline_step_log` for `failed` rows) — **is blind to a failure that occurs before
a step opens its `RUNNING` row.** That is exactly the 2026-06-01 class:

```python
nb   = Utils.get_notebook_context(dbutils)   # ← NameError hit HERE (cell 3, first line)
step = StepLog(...)                           #   StepLog never constructed → no RUNNING row written
```

Chain when the failure is pre-logging: the step writes **no row at all** → the finalize scan finds zero
`failed` rows → it sets `succeeded`. Any gate that trusts the audit table inherits that blind spot,
because the audit table is a *derived* view that only exists if the notebook reached its logging code.
**The only system that reliably knows "this task ran and failed" regardless of our logging is Databricks
itself** — so detection keys off the Databricks task outcome. (Note: this is strictly *more* complete,
not a different set — `StepLog.fail` always re-raises, so every audit-logged failure is *also* a
Databricks `FAILED` task; the cross-check catches that set **plus** the pre-logging failures.)

### 2.2 Mechanism summary

| Run condition | `finalize` behavior | `pipeline_log` | Job `result_state` |
|---|---|---|---|
| all tasks succeeded | get_run finds no failures → no raise | `succeeded` | `SUCCEEDED` ✅ |
| a task failed (logged or pre-logging) | get_run finds it → write `failed` + error → **raise** | `failed` + real error ✅ | `FAILED` ✅ |

### 2.3 As-built — `databricks_code/libs/finalize_pipeline_run_log.py`

```python
import re
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunResultState

# argv[1]=shared_lib_path, argv[2]=catalog, argv[3]=this job run's id. All REQUIRED.
if len(sys.argv) < 4:
    raise RuntimeError("Expected sys.argv[1]=shared_lib_path, [2]=catalog, [3]=job.run_id ...")
sys.path.insert(0, sys.argv[1])
catalog      = sys.argv[2]
job_run_id   = int(sys.argv[3])
audit_schema = f"{catalog}.audit"

from pipeline_logging import pipeline_log_finalize

PIPELINE_RUN_ID = dbutils.jobs.taskValues.get(taskKey="init_pipeline_log", key="pipeline_run_id")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# TIMEDOUT/CANCELED never reach our StepLog, so keying on FAILED alone would re-open the gap.
# UPSTREAM_FAILED/UPSTREAM_CANCELED are excluded (derivative — the root FAILED task is caught directly).
FAILURE_STATES = {RunResultState.FAILED, RunResultState.TIMEDOUT,
                  RunResultState.CANCELED, RunResultState.MAXIMUM_CONCURRENT_RUNS_REACHED}

# BEST-EFFORT: the whole cross-check is guarded so a transient Jobs-API failure DEGRADES to an
# audit-table-only finalize — it can never crash before the row is closed, nor false-fail a green run.
databricks_failures = []
try:
    workspace = WorkspaceClient()
    run = workspace.jobs.get_run(run_id=job_run_id)

    # run.tasks holds EVERY attempt — serverless auto-retries a failed task, so a healed task appears
    # twice (attempt 0 FAILED, attempt 1 SUCCESS). Keep only the LATEST attempt per task_key so a
    # transient the retry healed does NOT fail the job.
    latest_attempt = {}
    for task in run.tasks or []:
        if task.task_key == "finalize_pipeline_log":      # finalize itself is still RUNNING
            continue
        seen = latest_attempt.get(task.task_key)
        if seen is None or (task.attempt_number or 0) > (seen.attempt_number or 0):
            latest_attempt[task.task_key] = task

    for task in latest_attempt.values():
        if not (task.state and task.state.result_state in FAILURE_STATES):
            continue
        try:
            output = workspace.jobs.get_run_output(run_id=task.run_id)
            error = ANSI_ESCAPE.sub("", (output.error or "no error message")).strip()
        except Exception as output_error:             # one unreadable output must not drop the failure
            error = f"(error detail unavailable: {output_error})"
        databricks_failures.append(
            {"task_key": task.task_key, "error": f"[{task.state.result_state.value}] {error}"})
except Exception as cross_check_error:                 # degrade, do NOT crash
    print(f"WARNING: task-outcome cross-check failed ({cross_check_error}); audit-only finalize.")

pipeline_log_finalize(spark, audit_schema, PIPELINE_RUN_ID, databricks_failures)  # writes 'failed' if any

if databricks_failures:                               # make finalize the failed leaf → job FAILED
    failed_keys = ", ".join(failure["task_key"] for failure in databricks_failures)
    raise RuntimeError(f"finalize: {len(databricks_failures)} Databricks task(s) failed ... {failed_keys}.")
```

### 2.4 As-built — `pipeline_logging.pipeline_log_finalize`

Signature gained an optional `databricks_failures` (backward-compatible, default `None` = prior
behavior). Status is `failed` when **either** source shows a failure; `error_message` aggregates both:

```python
def pipeline_log_finalize(spark, audit_schema, pipeline_run_id,
                          databricks_failures: list[dict[str, str]] | None = None) -> None:
    databricks_failures = databricks_failures or []
    # ... read pipeline_name/started_timestamp from the existing row ...
    failed = spark.sql("SELECT COUNT(*) AS failed_count, COLLECT_LIST(notebook_name) AS failed_notebooks "
                       f"FROM {audit_schema}.pipeline_step_log "
                       f"WHERE pipeline_run_id = '{pipeline_run_id}' AND status = '{STATUS_FAILED}'").collect()[0]
    logged_failures = failed["failed_count"] > 0
    if logged_failures or databricks_failures:
        status = STATUS_FAILED
        # ... aggregate "N logged step(s) failed: ..." and "N Databricks task(s) failed: <task>: <error>; ..." ...
    else:
        status = STATUS_SUCCEEDED
        error_message = None
    pipeline_log_upsert(spark, audit_schema, pipeline_run_id, pipeline_name, status,
                        started_timestamp, ended_timestamp, error_message)
```

### 2.5 As-built — job YAML wiring (every per-phase job)

`finalize` needs its own job-run id; pass Databricks' dynamic value as `argv[3]`:

```yaml
        - task_key: finalize_pipeline_log
          depends_on: [ ... every leaf data task ... ]   # so get_run snapshots terminal states (§2.6)
          run_if: ALL_DONE
          spark_python_task:
            python_file: ../libs/finalize_pipeline_run_log.py
            parameters:
              - "{{job.parameters.shared_lib_path}}"   # sys.argv[1]
              - "{{job.parameters.catalog}}"           # sys.argv[2]
              - "{{job.run_id}}"                       # sys.argv[3] — this job run's id
          environment_key: default
```

`finalize`'s `depends_on` must reach **every leaf data task** (directly or transitively), so that by the
time it runs every sibling has hit a terminal state and `get_run` sees the true outcome. Verified per
job during rollout (gold's facts cover the dims transitively; the download/weather/step_log_test jobs
are linear chains; bronze/silver/weather list all loaders).

### 2.6 Verified platform facts (closed the old unknowns)

- **`WorkspaceClient()` ambient auth works inside a serverless `spark_python_task` run-tier context** —
  no `notebook_task` fallback needed. (Was the #1 open risk; confirmed on the gold_load run.)
- **`get_run_output(run_id).error` / `.error_trace` return the real error for a `notebook_task`** — even
  for a pre-logging failure the audit table never saw. `.error` is short and clean; `.error_trace` is
  ANSI-colored (stripped before storing).
- **Serverless auto-retry** ([[serverless-auto-retry-gotcha]]): `get_run` returns every attempt; a
  task that FAILED then SUCCEEDED on retry appears twice. Must take the **latest attempt per
  `task_key`** — counting any failed attempt double-counts and false-positives a healed transient.
- `{{job.run_id}}` resolves to the running job's id and `int()`-parses cleanly (observed: real ids on
  the dev runs). **Confirmed 2026-06-03 (`error_testing_wrapper` probe):** under a `run_job_task`
  wrapper it resolves to the **CHILD** run id, not the parent — so the child's finalize cross-check
  enumerates the child's own tasks (the loaders), not the wrapper's `run_job_task` shells. Databricks
  exposes a separate `{{parent_run_id}}` for the wrapper run, which is why `{{job.run_id}}` stays
  child-scoped.
- **`RunResultState` non-success terminal states** include `TIMEDOUT`, `CANCELED`,
  `MAXIMUM_CONCURRENT_RUNS_REACHED` (besides `FAILED`). A timed-out/canceled task never reaches our
  `StepLog`, so the detector keys on a **set** of failure states, not `FAILED` alone — otherwise a
  timeout re-opens the masking gap. `UPSTREAM_FAILED`/`UPSTREAM_CANCELED`/`EXCLUDED`/`SUCCESS` are
  deliberately not counted (derivative or non-failures).
- **Hardening (from code review):** the entire `get_run`/`get_run_output` cross-check is wrapped
  best-effort. A transient Jobs-API failure must not (a) crash `finalize` before the `pipeline_log` row
  is closed, nor (b) false-fail an otherwise-successful run — so on API error it **degrades** to the
  prior audit-table-only finalize. Per-task `get_run_output` is also individually guarded so one
  unreadable output doesn't drop the other failures.

---

## 3. Scope — jobs changed (one atomic change set, §20)

The shared `finalize_pipeline_run_log.py` is called by **8 jobs**; making `argv[3]` required forces
wiring all of them together (a half-migration would break the un-wired jobs' finalize):

- [x] `job_bronze_load.yml`
- [x] `job_silver_load.yml`  *(also: `fail_detector` task removed)*
- [x] `job_gold_load.yml`
- [x] `job_download_sources.yml`
- [x] `job_step_log_test.yml`
- [x] `job_weather_bronze.yml`
- [x] `job_weather_download.yml`
- [x] `job_weather_silver_gold.yml`

Removed: **`databricks_code/libs/fail_detector.py`** (superseded — see §5). **Out of scope:** the
`full_*` `run_job_task` wrappers (they propagate a real child `FAILED` for free); `job_catalog_setup.yml`
and `job_seed_dims.yml` (no `init/finalize` pipeline_log lifecycle).

---

## 4. Verification (the §3.1 gate — required before commit)

Static checks (`py_compile`, `bundle validate -t dev`) are **pre-commit checks, not the test.** The real
gate is a dev run.

1. **Happy path — DONE (gold_load, 2026-06-02):** clean run → job `SUCCEEDED`, `pipeline_log` succeeded,
   no false positive (retry dedup confirmed — 3 dims that auto-retried did not double-count).
2. **Failure path A — logged failure:** raise inside a loader cell *after* `StepLog` opens → loader
   FAILED, step row closed `failed`, `finalize` writes `failed` + raises, job `FAILED`, wrapper red.
3. **Failure path B — pre-logging (the motivating class) — DONE (gold_load, 2026-06-02):** `100/0` in
   `pipeline_step_log_upsert` → every dim failed before StepLog → **0 step rows**, yet `pipeline_log` =
   **failed** with the real `ZeroDivisionError`, job `result_state` = **FAILED**. This is the case an
   audit-reading gate would have passed.
4. **DONE (2026-06-03) — via the `error_testing` harness instead of a bronze rebuild.** The harness
   re-ran path B (pre-logging) on a non-gold job for both notebook and python tasks, plus the logged
   path, multi-failure, skip-resilience, auto-retry dedup, and the `run_job_task` wrapper (#4 / surface
   2). All green/red as designed. See the ★ STATUS block and `error_testing_harness_design.md`.

Inspect via `databricks jobs get-run <id>` (per-task states) and the audit tables — never trust the
wrapper alone. (Harness audit rows were read in one shot via the serverless SQL warehouse statement
API rather than per-scenario notebook runs.) All gate items verified; commit pending (held by user).

---

## 5. History — why the `fail_detector` leaf was superseded

The first as-built was a separate **`fail_detector`** leaf (`run_if: AT_LEAST_ONE_FAILED`, body = just
`raise`), proven on `silver_load` dev (2026-06-01). It correctly fixed surfaces 1 & 2 — but **not
surface 3**: it never touches `pipeline_log`, so a pre-logging failure still left the audit row reading
`succeeded` (finalize's scan saw 0 failed step rows). Fixing surface 3 *requires* consulting Databricks'
task outcomes anyway (the audit table is blind by definition), and the natural owner of that consult is
`finalize` (it already owns `pipeline_log` and is already the sole `ALL_DONE` leaf). Folding the
detection **and** the raise into `finalize` makes **one** leaf fix all three surfaces — so the separate
`fail_detector` leaf became redundant and was removed. (Detail of the masking mechanism and the original
silver proof: [[job-failure-masking-gotcha]].)

---

## 6. Related

- Memory: [[job-failure-masking-gotcha]] (the WHY + full task state), [[serverless-auto-retry-gotcha]]
  (latest-attempt dedup), [[dbutils-notebookexit-gotcha]], [[free-edition-daily-limit-gotcha]],
  [[deployment-status]].
- Code: `databricks_code/libs/finalize_pipeline_run_log.py`, `databricks_code/libs/pipeline_logging.py`
  (`pipeline_log_finalize`), the 8 `resources/job_*.yml` finalize tasks.
- Runbook for the rebuild test: `deploy_new_target.md`.
