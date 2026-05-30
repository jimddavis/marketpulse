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

**Workaround**: `Utils.normalize_aware_datetime` (in `pipeline_utils`)
normalizes naive datetimes to aware UTC at the helper boundary — called by
`pipeline_logging._duration_seconds` and every `*_upsert` / `*_insert`
helper, so callers don't have to think about it. Don't bypass it, and don't
re-introduce vinoworld's old `_to_utc_aware`.

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

`dbutils.notebook.exit(value)` works by RAISING an ordinary exception, and
there is **no public `dbutils.NotebookExit` class** to catch it with — that
name was invented in earlier (vinoworld) work and never existed in the API.
So a call placed INSIDE a `try/except Exception` is caught by the handler:
the notebook does NOT exit cleanly, the except branch runs instead, and the
step row is left mid-flight / the outcome is misclassified. (Research-
verified 2026-05-30 and empirically confirmed via the `step_log_test` run.)

The earlier "guard" `except dbutils.NotebookExit: raise` was a no-op — it
matched a class that does not exist and silently fell through to
`except Exception`.

**Workaround**: never call `dbutils.notebook.exit()` inside a
`try/except Exception`. Keep the no-files CHECK inside the try (so a failed
`dbutils.fs.ls` is still logged via `step.fail`), set a flag, then call
`step.no_files()` + `dbutils.notebook.exit(...)` AFTER the try block, where
the exit can't be swallowed. See `download_sources` / `step_log_test` cell 4.

```python
no_files = False
try:
    files = [... dbutils.fs.ls(SOURCE_PATH) ...]
    if not files: no_files = True
    else: ...work...
except Exception as e:
    step.fail(e); raise
if no_files:                       # outside try → exit() can't be swallowed
    step.no_files(); dbutils.notebook.exit("no files")
```

## Serverless auto-optimization retries failed tasks (duplicate audit rows)

Serverless compute has "auto-optimization" **enabled by default**, which
automatically retries a failed task once — *even with no `max_retries` set on
the job/task*. Verified empirically: job `step_log_test` run
`966022582684344` ran `step_log_test_no_files` as `attempt=0` and
`attempt=1`, both FAILED, ~22s apart. It is **not** sensitive to where the
error occurs in the notebook — a failure in any cell triggers it.

Each attempt re-runs the notebook from cell 1, so `StepLog` opens a fresh
`step_log_id` per attempt. **Every genuinely-failing step therefore writes
≥2 `pipeline_step_log` rows** (same `pipeline_run_id`, different
`step_log_id`). This is working as intended — it's an attempt-level audit
trail, not a bug in `StepLog`.

**Latent consequence (not yet fixed):** a task that fails `attempt=0` then
*succeeds* `attempt=1` leaves one `failed` **and** one `succeeded` row for
the same `step_sequence`. `pipeline_log_finalize` counts failures with
`COUNT(*) WHERE status='failed'`, so it would mis-mark such a pipeline
FAILED. Left as-is for now; revisit if finalize correctness matters.

**To disable:** uncheck *"Enable serverless auto-optimization (may include
additional retries)"* on the task (UI toggle; bundle-YAML expressibility
unverified).

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
