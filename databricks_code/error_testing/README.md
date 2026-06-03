# error_testing — disposable failure-condition harness

Exercises every failure condition the `job_status_gate_design.md` diagnostic must handle, using
trivial do-nothing tasks so **no real compute** is spent. Mirrors the **as-built** wiring (single
`finalize_pipeline_log`, `run_if: ALL_DONE`, self-raising), so a green/red sweep is valid evidence
for the §3.1 commit gate.

Full design: `_dev_planning/design_docs/error_testing_harness_design.md`.

## DAG

```
init_pipeline_log
  ├─ step2_a, step2_b        (noop_task.py)      python, no StepLog   → pre-logging class
       └─ step3_steplog      (noop_notebook)     notebook, StepLog ON → logged class
            ├─ step4_a, step4_b (noop_notebook)  notebook, no StepLog → pre-logging class (leaves)
                 └─ finalize_pipeline_log        run_if: ALL_DONE
```

## Use — deploy ONCE, then drive every scenario by parameter

```bash
cd databricks_code
databricks bundle deploy -t dev          # once
```

Fault injection is the run-time job parameter `fail_labels` (CSV of task labels). No redeploy, no
code edits between scenarios:

| # | Command | Expect job | Expect `pipeline_log` |
|---|---|---|---|
| 1 | `databricks bundle run error_testing` | SUCCEEDED | `succeeded`, no error |
| 2 | `databricks bundle run error_testing --params fail_labels=step4_a` | FAILED | `failed` + real error (0 step rows for step4_a) |
| 3 | `databricks bundle run error_testing --params fail_labels=step2_a` | FAILED | `failed` + real error (python capture; step3/4 skipped) |
| 4 | `databricks bundle run error_testing --params fail_labels=step3_steplog` | FAILED | `failed`, aggregates logged + Databricks sources; step3 step-row `failed` |
| 5 | `databricks bundle run error_testing --params fail_labels=step4_a,step4_b` | FAILED | `failed`, lists 2 tasks |

Valid labels: `step2_a`, `step2_b`, `step3_steplog`, `step4_a`, `step4_b`.

## Verify each run

```bash
databricks jobs get-run <run_id> -o json     # job + per-task result_state (the UI data, as text)
```
Then run `inspect_run.ipynb` (read-only; `pipeline_run_id_filter` defaults to `latest`) to see the
`pipeline_log` verdict + error and the `pipeline_step_log` rows.

## Teardown

Delete this folder and remove the `- error_testing/*.yml` line from `databricks.yml`.
Nothing else references it. (`databricks bundle destroy -t dev` removes the deployed job.)
