# Canonical helpers

All helpers live under `databricks_code/libs/`. **If a helper exists, use
it.** Do not write inline equivalents of logging, hash generation, exception
capture, or notebook-context discovery.

## `libs/notebook_init.ipynb`

`%run "../../libs/notebook_init"` is the first executable cell of **every**
pipeline notebook (use `"../libs/notebook_init"` from root-level notebooks).
It injects into the notebook's namespace:

- **Constants**: `CATALOG`, `BRONZE`, `SILVER`, `GOLD`, `AUDIT`,
  `RAW_FILES`, `STATUS_RUNNING`, `STATUS_SUCCEEDED`, `STATUS_FAILED`,
  `STATUS_NO_FILES`, `PIPELINE_RUN_ID`
- **Modules**: `Utils` (= `pipeline_utils`), `pipeline_logging` functions
  (`pipeline_log_upsert`, `pipeline_step_log_upsert`, `ingestion_log_insert`)
- **Bindings**: `uuid`, `time`, `F` (= `pyspark.sql.functions`), `datetime`,
  `timezone`

Catalog comes from a job parameter (`${var.catalog}` in `databricks.yml`),
or is derived from the notebook path via the `_target_catalog_map` if the
parameter is empty (manual / standalone runs).

Once `CATALOG` is known, `notebook_init` also calls
`pipeline_logging.configure(AUDIT)` so all audit writes resolve to the
correct schema.

## `libs/pipeline_logging.py`

Audit-tier helpers. Configure once per session.

```python
configure(audit_schema: str) -> None
# Called by notebook_init and by each spark_python_task script.
# Sets the module-level audit schema; required before any logging call.

pipeline_log_upsert(spark, pipeline_run_id, pipeline_name, status,
                    started_timestamp, ended_timestamp=None, error_message=None)
# Run-level row. UPSERT by pipeline_run_id.

pipeline_log_finalize(spark, pipeline_run_id)
# Close out a run row by scanning pipeline_step_log for failures.
# Called from finalize_pipeline_run_log.py at end of pipeline.

pipeline_step_log_upsert(spark, step_log_id, pipeline_run_id, step_sequence,
                         notebook_folder, notebook_name, status, started_timestamp,
                         layer=None, target_table=None, rows_read=None,
                         rows_written=None, ended_timestamp=None, error_message=None)
# Notebook-level row. UPSERT by step_log_id.

transform_detail_log_insert(spark, pipeline_run_id, step_log_id,
                            source_table, target_table, status, started_timestamp,
                            rows_read=None, rows_written=None, rows_inserted=None,
                            rows_updated=None, rows_expired=None, rows_rejected=None,
                            rows_deduplicated=None, validation_rules_applied=None,
                            schema_drift_detected=None, schema_drift_detail=None,
                            error_message=None, ended_timestamp=None)
# Table-level row. INSERT-ONLY. Auto-assigns transform_id.

ingestion_log_insert(spark, df_files, pipeline_run_id, step_log_id,
                     source_system, target_table, error_message=None,
                     ingested_timestamp=None)
# File-level row, bronze only. Appends one row per file via INSERT INTO ... SELECT.
```

## `libs/pipeline_utils.py`

Generic utilities. Imported as `Utils` by `notebook_init`.

```python
get_notebook_context(dbutils) -> dict
# Returns {"notebook_folder", "notebook_name", "notebook_path_full"}
# stripped of /Workspace/Users/<email>/ prefix.
# Use at the top of every notebook's step-log init.

capture_exception(exc) -> dict
# Returns {"error_type", "error_message", "error_traceback"}.
# Use in every `except Exception as e:` handler.

move_all_files(dbutils, source_path, target_path,
               create_target=True, skip_dirs=True, use_date_partition=False) -> dict
# Used in cell 7 of every bronze notebook to archive processed files,
# and in 000-MoveFilesFromArchiveToBronze for the reverse.

load_dim_from_csv(spark, source_path, target_table, merge_sql_fn,
                  add_timestamps=True, df_transform=None) -> dict
# Pattern A helper: reads a CSV, optionally adds InsertedDate/UpdatedDate,
# optionally applies a per-table df_transform, registers a temp view
# named 'temp_dim', runs caller-supplied merge SQL, returns an audit-ready
# dict whose keys match transform_detail_log_insert's parameter names.
# Caller passes the dict via **result.
```

## `libs/catalog_setup.py`

DDL helpers. **Only** called by `setup/catalog_ddl.ipynb`. Never import from
a pipeline notebook.

```python
create_catalog(spark, catalog, managed_location=None)
create_schemas(spark, schemas)
create_volume_schema(spark, catalog)
create_volumes(spark, dbutils, catalog, volume_definitions)
create_audit_tables(spark, audit_schema)
create_bronze_tables(spark, bronze_schema)
create_silver_tables(spark, silver_schema)
create_gold_tables(spark, gold_schema, silver_schema)
create_audit_views(spark, audit_schema)
create_reporting_views(spark, reporting_schema, silver_schema, gold_schema)
```

All return `{"status", "message", "objects_created", "error"}`. Caller checks
`status` and raises on failure.

## `libs/init_pipeline_run_log.py` and `libs/finalize_pipeline_run_log.py`

`spark_python_task` scripts wired into `databricks.yml` as the first and last
tasks of `vinoworld_elt_pipeline`. `finalize` uses `run_if: ALL_DONE` so it
fires whether upstream succeeded, failed, or was skipped.

- `init`: generates `pipeline_run_id`, opens the `pipeline_log` row, publishes
  the run_id as a `taskValue` (`init_pipeline_log:pipeline_run_id`).
- `finalize`: reads the taskValue, calls `pipeline_log_finalize` to scan
  `pipeline_step_log` and write the final status to `pipeline_log`.

Both scripts read `shared_lib_path` and `catalog` from `sys.argv` (set by the
bundle's `parameters:` list). `__file__` is not defined in `spark_python_task`
context — do not try to self-discover the libs path.
