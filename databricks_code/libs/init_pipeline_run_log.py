# -------------------------------------------------------------------------------
# Inserts the opening row into {catalog}.audit.pipeline_log (STATUS_RUNNING) and
# sets a taskValue with the pipeline_run_id for all downstream tasks to consume.
# Wired into resources/job_download_sources.yml as the first spark_python_task
# (task_key "init_pipeline_log"); finalize_pipeline_run_log.py closes the row.
# -------------------------------------------------------------------------------
import sys, uuid
from datetime import datetime, timezone

# sys.argv[1] = shared_lib_path, sys.argv[2] = catalog, sys.argv[3] = pipeline_name
# (bundle spark_python_task.parameters → ${var.shared_lib_path}, ${var.catalog},
# {{job.name}}). __file__ is NOT defined in a spark_python_task (Databricks runs it
# via exec(compile(...))); rely on the bundle to pass these. argv[1]/[2] are REQUIRED
# — no default catalog, which could silently route audit writes at the wrong catalog.
# argv[3] is OPTIONAL with a fallback, so a job that omits it still satisfies the
# pipeline_log.pipeline_name NOT NULL column.
if len(sys.argv) < 3:
    raise RuntimeError(
        "Expected sys.argv[1]=shared_lib_path and sys.argv[2]=catalog. Set both in "
        "the job YAML under the init task's spark_python_task.parameters."
    )
sys.path.insert(0, sys.argv[1])
catalog      = sys.argv[2]
audit_schema = f"{catalog}.audit"

from pipeline_logging import pipeline_log_upsert, STATUS_RUNNING

PIPELINE_RUN_ID   = str(uuid.uuid4())
PIPELINE_START_TS = datetime.now(timezone.utc)
# {{job.name}} passed by every job → records WHICH job ran (e.g. "Marketpulse bronze_load
# [dev]"). Fallback keeps the NOT NULL pipeline_name column populated if a caller omits argv[3].
PIPELINE_NAME     = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].strip() else "marketpulse_pipeline"

dbutils.jobs.taskValues.set(key="pipeline_run_id", value=PIPELINE_RUN_ID)

pipeline_log_upsert(
    spark, audit_schema, PIPELINE_RUN_ID, PIPELINE_NAME, STATUS_RUNNING, PIPELINE_START_TS
)
print(f"pipeline_log opened: name='{PIPELINE_NAME}' run_id={PIPELINE_RUN_ID} catalog={catalog}")
