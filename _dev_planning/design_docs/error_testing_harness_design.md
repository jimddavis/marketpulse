# error_testing harness — design

A **disposable** job harness that exercises every failure condition the
`job_status_gate_design.md` diagnostic must handle, using trivial do-nothing tasks so
**no real compute** is spent. It mirrors the **as-built** wiring (single `finalize_pipeline_log`,
`run_if: ALL_DONE`, self-raising) so a green/red sweep is valid evidence for the §3.1 commit gate.

> Teardown: delete `databricks_code/error_testing/` and remove the `- error_testing/*.yml`
> line from `databricks_code/databricks.yml`. Nothing else references it.

---

## 1. Method — fault injection by run-time parameter (deploy once)

The expensive part of "set up condition → deploy → run → check → edit → repeat" is the
**redeploy + code edit per scenario**. This harness removes both: every fault is selected by a
single job-level parameter, so you **deploy once** and drive each scenario from the `run` command.

- Job param **`fail_labels`** — CSV of task labels to fail. Every no-op task gets
  `{{job.parameters.fail_labels}}` plus its own hard-coded `label`, and does
  `if label in fail_labels: raise`. No redeploy, no edits between scenarios.
- Override at run time:
  - `databricks bundle run error_testing` *(happy)*
  - `databricks bundle run error_testing --params fail_labels=step4_a`
  - `databricks bundle run error_testing --params fail_labels=step4_a,step4_b`

`--params` is documented as "comma separated k=v pairs for job parameters" (verified via
`databricks bundle run --help`).

## 2. Verification — two CLI reads, ~0 extra compute

| Requirement | How |
|---|---|
| **Job + per-task status** (UI) | `databricks jobs get-run <run_id> -o json` → job `result_state` + each task's `result_state`. The JSON is the same data the UI shows; visual inspection is confirmatory. |
| **`pipeline_log` status + error capture** | `inspect_run.ipynb` (read-only) `SELECT`s `pipeline_log` + `pipeline_step_log` for the run. Also: `databricks jobs get-run-output <finalize_task_run_id>` shows the raised error text. |

## 3. Job DAG (Wiring Y — as-built)

```
init_pipeline_log (libs/init_pipeline_run_log.py)   opens pipeline_log RUNNING; sets run-id taskValue
   ├─ step2_a, step2_b   (noop_task.py)             python, no StepLog       → pre-logging class
        └─ step3_steplog (noop_notebook.ipynb)      notebook, StepLog ON     → logged class
             ├─ step4_a, step4_b (noop_notebook)    notebook, StepLog OFF    → pre-logging class (leaves)
                  └─ finalize_pipeline_log (libs/finalize_pipeline_run_log.py)
                                                     run_if: ALL_DONE, depends_on: step4_a, step4_b
```

**Load-bearing task_keys:** `init_pipeline_log` (notebook_init + finalize read its taskValue) and
`finalize_pipeline_log` (the cross-check skips itself by this exact key).

**Why `ALL_DONE` on the leaves is correct:** `run_if` inspects only *direct deps*; a skipped dep
satisfies neither `ALL_SUCCESS` nor `AT_LEAST_ONE_FAILED`. `ALL_DONE` treats skipped as terminal, so
finalize still fires when a mid-chain failure skips its descendants, and `get_run` reads the **whole
run** to find the real failed task. (A two-task `run_if` split would leave `pipeline_log` stuck
`RUNNING` on any mid-chain failure — the reason the design landed on a single `ALL_DONE` finalize.)

## 4. Artifacts

**Create — `databricks_code/error_testing/`**
- `noop_task.py` — `argv[1]=label, argv[2]=fail_labels`. Prints; `raise` iff `label ∈ fail_labels`. No logging imports → pre-logging python failure. (step2_a/b)
- `noop_notebook.ipynb` — params `label, step_sequence, use_steplog, fail_labels`. `use_steplog=true` → opens `StepLog`, raise caught by `step.fail(e); raise` (logged). `false` → no step row; raise is pre-logging; clean path `dbutils.notebook.exit()` outside any try. (step3 ×1, step4 ×2)
- `inspect_run.ipynb` — read-only audit-row viewer (`pipeline_run_id_filter` default `latest`).
- `job_error_testing.yml` — the job above.
- `README.md` — scenario runbook + teardown.

**Reuse as-is (the real code under test — not copied, §6/§20):**
`../libs/init_pipeline_run_log.py`, `../libs/finalize_pipeline_run_log.py`.

**Modify:** `databricks.yml` → add `- error_testing/*.yml` to `include`.

## 5. Core scenario matrix

| # | `fail_labels` | Job `result_state` | Task states | `pipeline_log` | Proves |
|---|---|---|---|---|---|
| 1 | *(empty)* | SUCCEEDED | all SUCCESS; finalize SUCCESS | `succeeded`, err null; step3 step-row `succeeded` | no false-positive |
| 2 | `step4_a` | FAILED | step4_a FAILED, step4_b SUCCESS, finalize FAILED | `failed` + real err; **0 step rows for step4_a** | pre-logging **notebook leaf** surfaces |
| 3 | `step2_a` | FAILED | step2_a FAILED; step3/step4 SKIPPED; finalize FAILED | `failed` + real err | **python** `get_run_output` capture + `ALL_DONE` survives skipped downstream |
| 4 | `step3_steplog` | FAILED | step3 FAILED; step4 SKIPPED; finalize FAILED | `failed`; err aggregates logged + Databricks sources; step3 step-row `failed` | logged path + dual-source aggregation + skip-resilience |
| 5 | `step4_a,step4_b` | FAILED | both leaves FAILED; finalize FAILED | `failed`; err lists **2** tasks | multi-failure aggregation |

## 6. Out of scope (Extended tier — not built; documented for later)

TIMEDOUT / CANCELED (need `timeout_seconds` + sleep / manual cancel), serverless auto-retry dedup
(already verified on `gold_load`), `run_job_task` wrapper propagation (surface 2 — needs a wrapper
job), and the best-effort Jobs-API degrade path (hard to inject deterministically). Add only if the
Core sweep leaves a real question.
