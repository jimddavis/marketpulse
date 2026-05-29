# -------------------------------------------------------------------------------
# A simple script that inserts a record into pipeline_run_log and sets a
# taskValue with the pipeline_run_id for all downstream tasks to consume.
# Wired into databricks.yml as the first spark_python_task of
# vinoworld_elt_pipeline.
# -------------------------------------------------------------------------------
import sys, uuid
from datetime import datetime, timezone

# shared_lib_path comes from sys.argv[1] (bundle spark_python_task.parameters
# → ${var.shared_lib_path}). catalog comes from sys.argv[2] (${var.catalog}).
# __file__ is NOT defined in a spark_python_task because Databricks invokes
# the script via exec(compile(...)); rely on the bundle to pass the path.
if len(sys.argv) < 2:
    raise RuntimeError(
        "Expected sys.argv[1]=shared_lib_path. Set in databricks.yml under "
        "spark_python_task.parameters when wiring this script into a job."
    )
sys.path.insert(0, sys.argv[1])
catalog = sys.argv[2] if len(sys.argv) > 2 else "vinoworld"

from pipeline_logging import pipeline_log_upsert, configure, STATUS_RUNNING
configure(f"{catalog}.audit")


PIPELINE_RUN_ID   = str(uuid.uuid4())
PIPELINE_START_TS = datetime.now(timezone.utc)
PIPELINE_NAME     = "vinoworld_elt_pipeline"
PIPELINE_STATUS   = STATUS_RUNNING
PIPELINE_END_TS   = None
ERROR_MESSAGE     = None

dbutils.jobs.taskValues.set(key="pipeline_run_id", value=PIPELINE_RUN_ID)

pipeline_log_upsert(spark, PIPELINE_RUN_ID, PIPELINE_NAME, PIPELINE_STATUS, PIPELINE_START_TS)
