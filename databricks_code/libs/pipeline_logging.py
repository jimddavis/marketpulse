"""Shared logging module — STUB.

Wraps writes to the project's audit schema. Implement when `setup/
catalog_ddl.ipynb` has declared the audit table DDL — at that point the
function bodies become unambiguous (one INSERT / MERGE per audit table).

Conventions enforced (project CLAUDE.md § 12):
- No module-level side effects.
- `spark` is a function parameter.
- All imports at top of file.
- These functions are called from inside notebook try/except blocks
  (CLAUDE.md § 11.4); they MAY raise on programming errors but SHOULD
  swallow non-fatal logging failures so a logging issue does not roll
  back a successful Bronze write.

Audit tables expected (see setup/catalog_ddl.ipynb when written):
- `{AUDIT}.pipeline_run_log`      — one row per orchestrator invocation
- `{AUDIT}.pipeline_step_log`     — one row per notebook execution
- `{AUDIT}.ingestion_log`         — one row per source-file ingest
- `{AUDIT}.transform_detail_log`  — one row per Silver/Gold transform
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from pipeline_utils import Utils

# Status literal used by download_log_last_sha256's filter. Must equal notebook_init
# STATUS_SUCCEEDED (the project's canonical "succeeded" value); centralized here so the
# WHERE clause carries no bare literal (CLAUDE.md §6).
_STATUS_SUCCEEDED = "succeeded"

# Column order and types MUST match {audit_schema}.download_log in AUDIT_DDL.py — the
# CLAUDE.md §11.1 load-bearing check (STRING↔StringType, INT↔IntegerType,
# BIGINT↔LongType, DOUBLE↔DoubleType, TIMESTAMP↔TimestampType). nullable=False mirrors
# the DDL's NOT NULL columns. test_journal_logging asserts the two stay in agreement.
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


def pipeline_step_log_upsert(
    spark: Any,
    step_log_id: str,
    pipeline_run_id: int,
    step_sequence: int,
    notebook_folder: str,
    notebook_name: str,
    status: str,
    started_timestamp: datetime,
    layer: str,
    target_table: str,
    rows_read: int | None = None,
    rows_written: int | None = None,
    ended_timestamp: datetime | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Upsert one row in `{AUDIT}.pipeline_step_log`.

    Called twice per notebook execution:
    1. At cell 3 with status=STATUS_RUNNING, no end/rows yet.
    2. At cell 6 (success) or in the `except` handler (failure) with
       final status, ended_timestamp, rows_read, rows_written.

    `step_log_id` is the natural key — same id on both calls performs
    an UPDATE on the second call (MERGE on step_log_id).

    Returns
    -------
    dict with 'status' ('succeeded' | 'failed') and optional
    'error_message'.

    Pre-declared variable rule (CLAUDE.md § 11.4):
    The variables passed here must be declared OUTSIDE the calling
    notebook's try/except block, because the except handler also calls
    this function and would NameError if the try block raised on its
    first line.
    """
    raise NotImplementedError("Implement after setup/catalog_ddl.ipynb declares pipeline_step_log")


def ingestion_log_insert(
    spark: Any,
    pipeline_run_id: int,
    step_log_id: str,
    source_file_path: str,
    target_table: str,
    rows_inserted: int,
    rows_updated: int = 0,
    status: str = "succeeded",
    error_message: str | None = None,
) -> dict[str, Any]:
    """Insert one row per source file into `{AUDIT}.ingestion_log`.

    Use the `INSERT INTO ... SELECT` pattern (not createDataFrame + write)
    so any `GENERATED ALWAYS AS IDENTITY` PK is auto-assigned.

    Returns
    -------
    dict with 'status' and optional 'error_message'. Logging failures
    return {'status': 'failed', ...} but DO NOT raise — the caller has
    already committed the Bronze write and a logging hiccup should not
    roll that back.
    """
    raise NotImplementedError("Implement after setup/catalog_ddl.ipynb declares ingestion_log")


def transform_detail_log_insert(
    spark: Any,
    pipeline_run_id: int,
    step_log_id: str,
    transform_source_table: str,
    transform_target_table: str,
    rows_inserted: int,
    rows_expired: int,
    transform_started: datetime,
    transform_ended: datetime,
    status: str = "succeeded",
    error_message: str | None = None,
) -> dict[str, Any]:
    """Insert one row per Silver/Gold transform into `{AUDIT}.transform_detail_log`.

    Pre-declared variable rule (CLAUDE.md § 11.4):
    `transform_source_table`, `transform_target_table`, `transform_started`,
    `rows_inserted`, `rows_expired` MUST be declared above the calling
    try/except so the except handler has them bound even if the first
    SQL statement in the try block raised.
    """
    raise NotImplementedError("Implement after setup/catalog_ddl.ipynb declares transform_detail_log")


# ---------------------------------------------------------------------------
# download_log — the data-acquisition framework's audit table (WS-D).
# DDL: AUDIT_DDL.create_download_log. Surfaced to the core as a DownloadJournal
# of two callables (design §9): the entry binds these via functools.partial.
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
    DownloadJournal.record, called `record(**asdict(DownloadLogRow))` — so these keyword
    names match DownloadLogRow's fields exactly. `duration_seconds` is NOT a parameter;
    it is derived here from the two timestamps.

    Logging failures are SWALLOWED — returns {'status':'failed', ...} but does NOT raise
    (CLAUDE.md §11.4/§12): a logging hiccup must never roll back a completed download.
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

    Drives the idempotent no-op (design §7.6): the runner skips the promote when the new
    digest equals this. Returns None on ANY error (e.g. the table is absent on first run)
    so the run downloads rather than mis-skipping. Parameterized SQL keeps `source_url`
    out of the query text (CONFIDENCE: Projected — `spark.sql(..., args=)` named markers
    require a recent Spark; verify at WS-I).
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
            args={"source_url": source_url, "succeeded": _STATUS_SUCCEEDED},
        ).collect()
    except Exception:  # logging/read boundary — a lookup failure must not break the run
        return None
    return rows[0]["file_sha256"] if rows else None


def _duration_seconds(started: datetime | None, ended: datetime | None) -> float | None:
    # normalize_aware_datetime handles the offset-naive/aware mix (Spark TIMESTAMPs read
    # back naive; datetime.now(timezone.utc) is aware) so the subtraction never raises.
    if started is None or ended is None:
        return None
    return (Utils.normalize_aware_datetime(ended)
            - Utils.normalize_aware_datetime(started)).total_seconds()
