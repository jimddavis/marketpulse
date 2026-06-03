# -------------------------------------------------------------------------------
# Finalize the pipeline_log row opened by init_pipeline_run_log.py, and surface
# failures that our own audit logging never saw.
#
# pipeline_log_finalize alone trusts pipeline_step_log, which is blind to a failure
# that occurs before a notebook opens its step row (the "pre-logging" class). To close
# that gap this script cross-checks Databricks' OWN task outcomes for THIS job run via
# WorkspaceClient.get_run, pulls each failed task's real error with get_run_output, and
#   (a) feeds them into pipeline_log_finalize so the audit row reads 'failed', and
#   (b) re-raises so finalize itself becomes a failed leaf -> job result_state = FAILED
#       -> run_job_task propagates red to the full_* wrapper.
# finalize stays run_if: ALL_DONE, so it always runs; the audit row is committed BEFORE
# the raise, so it closes honestly even though the task then fails.
#
# Parameters: argv[1]=shared_lib_path, argv[2]=catalog, argv[3]=this job run's id.
# -------------------------------------------------------------------------------
import re
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunResultState

# All three REQUIRED — no default catalog that could mis-route audit writes, and the
# job-run id is needed to look up this run's task outcomes.
if len(sys.argv) < 4:
    raise RuntimeError(
        "Expected sys.argv[1]=shared_lib_path, sys.argv[2]=catalog, sys.argv[3]=job.run_id. "
        "Set all three in the job YAML under finalize's spark_python_task.parameters."
    )
sys.path.insert(0, sys.argv[1])
catalog      = sys.argv[2]
job_run_id   = int(sys.argv[3])
audit_schema = f"{catalog}.audit"

from pipeline_logging import pipeline_log_finalize

# init_pipeline_run_log.py set this via dbutils.jobs.taskValues.set(key="pipeline_run_id").
PIPELINE_RUN_ID = dbutils.jobs.taskValues.get(
    taskKey="init_pipeline_log",
    key="pipeline_run_id",
)

# Databricks embeds terminal color codes in error / error_trace; strip them for the audit row.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# Terminal task states that count as a REAL failure for this run. A task that TIMED OUT or was
# CANCELED never reaches our StepLog, so keying on FAILED alone would re-open the masking gap for
# those. Deliberately EXCLUDES: SUCCESS / EXCLUDED (not failures); UPSTREAM_FAILED /
# UPSTREAM_CANCELED (derivative — the root FAILED task is caught directly); DISABLED.
FAILURE_STATES = {
    RunResultState.FAILED,
    RunResultState.TIMEDOUT,
    RunResultState.CANCELED,
    RunResultState.MAXIMUM_CONCURRENT_RUNS_REACHED,
}

# Cross-check Databricks' OWN task outcomes for this run (finalize is run_if: ALL_DONE, so by the
# time it runs every sibling has reached a terminal state). BEST-EFFORT: the whole block is guarded
# so a transient Jobs-API failure DEGRADES to an audit-table-only finalize rather than (a) crashing
# before the pipeline_log row is closed, or (b) false-failing an otherwise-successful run. On an API
# outage we lose only the pre-logging-failure catch; post-logging failures still close via the
# pipeline_step_log scan in pipeline_log_finalize, exactly as before this feature existed.
databricks_failures = []
try:
    workspace = WorkspaceClient()
    run = workspace.jobs.get_run(run_id=job_run_id)

    # run.tasks holds EVERY attempt — serverless auto-retries a failed task, so a healed task
    # appears twice (attempt 0 FAILED, attempt 1 SUCCESS). Keep only the LATEST attempt per
    # task_key, so a transient that the retry healed does not fail the job.
    latest_attempt = {}
    for task in run.tasks or []:
        if task.task_key == "finalize_pipeline_log":   # finalize itself is still RUNNING
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
        except Exception as output_error:   # one unreadable task output must not drop the failure
            error = f"(error detail unavailable: {output_error})"
        # Prefix the terminal state so the audit row distinguishes a timeout from a crash.
        databricks_failures.append(
            {"task_key": task.task_key, "error": f"[{task.state.result_state.value}] {error}"}
        )
except Exception as cross_check_error:
    # Degrade, do NOT crash — pipeline_log_finalize below still closes the row off the audit table.
    print(
        f"WARNING: Databricks task-outcome cross-check failed ({cross_check_error}); "
        f"finalizing from pipeline_step_log only."
    )

print(f"databricks_failures detected: {len(databricks_failures)} -> {databricks_failures}")

# Closes the pipeline_log row: status='failed' if step-log failures OR databricks_failures.
pipeline_log_finalize(spark, audit_schema, PIPELINE_RUN_ID, databricks_failures)
print(f"pipeline_log closed: run_id={PIPELINE_RUN_ID} catalog={catalog}")

# If Databricks saw any task fail, make finalize the failed leaf so the JOB reports FAILED
# (not SUCCESS_WITH_FAILURES). Runs AFTER the audit row is committed above.
if databricks_failures:
    failed_keys = ", ".join(failure["task_key"] for failure in databricks_failures)
    raise RuntimeError(
        f"finalize: {len(databricks_failures)} Databricks task(s) failed this run "
        f"(job_run_id={job_run_id}); failing finalize so the job reports FAILED. "
        f"Failed tasks: {failed_keys}."
    )
