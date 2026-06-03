"""Shared audit-logging helpers for the marketpulse ELT pipeline.

Imported by `libs/notebook_init.ipynb` (after it resolves `shared_lib_path` and
prepends it to `sys.path`) and by the `spark_python_task` scripts
`init_pipeline_run_log.py` / `finalize_pipeline_run_log.py` — which run OUTSIDE
notebook_init and so import `STATUS_*` and the run-tier functions directly.

Public surface
--------------
- `STATUS_*`                         — status vocabulary (SINGLE source of truth; notebook_init re-exports)
- `pipeline_log_upsert`              — run-level audit row (upsert; MAY RAISE)
- `pipeline_log_finalize`            — close a run by scanning the step log (MAY RAISE)
- `pipeline_step_log_upsert`         — notebook-level audit row (upsert; MAY RAISE)
- `StepLog`                          — recorder wrapping the two step_log upserts (open/close)
- `ingestion_log_insert`             — file-level audit (insert-only; SWALLOW -> dict)
- `transform_detail_log_insert`      — table-level audit (insert-only; SWALLOW -> dict)
- `download_log_insert` / `download_log_last_sha256` — data-acquisition audit (insert-only)

Conventions (project CLAUDE.md §12): no module-level side effects; `spark`/`dbutils`
are parameters, never globals; `audit_schema` is an explicit parameter on every
function. Upserts use `spark.sql` MERGE (NOT the `delta.tables` Python API) so the
module imports cleanly without `delta-spark` for local unit tests; insert-only writes
use `createDataFrame(...).write.append`. All audit PKs are application-generated UUID
strings — no `GENERATED ALWAYS AS IDENTITY` (it conflicted across MERGE/re-run paths).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from pipeline_utils import Utils

# ---------------------------------------------------------------------------
# Status vocabulary — SINGLE source of truth. notebook_init re-exports these so
# notebooks see the bare names; the spark_python scripts import them directly.
# (data_fetch/constants.py keeps its own copy by design — the package is
# standalone; a drift test asserts the two agree.)
# ---------------------------------------------------------------------------
STATUS_RUNNING   = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED    = "failed"
STATUS_NO_FILES  = "no_files"
STATUS_SKIPPED   = "skipped"


# ---------------------------------------------------------------------------
# Schemas — column ORDER and TYPES mirror ddl/audit_ddl.py exactly
# (CLAUDE.md §11.1 load-bearing check). BIGINT↔LongType, INT↔IntegerType,
# DOUBLE↔DoubleType, BOOLEAN↔BooleanType, TIMESTAMP↔TimestampType.
# ---------------------------------------------------------------------------
_PIPELINE_LOG_SCHEMA = StructType([
    StructField("pipeline_run_id",   StringType(),    False),
    StructField("pipeline_name",     StringType(),    False),
    StructField("status",            StringType(),    False),
    StructField("started_timestamp", TimestampType(), False),
    StructField("ended_timestamp",   TimestampType(), True),
    StructField("duration_seconds",  DoubleType(),    True),
    StructField("error_message",     StringType(),    True),
])

_STEP_LOG_SCHEMA = StructType([
    StructField("step_log_id",       StringType(),    False),
    StructField("pipeline_run_id",   StringType(),    False),
    StructField("step_sequence",     IntegerType(),   False),
    StructField("notebook_folder",   StringType(),    False),
    StructField("notebook_name",     StringType(),    False),
    StructField("layer",             StringType(),    True),
    StructField("target_table",      StringType(),    True),
    StructField("status",            StringType(),    False),
    StructField("rows_read",         LongType(),      True),
    StructField("rows_written",      LongType(),      True),
    StructField("started_timestamp", TimestampType(), False),
    StructField("ended_timestamp",   TimestampType(), True),
    StructField("duration_seconds",  DoubleType(),    True),
    StructField("error_message",     StringType(),    True),
])

_TRANSFORM_DETAIL_SCHEMA = StructType([
    StructField("transform_id",             StringType(),    False),
    StructField("pipeline_run_id",          StringType(),    False),
    StructField("step_log_id",              StringType(),    False),
    StructField("source_table",             StringType(),    False),
    StructField("target_table",             StringType(),    False),
    StructField("status",                   StringType(),    False),
    StructField("rows_read",                LongType(),      True),
    StructField("rows_written",             LongType(),      True),
    StructField("rows_inserted",            LongType(),      True),
    StructField("rows_updated",             LongType(),      True),
    StructField("rows_expired",             LongType(),      True),
    StructField("rows_rejected",            LongType(),      True),
    StructField("rows_deduplicated",        LongType(),      True),
    StructField("validation_rules_applied", StringType(),    True),
    StructField("schema_drift_detected",    BooleanType(),   True),
    StructField("schema_drift_detail",      StringType(),    True),
    StructField("error_message",            StringType(),    True),
    StructField("started_timestamp",        TimestampType(), False),
    StructField("ended_timestamp",          TimestampType(), True),
    StructField("duration_seconds",         DoubleType(),    True),
])

# Column order/types MUST match {audit_schema}.download_log in ddl/audit_ddl.py.
_DOWNLOAD_LOG_SCHEMA = StructType([
    StructField("download_id",         StringType(),    False),
    StructField("pipeline_run_id",     StringType(),    False),
    StructField("step_log_id",         StringType(),    False),
    StructField("source_system",       StringType(),    False),
    StructField("source_url",          StringType(),    False),
    StructField("landed_file_path",    StringType(),    False),
    StructField("status",              StringType(),    False),
    StructField("http_status_code",    IntegerType(),   True),
    StructField("bytes_downloaded",    LongType(),      True),
    StructField("file_sha256",         StringType(),    True),
    StructField("download_attempts",   IntegerType(),   True),
    StructField("download_started_ts", TimestampType(), False),
    StructField("download_ended_ts",   TimestampType(), True),
    StructField("duration_seconds",    DoubleType(),    True),
    StructField("error_message",       StringType(),    True),
])


def _duration_seconds(started: datetime | None, ended: datetime | None) -> float | None:
    # normalize_aware_datetime handles the offset-naive/aware mix (Spark TIMESTAMPs read
    # back naive; datetime.now(timezone.utc) is aware) so the subtraction never raises.
    if started is None or ended is None:
        return None
    return (Utils.normalize_aware_datetime(ended)
            - Utils.normalize_aware_datetime(started)).total_seconds()


def _merge_one_row(spark: Any, table: str, schema: StructType, values: tuple,
                   key_cols: list[str], view_name: str) -> None:
    """Upsert one row into a Delta table via SQL MERGE on `key_cols`.

    Uses `spark.sql("MERGE …")` over a temp view rather than the `delta.tables`
    Python API so the module imports without `delta-spark` (local unit tests).
    """
    df = spark.createDataFrame([values], schema=schema)
    df.createOrReplaceTempView(view_name)
    on = " AND ".join(f"t.{key_col} = s.{key_col}" for key_col in key_cols)
    spark.sql(f"""
        MERGE INTO {table} AS t
        USING {view_name} AS s
        ON {on}
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)


# ---------------------------------------------------------------------------
# Run tier — pipeline_log. Upsert; MAY RAISE (called at controlled points).
# ---------------------------------------------------------------------------
def pipeline_log_upsert(
    spark: Any,
    audit_schema: str,
    pipeline_run_id: str,
    pipeline_name: str,
    status: str,
    started_timestamp: datetime,
    ended_timestamp: datetime | None = None,
    error_message: str | None = None,
) -> None:
    """Upsert one row into `{audit_schema}.pipeline_log` (MERGE on pipeline_run_id)."""
    started = Utils.normalize_aware_datetime(started_timestamp)
    ended   = Utils.normalize_aware_datetime(ended_timestamp)
    values = (
        pipeline_run_id, pipeline_name, status, started, ended,
        _duration_seconds(started, ended), error_message,
    )
    _merge_one_row(spark, f"{audit_schema}.pipeline_log", _PIPELINE_LOG_SCHEMA,
                   values, ["pipeline_run_id"], "_pipeline_log_src")


def pipeline_log_finalize(
    spark: Any,
    audit_schema: str,
    pipeline_run_id: str,
    databricks_failures: list[dict[str, str]] | None = None,
) -> None:
    """Close out a pipeline_log row at end of run. MAY RAISE.

    Reads pipeline_name + started_timestamp from the existing row, then derives the
    final status from TWO sources:
      1. pipeline_step_log rows for this run with status='failed' (our audit trail), and
      2. databricks_failures — failed sibling tasks observed directly from Databricks'
         task outcomes (WorkspaceClient.get_run), passed in by the caller.

    Source 2 catches failures that never reached our logging — e.g. an error before a
    notebook opens its pipeline_step_log row. The audit table is blind to those, so a
    status derived from it alone can read 'succeeded' for a run that really failed.
    Each databricks_failures entry is a dict {"task_key": str, "error": str}.
    """
    databricks_failures = databricks_failures or []

    header = spark.sql(f"""
        SELECT pipeline_name, started_timestamp
        FROM {audit_schema}.pipeline_log
        WHERE pipeline_run_id = '{pipeline_run_id}'
    """).collect()

    if not header:
        raise ValueError(
            f"No pipeline_log row exists for pipeline_run_id='{pipeline_run_id}'. "
            f"Call pipeline_log_upsert at run start before pipeline_log_finalize."
        )

    pipeline_name     = header[0]["pipeline_name"]
    started_timestamp = header[0]["started_timestamp"]
    ended_timestamp   = datetime.now(timezone.utc)

    failed = spark.sql(f"""
        SELECT
            COUNT(*)                    AS failed_count,
            COLLECT_LIST(notebook_name) AS failed_notebooks
        FROM {audit_schema}.pipeline_step_log
        WHERE pipeline_run_id = '{pipeline_run_id}'
          AND status = '{STATUS_FAILED}'
    """).collect()[0]

    logged_failures = failed["failed_count"] > 0

    if logged_failures or databricks_failures:
        status = STATUS_FAILED
        # Aggregate both sources into one message so the audit row records what failed
        # whether or not the step ever logged a row.
        parts = []
        if logged_failures:
            parts.append(
                f"{failed['failed_count']} logged step(s) failed: "
                f"{', '.join(failed['failed_notebooks'])}."
            )
        if databricks_failures:
            detail = "; ".join(
                f"{failure['task_key']}: {failure['error']}" for failure in databricks_failures
            )
            parts.append(f"{len(databricks_failures)} Databricks task(s) failed: {detail}")
        parts.append(f"See {audit_schema}.pipeline_step_log and the run's task matrix.")
        error_message = " ".join(parts)
    else:
        status = STATUS_SUCCEEDED
        error_message = None

    pipeline_log_upsert(
        spark, audit_schema, pipeline_run_id, pipeline_name, status,
        started_timestamp, ended_timestamp, error_message,
    )


# ---------------------------------------------------------------------------
# Notebook tier — pipeline_step_log. Upsert; MAY RAISE.
# ---------------------------------------------------------------------------
def pipeline_step_log_upsert(
    spark: Any,
    audit_schema: str,
    step_log_id: str,
    pipeline_run_id: str,
    step_sequence: int,
    notebook_folder: str,
    notebook_name: str,
    status: str,
    started_timestamp: datetime,
    layer: str | None = None,
    target_table: str | None = None,
    rows_read: int | None = None,
    rows_written: int | None = None,
    ended_timestamp: datetime | None = None,
    error_message: str | None = None,
) -> None:
    """Upsert one row into `{audit_schema}.pipeline_step_log` (MERGE on step_log_id).

    Called twice per notebook step (open RUNNING, then close SUCCEEDED/FAILED/NO_FILES)
    with the same `step_log_id`. Normally invoked via the `StepLog` recorder, not directly.
    """
    started = Utils.normalize_aware_datetime(started_timestamp)
    ended   = Utils.normalize_aware_datetime(ended_timestamp)
    values = (
        step_log_id, pipeline_run_id, step_sequence, notebook_folder, notebook_name,
        layer, target_table, status, rows_read, rows_written, started, ended,
        _duration_seconds(started, ended), error_message,
    )
    _merge_one_row(spark, f"{audit_schema}.pipeline_step_log", _STEP_LOG_SCHEMA,
                   values, ["step_log_id"], "_step_log_src")


class StepLog:
    """One pipeline_step_log row, opened on construction, closed explicitly.

    Holds `step_log_id` + mutable `rows_read` / `rows_written` so notebooks carry no
    loose status / ended_timestamp / error_message variables (removes the CLAUDE.md
    §11.4 footgun). `dbutils` is accepted for caller uniformity; it is never used as a
    module global. Canonical per-cell usage (design §7):

        step = StepLog(spark, AUDIT, dbutils, pipeline_run_id=PIPELINE_RUN_ID,
                       step_sequence=1, notebook_folder=nb["notebook_folder"],
                       notebook_name=nb["notebook_name"], layer="bronze",
                       target_table=TARGET_TABLE)
        try:
            ...
            step.rows_written = ...
            step.succeed()
        except Exception as e:
            step.fail(e); raise

    Any early `dbutils.notebook.exit()` is called OUTSIDE the try (set a flag
    inside, exit after) — the exit raises an ordinary exception that
    `except Exception` would swallow; there is no `dbutils.NotebookExit` class.
    See `.claude/project/gotchas.md`.
    """

    def __init__(self, spark: Any, audit_schema: str, dbutils: Any, *,
                 pipeline_run_id: str, step_sequence: int,
                 notebook_folder: str, notebook_name: str,
                 layer: str | None = None, target_table: str | None = None):
        self._spark = spark
        self._audit = audit_schema
        self.step_log_id  = str(uuid.uuid4())
        self._started     = datetime.now(timezone.utc)
        self.rows_read    = 0
        self.rows_written = 0
        self._common = dict(
            pipeline_run_id=pipeline_run_id, step_sequence=step_sequence,
            notebook_folder=notebook_folder, notebook_name=notebook_name,
            layer=layer, target_table=target_table,
        )
        pipeline_step_log_upsert(
            spark, audit_schema, self.step_log_id, status=STATUS_RUNNING,
            started_timestamp=self._started, **self._common,
        )  # OPEN: RUNNING row

    def _close(self, status: str, error_message: str | None = None) -> None:
        pipeline_step_log_upsert(
            self._spark, self._audit, self.step_log_id, status=status,
            started_timestamp=self._started, ended_timestamp=datetime.now(timezone.utc),
            rows_read=self.rows_read, rows_written=self.rows_written,
            error_message=error_message, **self._common,
        )

    def succeed(self) -> None:
        self._close(STATUS_SUCCEEDED)

    def no_files(self) -> None:
        self._close(STATUS_NO_FILES)

    def fail(self, exc: BaseException) -> None:
        err = Utils.capture_exception(exc)
        self._close(STATUS_FAILED,
                    error_message=f"{err['error_type']}: {err['error_message']}")


# ---------------------------------------------------------------------------
# Leaf tier — insert-only, immutable. SWALLOW logging failures and return a dict
# (CLAUDE.md §11.4/§12): a logging hiccup must never roll back a committed write.
# ---------------------------------------------------------------------------
def ingestion_log_insert(
    spark: Any,
    audit_schema: str,
    df_files: Any,
    pipeline_run_id: str,
    step_log_id: str,
    source_system: str,
    target_table: str,
    error_message: str | None = None,
    ingested_timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Append one row per file into `{audit_schema}.ingestion_log`.

    `df_files` is a DataFrame with a `source_file_path` column (one row per file).
    PK `ingestion_id` is generated per row with `uuid()`. Returns
    `{"status","error_message"}`; never raises.
    """
    try:
        if ingested_timestamp is None:
            ingested_timestamp = datetime.now(timezone.utc)
        ts = Utils.normalize_aware_datetime(ingested_timestamp)
        df = (
            df_files.select("source_file_path")
            .withColumn("ingestion_id",       F.expr("uuid()"))
            .withColumn("pipeline_run_id",    F.lit(pipeline_run_id))
            .withColumn("step_log_id",        F.lit(step_log_id))
            .withColumn("source_system",      F.lit(source_system))
            .withColumn("target_table",       F.lit(target_table))
            .withColumn("error_message",      F.lit(error_message))
            .withColumn("ingested_timestamp", F.lit(ts).cast("timestamp"))
            .select(
                "ingestion_id", "pipeline_run_id", "step_log_id", "source_system",
                "source_file_path", "target_table", "error_message", "ingested_timestamp",
            )
        )
        df.write.format("delta").mode("append").saveAsTable(f"{audit_schema}.ingestion_log")
        return {"status": STATUS_SUCCEEDED, "error_message": None}
    except Exception as e:  # outermost logging boundary — never propagate (CLAUDE.md §12)
        return {"status": STATUS_FAILED, "error_message": f"{type(e).__name__}: {e}"}


def transform_detail_log_insert(
    spark: Any,
    audit_schema: str,
    pipeline_run_id: str,
    step_log_id: str,
    source_table: str,
    target_table: str,
    status: str,
    started_timestamp: datetime,
    rows_read: int | None = None,
    rows_written: int | None = None,
    rows_inserted: int | None = None,
    rows_updated: int | None = None,
    rows_expired: int | None = None,
    rows_rejected: int | None = None,
    rows_deduplicated: int | None = None,
    validation_rules_applied: str | None = None,
    schema_drift_detected: bool | None = None,
    schema_drift_detail: str | None = None,
    error_message: str | None = None,
    ended_timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Append one immutable row into `{audit_schema}.transform_detail_log`.

    PK `transform_id` is auto-generated. Returns `{"status","error_message"}`; never raises.
    """
    try:
        started = Utils.normalize_aware_datetime(started_timestamp)
        ended   = Utils.normalize_aware_datetime(ended_timestamp)
        values = (
            str(uuid.uuid4()), pipeline_run_id, step_log_id, source_table, target_table,
            status, rows_read, rows_written, rows_inserted, rows_updated, rows_expired,
            rows_rejected, rows_deduplicated, validation_rules_applied,
            schema_drift_detected, schema_drift_detail, error_message,
            started, ended, _duration_seconds(started, ended),
        )
        df = spark.createDataFrame([values], schema=_TRANSFORM_DETAIL_SCHEMA)
        df.write.format("delta").mode("append").saveAsTable(f"{audit_schema}.transform_detail_log")
        return {"status": STATUS_SUCCEEDED, "error_message": None}
    except Exception as e:  # outermost logging boundary — never propagate (CLAUDE.md §12)
        return {"status": STATUS_FAILED, "error_message": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# download_log — the data-acquisition framework's audit table (design §9).
# Surfaced to the core as a DownloadJournal of two callables.
# ---------------------------------------------------------------------------
def download_log_insert(
    spark: Any,
    audit_schema: str,
    *,
    download_id: str,
    pipeline_run_id: str,
    step_log_id: str,
    source_system: str,
    source_url: str,
    landed_file_path: str,
    status: str,
    http_status_code: int | None = None,
    bytes_downloaded: int | None = None,
    file_sha256: str | None = None,
    download_attempts: int | None = None,
    download_started_ts: datetime | None = None,
    download_ended_ts: datetime | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Append one row to `{audit_schema}.download_log` (design §9).

    Bound by the entry as `partial(download_log_insert, spark, AUDIT)` and surfaced as
    DownloadJournal.record. Logging failures are SWALLOWED — returns
    `{"status","error_message"}` but does NOT raise (CLAUDE.md §11.4/§12).
    """
    try:
        row = (
            download_id, pipeline_run_id, step_log_id, source_system, source_url,
            landed_file_path, status, http_status_code, bytes_downloaded, file_sha256,
            download_attempts,
            Utils.normalize_aware_datetime(download_started_ts),
            Utils.normalize_aware_datetime(download_ended_ts),
            _duration_seconds(download_started_ts, download_ended_ts), error_message,
        )
        df = spark.createDataFrame([row], schema=_DOWNLOAD_LOG_SCHEMA)
        df.write.format("delta").mode("append").saveAsTable(f"{audit_schema}.download_log")
        return {"status": "succeeded", "error_message": None}
    except Exception as e:  # outermost logging boundary — never propagate (CLAUDE.md §12)
        return {"status": "failed", "error_message": f"{type(e).__name__}: {e}"}


def download_log_last_sha256(spark: Any, audit_schema: str, source_url: str) -> str | None:
    """Return the most recent successfully-landed `file_sha256` for `source_url`, or None.

    Drives the idempotent no-op (design §7.6). Returns None on ANY error (e.g. the table
    is absent on first run) so the run downloads rather than mis-skipping.
    """
    try:
        rows = spark.sql(
            f"""
            SELECT file_sha256
            FROM {audit_schema}.download_log
            WHERE source_url = :source_url
              AND status = :succeeded
              AND file_sha256 IS NOT NULL
            ORDER BY download_started_ts DESC
            LIMIT 1
            """,
            args={"source_url": source_url, "succeeded": STATUS_SUCCEEDED},
        ).collect()
    except Exception:  # logging/read boundary — a lookup failure must not break the run
        return None
    return rows[0]["file_sha256"] if rows else None
