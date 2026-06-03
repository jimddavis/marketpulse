# -------------------------------------------------------------------------------
# error_testing harness — do-little spark_python task (Step Two).
#
# Does NOTHING except optionally raise, selected by the run-time `fail_labels`
# parameter. Imports no logging code, so a raise here is a PRE-LOGGING failure
# (it never opens a pipeline_step_log row) — the masking class the finalize
# cross-check must still surface. See _dev_planning/design_docs/error_testing_harness_design.md.
#
# Parameters (spark_python_task.parameters): argv[1]=label, argv[2]=fail_labels (CSV).
# `label` is hard-coded per task in job_error_testing.yml; `fail_labels` is the job
# parameter, overridden per run with `--params fail_labels=<labels>`.
# -------------------------------------------------------------------------------
import sys

if len(sys.argv) < 2:
    raise RuntimeError(
        "Expected sys.argv[1]=label and (optional) sys.argv[2]=fail_labels. "
        "Set both in job_error_testing.yml under this task's spark_python_task.parameters."
    )

label       = sys.argv[1]
fail_labels = [s.strip() for s in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if s.strip()]

print(f"noop_task[{label}]: fail_labels={fail_labels}")

# Pre-logging failure injection — no StepLog, no audit row written for this task.
if label in fail_labels:
    raise RuntimeError(
        f"noop_task[{label}]: injected PRE-LOGGING failure (fail_labels={fail_labels})"
    )

print(f"noop_task[{label}]: clean no-op success")
