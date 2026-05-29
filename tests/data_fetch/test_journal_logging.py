"""WS-D — download_log_insert / download_log_last_sha256 + DDL↔schema agreement.

No real SparkSession: a FakeSpark captures the write / sql surface. The DDL test asserts
AUDIT_DDL.create_download_log stays aligned with pipeline_logging._DOWNLOAD_LOG_SCHEMA
(the CLAUDE.md §11.1 load-bearing check).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pipeline_logging as pl
from pipeline_logging import _DOWNLOAD_LOG_SCHEMA, download_log_insert, download_log_last_sha256

from fakes import FakeSpark


def _ts(second: int) -> datetime:
    return datetime(2026, 5, 29, 10, 0, second, tzinfo=timezone.utc)


def _kwargs(**over):
    base = dict(
        download_id="d1", pipeline_run_id="r1", step_log_id="s1", source_system="zillow",
        source_url="https://h/z.csv", landed_file_path="/Volumes/c/raw/zillow/z.csv",
        status="succeeded", http_status_code=200, bytes_downloaded=123, file_sha256="abc",
        download_attempts=1, download_started_ts=_ts(0), download_ended_ts=_ts(5),
        error_message=None,
    )
    base.update(over)
    return base


# -- download_log_insert -----------------------------------------------------

def test_insert_appends_one_delta_row_to_named_table():
    spark = FakeSpark()
    result = download_log_insert(spark, "c.audit", **_kwargs())
    assert result["status"] == "succeeded"
    assert len(spark.writes) == 1
    w = spark.writes[0]
    assert w["table"] == "c.audit.download_log"
    assert w["format"] == "delta" and w["mode"] == "append"
    assert w["schema"] is _DOWNLOAD_LOG_SCHEMA
    assert len(w["data"]) == 1 and len(w["data"][0]) == len(_DOWNLOAD_LOG_SCHEMA.fields)


def test_insert_row_values_align_with_schema_order():
    spark = FakeSpark()
    download_log_insert(spark, "c.audit", **_kwargs())
    row = spark.writes[0]["data"][0]
    by_name = {f.name: i for i, f in enumerate(_DOWNLOAD_LOG_SCHEMA.fields)}
    assert row[by_name["download_id"]] == "d1"
    assert row[by_name["status"]] == "succeeded"
    assert row[by_name["bytes_downloaded"]] == 123
    assert row[by_name["http_status_code"]] == 200
    assert row[by_name["source_url"]] == "https://h/z.csv"


def test_insert_derives_duration_seconds():
    spark = FakeSpark()
    download_log_insert(spark, "c.audit", **_kwargs(download_started_ts=_ts(0), download_ended_ts=_ts(5)))
    row = spark.writes[0]["data"][0]
    dur_idx = [f.name for f in _DOWNLOAD_LOG_SCHEMA.fields].index("duration_seconds")
    assert row[dur_idx] == 5.0


def test_insert_duration_none_when_ended_missing():
    spark = FakeSpark()
    download_log_insert(spark, "c.audit", **_kwargs(download_ended_ts=None))
    row = spark.writes[0]["data"][0]
    fields = [f.name for f in _DOWNLOAD_LOG_SCHEMA.fields]
    assert row[fields.index("duration_seconds")] is None
    assert row[fields.index("download_ended_ts")] is None


def test_insert_normalizes_naive_timestamps_without_error():
    spark = FakeSpark()
    naive_start = datetime(2026, 5, 29, 10, 0, 0)        # offset-naive (as Spark reads return)
    naive_end = datetime(2026, 5, 29, 10, 0, 7)
    result = download_log_insert(spark, "c.audit",
                                 **_kwargs(download_started_ts=naive_start, download_ended_ts=naive_end))
    assert result["status"] == "succeeded"
    row = spark.writes[0]["data"][0]
    fields = [f.name for f in _DOWNLOAD_LOG_SCHEMA.fields]
    assert row[fields.index("duration_seconds")] == 7.0
    assert row[fields.index("download_started_ts")].tzinfo is timezone.utc   # normalized to aware


def test_insert_swallows_write_failure_and_returns_failed():
    spark = FakeSpark(fail_on_write=True)
    result = download_log_insert(spark, "c.audit", **_kwargs())   # must NOT raise
    assert result["status"] == "failed"
    assert "RuntimeError" in result["error_message"]


# -- download_log_last_sha256 ------------------------------------------------

def test_last_sha256_returns_latest_value_and_filters_correctly():
    spark = FakeSpark(sql_results=[[{"file_sha256": "deadbeef"}]])
    out = download_log_last_sha256(spark, "c.audit", "https://h/z.csv")
    assert out == "deadbeef"
    call = spark.sql_calls[0]
    assert call["args"] == {"source_url": "https://h/z.csv", "succeeded": "succeeded"}
    q = " ".join(call["query"].split())
    assert "status = :succeeded" in q
    assert "ORDER BY download_started_ts DESC" in q
    assert "LIMIT 1" in q


def test_last_sha256_none_when_no_rows():
    spark = FakeSpark(sql_results=[[]])
    assert download_log_last_sha256(spark, "c.audit", "u") is None


def test_last_sha256_swallows_error_returns_none():
    spark = FakeSpark(fail_on_sql=True)
    assert download_log_last_sha256(spark, "c.audit", "u") is None


# -- DDL ↔ insert-schema agreement (CLAUDE.md §11.1) -------------------------

def test_download_log_ddl_matches_insert_schema(monkeypatch):
    import AUDIT_DDL
    # _run_ddl lives in catalog_setup and is in scope only when the setup notebook runs;
    # inject a capturing stub so we can inspect the emitted DDL statement standalone.
    monkeypatch.setattr(AUDIT_DDL, "_run_ddl", lambda spark, statements: statements, raising=False)

    statements = AUDIT_DDL.create_download_log(spark=None, audit_schema="cat.audit")
    table, sql = statements[0]
    assert table == "cat.audit.download_log"

    body = sql[sql.index("(") + 1: sql.rindex(")")]
    ddl_type = {"StringType": "STRING", "IntegerType": "INT", "LongType": "BIGINT",
                "DoubleType": "DOUBLE", "TimestampType": "TIMESTAMP"}
    last_pos = -1
    for field in _DOWNLOAD_LOG_SCHEMA.fields:
        typ = ddl_type[type(field.dataType).__name__]
        m = re.search(rf"\b{field.name}\s+{typ}\b", body)
        assert m, f"{field.name} {typ} missing from DDL"
        assert m.start() > last_pos, f"{field.name} out of order vs schema"
        last_pos = m.start()
        not_null = re.search(rf"\b{field.name}\s+{typ}\s+NOT NULL", body) is not None
        assert not_null == (not field.nullable), f"{field.name} NOT NULL disagreement"
