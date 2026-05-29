# Project-specific gotchas

Real failure modes from this project. Training-data best practices won't warn
you about these; they were learned the hard way.

## `__file__` is not defined in `spark_python_task` scripts

Databricks invokes `spark_python_task` scripts via `exec(compile(...))`, so
the `__file__` name is undefined. Attempting to self-discover the script's
location for sibling paths (e.g., to find `libs/`) raises `NameError`.

**Workaround**: pass paths in as task `parameters:` and read with `sys.argv`.
See `init_pipeline_run_log.py` and `finalize_pipeline_run_log.py` —
`sys.argv[1]` is `shared_lib_path`, `sys.argv[2]` is `catalog`.

## `DESCRIBE HISTORY` returns zeros inside `BEGIN ATOMIC` blocks

`operationMetrics` (`numTargetRowsInserted`, `numTargetRowsUpdated`, etc.)
are populated for a plain MERGE but are all zero for MERGE/INSERT statements
wrapped in `BEGIN ATOMIC ... END;`.

**Workaround**: derive row counts from pre/post `COUNT(*)` differentials.
See `slvr_02_load_dim_product` for the canonical pre-count → atomic block →
post-count pattern.

## Sync snapshot goes stale after laptop restart or UI delete

The Databricks CLI keeps a local sync snapshot at
`.databricks/bundle/<target>/sync-snapshots/` to skip uploading unchanged
files. If files in the remote workspace change (deleted via UI, target
recreated, laptop restarted) without a corresponding local change, the CLI
silently skips re-uploading them — files appear "missing" in the workspace
after a successful deploy.

**Fix**:

```bash
rm -rf .databricks/bundle/<target>/sync-snapshots/
databricks bundle deploy --target <target>
```

Apply any time files appear missing in the workspace after a deploy.

## Mixing tz-aware and tz-naive datetimes

Spark TIMESTAMP columns return offset-NAIVE Python datetimes on read.
`datetime.now(timezone.utc)` returns offset-AWARE. Subtracting one from the
other raises `TypeError: can't subtract offset-naive and offset-aware
datetimes`.

**Workaround**: `pipeline_logging._to_utc_aware` normalizes naive datetimes
to aware UTC at the helper boundary, so callers don't have to think about it.
Don't bypass it.

## Spark's JSON reader flattens nested objects at read time

If you read JSON with `spark.read.format("json").load(path)`, nested objects
are flattened. Using `from_json` afterward fights against this.

**Workaround**: declare the nested field as `StringType` in `read_schema`,
then call `from_json(F.col("NestedField"), nested_schema)` to parse it
explicitly. See `brz_03_verde_sales` for the pattern.

## Spark's directory read cannot detect per-file schema drift

`spark.read.format("csv").load(SOURCE_PATH)` happily merges files with
different headers, silently dropping or NULLing columns.

**Workaround**: per-file header validation BEFORE the bulk read. Probe each
file's `.limit(0).columns` against `EXPECTED_SOURCE_COLS`. See every bronze
notebook's cell 4 for the pattern.

## `except Exception` swallows `dbutils.notebook.exit()`

Databricks raises a JVM-internal exception on `dbutils.notebook.exit()` that
propagates through `except Exception`. Without an explicit guard, a clean
notebook exit is misclassified as a failure (failed audit row, parent job
flagged as failed).

**Workaround**: `except dbutils.NotebookExit: raise` MUST appear before
`except Exception` in every cell that calls `dbutils.notebook.exit()`. See
every bronze notebook's cell 4.

## `INSERT INTO` with explicit column list is required for IDENTITY tables

When a table has `BIGINT GENERATED ALWAYS AS IDENTITY`, you cannot include
that column in the DataFrame schema OR in `INSERT INTO ... VALUES`.

**Workaround**: use `INSERT INTO target_table (col1, col2, ...) SELECT
col1, col2, ... FROM staging_view` and OMIT the IDENTITY column. See
`ingestion_log_insert` and `gold_01_load_sales_fact` for examples.

## Audit-logging variables must be declared OUTSIDE the `try` block (Pattern B)

If a notebook writes `transform_detail_log` in both success and failure
paths, the per-transform variables (`transform_source_table`,
`transform_target_table`, `transform_started`, `rows_inserted`,
`rows_expired`, etc.) must be declared BEFORE the `try:` line. If they live
inside `try:` and the first SQL statement raises, the `except` handler hits
`NameError` instead of logging the actual failure.



```python
# Per-transform variables for transform_detail_log. Defined OUTSIDE the try
# block so the except handler can log a failed transform row even if the
# atomic SQL never started.
transform_source_table = f"{CATALOG}.bronze.products"
transform_target_table = f"{CATALOG}.silver.dim_product"
transform_started      = datetime.now(timezone.utc)
rows_inserted          = 0
rows_expired           = 0

```
