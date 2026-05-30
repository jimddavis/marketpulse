# -------------------------------------------------------------------------------
# Inserts the opening row into {catalog}.audit.pipeline_log (STATUS_RUNNING) and
# sets a taskValue with the pipeline_run_id for all downstream tasks to consume.
# Wired into resources/job_download_sources.yml as the first spark_python_task
# (task_key "init_pipeline_log"); finalize_pipeline_run_log.py closes the row.
# -------------------------------------------------------------------------------
import sys, uuid
from datetime import datetime, timezone

# sys.argv[1] = shared_lib_path, sys.argv[2] = catalog (bundle spark_python_task
# .parameters → ${var.shared_lib_path}, ${var.catalog}). __file__ is NOT defined
# in a spark_python_task (Databricks runs it via exec(compile(...))); rely on the
# bundle to pass these. Both are REQUIRED — no default catalog, which could
# silently route audit writes at the wrong catalog.
if len(sys.argv) < 3:
    raise RuntimeError(
        "Expected sys.argv[1]=shared_lib_path and sys.argv[2]=catalog. Set both in "
        "job_download_sources.yml under spark_python_task.parameters."
    )
sys.path.insert(0, sys.argv[1])
catalog      = sys.argv[2]
audit_schema = f"{catalog}.audit"

from pipeline_logging import pipeline_log_upsert, STATUS_RUNNING

PIPELINE_RUN_ID   = str(uuid.uuid4())
PIPELINE_START_TS = datetime.now(timezone.utc)
PIPELINE_NAME     = "marketpulse_pipeline"

dbutils.jobs.taskValues.set(key="pipeline_run_id", value=PIPELINE_RUN_ID)

pipeline_log_upsert(
    spark, audit_schema, PIPELINE_RUN_ID, PIPELINE_NAME, STATUS_RUNNING, PIPELINE_START_TS
)
print(f"pipeline_log opened: run_id={PIPELINE_RUN_ID} catalog={catalog}")
