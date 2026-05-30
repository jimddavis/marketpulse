# -------------------------------------------------------------------------------
# Finalize the pipeline_log row opened by init_pipeline_run_log.py. All logic lives
# in pipeline_logging.pipeline_log_finalize — this script bootstraps the import
# path, recovers the run_id from the init task's taskValue, and hands off.
#
# Wired into resources/job_download_sources.yml as the LAST task with
# run_if: ALL_DONE so it runs whether upstream succeeded, failed, or was skipped.
# -------------------------------------------------------------------------------
import sys

# sys.argv[1] = shared_lib_path, sys.argv[2] = catalog (see init_pipeline_run_log.py).
# Both REQUIRED — no default catalog that could mis-route audit writes.
if len(sys.argv) < 3:
    raise RuntimeError(
        "Expected sys.argv[1]=shared_lib_path and sys.argv[2]=catalog. Set both in "
        "job_download_sources.yml under spark_python_task.parameters."
    )
sys.path.insert(0, sys.argv[1])
catalog      = sys.argv[2]
audit_schema = f"{catalog}.audit"

from pipeline_logging import pipeline_log_finalize

# init_pipeline_run_log.py set this via dbutils.jobs.taskValues.set(key="pipeline_run_id").
PIPELINE_RUN_ID = dbutils.jobs.taskValues.get(
    taskKey="init_pipeline_log",
    key="pipeline_run_id",
)

pipeline_log_finalize(spark, audit_schema, PIPELINE_RUN_ID)
print(f"pipeline_log closed: run_id={PIPELINE_RUN_ID} catalog={catalog}")
