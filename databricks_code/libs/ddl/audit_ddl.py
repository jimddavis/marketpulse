# ddl/audit_ddl.py
# Audit-schema table DDL. create_audit_tables creates ALL audit tables (idempotent,
# CREATE IF NOT EXISTS) so the logging functions in pipeline_logging have their targets
# even before a table is first written. Standalone — imports the shared _run_ddl from
# ddl._utils (no reliance on it being in scope, the prior coupling).
#
# download_log is a peer of ingestion_log for the data-acquisition framework (design §9).
# It is SEPARATE so ingestion_log's NOT NULL invariants stay honest; the download→ingest
# gap is a join on download_log.landed_file_path = ingestion_log.source_file_path.
# Its column order/types are mirrored by pipeline_logging._DOWNLOAD_LOG_SCHEMA.

from ddl._utils import _run_ddl


def create_audit_tables(spark, audit_schema):
    statements = [
        (f"{audit_schema}.pipeline_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.pipeline_log (
                pipeline_run_id      STRING      NOT NULL,
                pipeline_name        STRING      NOT NULL,
                status               STRING      NOT NULL,
                started_timestamp    TIMESTAMP   NOT NULL,
                ended_timestamp      TIMESTAMP,
                duration_seconds     DOUBLE,
                error_message        STRING
            )
        """),
        (f"{audit_schema}.pipeline_step_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.pipeline_step_log (
                step_log_id          STRING      NOT NULL,
                pipeline_run_id      STRING      NOT NULL,
                step_sequence        INT         NOT NULL,
                notebook_folder      STRING      NOT NULL,
                notebook_name        STRING      NOT NULL,
                layer                STRING,
                target_table         STRING,
                status               STRING      NOT NULL,
                rows_read            BIGINT,
                rows_written         BIGINT,
                started_timestamp    TIMESTAMP   NOT NULL,
                ended_timestamp      TIMESTAMP,
                duration_seconds     DOUBLE,
                error_message        STRING
            )
        """),
        (f"{audit_schema}.transform_detail_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.transform_detail_log (
                transform_id                STRING      NOT NULL,
                pipeline_run_id             STRING      NOT NULL,
                step_log_id                 STRING      NOT NULL,
                source_table                STRING      NOT NULL,
                target_table                STRING      NOT NULL,
                status                      STRING      NOT NULL,
                rows_read                   BIGINT,
                rows_written                BIGINT,
                rows_inserted               BIGINT,
                rows_updated                BIGINT,
                rows_expired                BIGINT,
                rows_rejected               BIGINT,
                rows_deduplicated           BIGINT,
                validation_rules_applied    STRING,
                schema_drift_detected       BOOLEAN,
                schema_drift_detail         STRING,
                error_message               STRING,
                started_timestamp           TIMESTAMP   NOT NULL,
                ended_timestamp             TIMESTAMP,
                duration_seconds            DOUBLE
            )
        """),
        (f"{audit_schema}.ingestion_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.ingestion_log (
                ingestion_id         STRING      NOT NULL,
                pipeline_run_id      STRING      NOT NULL,
                step_log_id          STRING      NOT NULL,
                source_system        STRING      NOT NULL,
                source_file_path     STRING      NOT NULL,
                target_table         STRING      NOT NULL,
                error_message        STRING,
                ingested_timestamp   TIMESTAMP   NOT NULL
            )
        """),
        (f"{audit_schema}.download_log", f"""
            CREATE TABLE IF NOT EXISTS {audit_schema}.download_log (
                download_id          STRING      NOT NULL,
                pipeline_run_id      STRING      NOT NULL,
                step_log_id          STRING      NOT NULL,
                source_system        STRING      NOT NULL,
                source_url           STRING      NOT NULL,
                landed_file_path     STRING      NOT NULL,
                status               STRING      NOT NULL,
                http_status_code     INT,
                bytes_downloaded     BIGINT,
                file_sha256          STRING,
                download_attempts    INT,
                download_started_ts  TIMESTAMP   NOT NULL,
                download_ended_ts    TIMESTAMP,
                duration_seconds     DOUBLE,
                error_message        STRING
            )
        """),
    ]
    return _run_ddl(spark, statements)
