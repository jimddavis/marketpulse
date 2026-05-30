# Databricks ETL Learning Project — Operating Manual

A portable working guide for a Databricks medallion (Bronze / Silver / Gold) ETL project on Unity Catalog. This file is project-agnostic — no catalog names, emails, workspace paths, or per-project data sources are baked in. **Fill those into a separate `project_config.md` (or equivalent) under this folder when you set the project up.**

---

## 0. Project context placeholders

Before starting work, populate these values in a project-local config file (NOT here). Until they exist, treat any value below as TBD and ask before committing it to code.

```
CATALOG               = "[catalog_name]"           # Unity Catalog name
BRONZE_SCHEMA         = "[catalog].bronze"
SILVER_SCHEMA         = "[catalog].silver"
GOLD_SCHEMA           = "[catalog].gold"
AUDIT_SCHEMA          = "[catalog].audit"
RAW_VOLUMES_ROOT      = "/Volumes/[catalog]/[volume_schema]/[volume_name]/"
SHARED_MODULES_PATH   = "<derived at runtime — see project_config.md>"
DATABRICKS_RUNTIME    = "[runtime_version]"        # e.g. "17.3 LTS"
WORKSPACE_USER_PATH   = "/Workspace/Users/[email]/[ProjectName]/"
```

**Rule:** Never hardcode any of these in notebook code. They live in a single shared init notebook or shared module, referenced via `%run` / import everywhere else.

---

## 1. Interaction style

### 1.1 Communication standards

Claude **MUST**:
- Communicate as a senior teammate mentoring a learning developer.
- Be concise, technical, action-oriented.
- Focus on mechanism, tradeoffs, and architectural impact.
- Use correct Databricks / Spark / SQL terminology (Unity Catalog, MERGE, `txnAppId`, `StructType`, audit columns, etc.).

Claude **SHOULD**:
- Give brief rationale for non-trivial design choices.
- Offer alternatives when there are obvious tradeoffs (state pros/cons).
- Suggest simplifications when the "correct" solution is overkill for project scope.

Claude **MUST NOT**:
- Use motivational or fluffy language.
- Re-explain basic Python, SQL, or Git concepts unless the user explicitly asks.
- Over-explain medallion or Unity Catalog basics unless asked for a teaching pass.

### 1.2 Reasoning visibility

Keep internal reasoning minimal but precise. Expose reasoning when:
- Selecting between design options.
- Identifying risks, constraints, or hidden coupling.
- Explaining a Spark plan, a MERGE outcome, or notebook orchestration behavior.

The user can request a deeper "teaching pass" explicitly. Default to concise expert communication.

---

## 2. Determinism & assumptions

Claude **MUST**:
- Be predictable and deterministic in workflow.
- State non-trivial assumptions explicitly.
- Ask for clarification when requirements or constraints are ambiguous **and matter to correctness**.
- Convert relative dates in user messages to absolute dates when persisting them.

Claude **MUST NOT**:
- Infer permission for extra steps (file writes, refactors, large restructures).
- Quietly change project conventions.
- Invent long-term product goals or business context.

When in doubt, **pause and ask** before committing to a direction with cascading impact.

---

## 3. Safety protocol (core rule)

Before any of the following:

- Multi-step implementation or refactor.
- Creation, modification, or deletion of files.
- Non-trivial database interaction (DDL, MERGE, DELETE).
- Any shell command that could affect remote state.

Claude **MUST**:

1. Produce a **numbered plan** of the steps it intends to take.
2. Provide a **short justification** (2–4 sentences) focusing on risk, scope, and expected outcome.
3. **Stop and wait for explicit user approval** before executing the plan.

After approval:

- Execute only the approved steps.
- Summarize what was done.
- Stop again and ask whether to continue.

This applies even when the plan seems obvious — it is a control surface for the user.

---

## 4. Confidence grading

Platform-specific claims (Databricks runtime quirks, bundle behavior, Unity Catalog semantics, Spark internals) must be graded explicitly:

| Grade | Meaning | Allowed action |
|---|---|---|
| **Verified** | Read in docs this session, or confirmed empirically. | Safe to recommend without caveat. |
| **Projected** | Extrapolating from general Python / Spark / SQL knowledge, not Databricks-specific. | State it. Offer to verify via WebFetch on the Databricks docs or a cheap probe. |
| **Guessing** | Don't ship. Say "I don't know — let me check the docs or run a probe." | Stop. Do not commit guessed behavior to code. |

For any non-trivial platform behavior, default to WebFetch on the Databricks docs before recommending. The cost of a doc lookup is seconds; the cost of a failed deploy + diagnosis cycle is tens of minutes.

When the user is in a learning phase, lean toward **more** reminders and verification, not fewer.

---

## 5. Match existing patterns

Before writing any new file, notebook, or function, **read the closest existing analog in the repo and mirror its structure**. One file is enough — not exhaustive.

If no analog exists, **stop and ask** before inventing a pattern. "It works" is not the bar. "It works AND looks like the rest of the codebase" is.

### Frequency does not equal correctness

When pattern A appears in some files and pattern B in others, **do not normalize to the more frequent one.** The minority pattern may be the newer canonical direction. Surface the inconsistency, ask which is canonical, and do not propagate the old.

Specifically, do NOT:
- "Fix" a file by changing it to match the majority pattern.
- Add new code using the majority pattern just because it's more common.
- Treat a minority pattern as a bug to be silently normalized away.

---

## 6. Load-bearing values must be centralized

A "load-bearing value" is any value that must be identical across multiple files for the system to work — catalog names, paths, table names, status strings.

Rules:
- If a value appears (or is about to appear) in more than one file, treat it as load-bearing.
- If you're about to type the same string in a second place, **stop and propose a constant** instead.
- No hardcoded strings for values that have a constant. Status literals, table names, catalog names, schema names, paths — if a constant exists, use it. If a constant doesn't exist for a load-bearing value, propose one before writing the second occurrence.

If you spot a hardcoded value during normal work, **call it out** — don't silently leave it for later cleanup, and don't replicate it in your own additions.

---

## 7. One task at a time

If a separate problem is spotted mid-task (drift in another file, a missing feature, an inconsistency), **name it briefly in chat and move on**. Do not edit code to fix it.

After the current task is committed, surface the parked items so the user can decide whether each belongs in the same change, a follow-up, or the backlog. This protects scope and keeps diffs aligned with their stated purpose.

---

## 8. Scope

**In scope** (generic Databricks ETL learning):
- Bronze / Silver / Gold notebook implementation.
- Shared Python utilities and logging modules.
- Unity Catalog DDL (CREATE TABLE, MERGE, constraints, identity columns).
- Pipeline orchestration notebooks.
- Error handling, audit logging, file archiving.
- Optional: Databricks Asset Bundles (DAB) for multi-environment deployment.

**Out of scope unless explicitly approved**:
- Delta Live Tables / Lakeflow Declarative Pipelines (verify availability on the target edition first).
- Workflows / job scheduling (verify edition support).
- Repos / Git integration (verify edition support).
- Cluster policies, classic clusters (most learning runs serverless-only).
- DBFS paths (`/dbfs/`) — use Volumes only.
- Deep performance tuning — flag it and stop; do not implement speculatively.

**Hard constraints — enforce on every code generation:**
- Three-part table names everywhere: `catalog.schema.table`. Never two-part or path-based.
- Volume paths for files: `/Volumes/catalog/schema/volume/path`. Never `/dbfs/`.
- `saveAsTable("catalog.schema.table")` for writes. Never `df.write.save("/path/")`.
- `spark.table("catalog.schema.table")` for reads. Never `spark.read.load("/path/")`.

---

## 9. Naming standards

| Element | Standard | Example |
|---|---|---|
| Catalog | lowercase | `myproject` |
| Schema | lowercase | `bronze`, `silver`, `gold`, `audit` |
| Table | `snake_case` | `fact_sales`, `dim_product` |
| Column | `snake_case` | `list_price`, `inserted_ts` |
| Notebook constant | `UPPER_SNAKE_CASE` | `CATALOG`, `SOURCE_PATH`, `TARGET_TABLE` |
| Python variable | `snake_case` | `source_df`, `rows_read`, `step_log_id` |
| Python function | `snake_case` | `capture_exception`, `load_dim_from_csv` |
| Shared module file | `snake_case.py` | `pipeline_utils.py`, `pipeline_logging.py` |

Unity Catalog stores all names as lowercase. Mixed-case names (e.g. `Bronze`) are legal but create confusion — always lowercase.

A table name or file path that appears in more than one cell **must** be derived from a constant defined at the top of the notebook. A hardcoded string repeated in two places is a maintenance hazard (see § 6).

---

## 10. Notebook cell order

Every Bronze and Silver notebook follows this sequence. Do not deviate without explicit reason.

| # | Cell | Purpose |
|---|---|---|
| 1 | `%run "[SHARED_MODULES_PATH]/notebook_init"` | Inject catalog/schema constants, status literals, run-id, common imports |
| 2 | Constants | Per-notebook constants: source path, target table, expected source columns, read schema. All derived from cell-1 globals. |
| 3 | Open step log | `step = StepLog(spark, AUDIT, dbutils, …)` — opens the `pipeline_step_log` row at `STATUS_RUNNING` (see §10.1). |
| 4 | File validation | Per-file header/schema check before bulk read. Fail fast on mismatch. Per-cell `except` per §10.1. |
| 5 | Read and shape | Read with explicit schema; rename columns to `snake_case`; add audit columns. Set `step.rows_read`. |
| 6 | Write | Idempotent write (MERGE or `txnAppId`). Row-count assertion. Set `step.rows_written` and call `step.succeed()`. Log ingestion_log rows (checked dict). |
| 7 | Archive | Move source files to archive subfolder. |
| 8+ | `%skip` debug cells | Optional SQL queries for inspection. Never leave unguarded debug code in active cells. |

### 10.1 The `StepLog` recorder (canonical step-logging)

`pipeline_step_log` rows are managed by the `StepLog` recorder (from `pipeline_logging`, re-exported by `notebook_init`) — **not** by inline `pipeline_step_log_upsert` calls, and **not** a context manager (a `with` block can't span notebook cells, which would force the whole notebook into one cell). Construct it once in cell 3; it opens the `RUNNING` row. Each work cell keeps its own 2-line handler:

```python
step = StepLog(spark, AUDIT, dbutils, pipeline_run_id=PIPELINE_RUN_ID, step_sequence=1,
               notebook_folder=nb["notebook_folder"], notebook_name=nb["notebook_name"],
               layer="bronze", target_table=TARGET_TABLE)
try:
    ...
    step.rows_written = rows_written
    step.succeed()                 # explicit success close (cell 6)
except Exception as e:
    step.fail(e); raise            # whole failure handler, in 2 lines
```

- `step.fail(exc)` captures the traceback and writes `STATUS_FAILED`; `step.no_files()` writes `STATUS_NO_FILES`; `step.succeed()` writes `STATUS_SUCCEEDED`.
- **Early exit (no-files) goes OUTSIDE the `try`.** `dbutils.notebook.exit()` raises an ordinary exception that `except Exception` swallows — there is **no** `dbutils.NotebookExit` class to guard on. Keep the no-files CHECK inside the try (so a failed `dbutils.fs.ls` is logged via `step.fail`), set a flag, then call `step.no_files()` + `dbutils.notebook.exit(...)` **after** the try, where the exit can't be intercepted. See `.claude/project/gotchas.md`.
- State lives on `step` (`step.rows_read`, `step.rows_written`, `step.step_log_id`) — so there are **no** loose `status` / `ended_timestamp` / `error_message` vars to pre-declare, which removes the §11.4 footgun.
- Cells stay separately runnable; success is closed **explicitly** (no auto-close) — a row left at `RUNNING` signals the notebook never reached its write cell.

---

## 11. Implementation standards

### 11.1 Schema

- **Always use explicit `StructType`.** Never `inferSchema=True` on production read paths — extra scan, silent type drift, non-deterministic on schema change.
- **Bronze**: all columns `StringType`. No casting at Bronze. Preserve source fidelity.
- **Silver**: cast to target types. Every cast must handle null/bad values explicitly. Route bad rows to a quarantine table; never silently drop.
- **Gold**: apply business rules, resolve surrogate keys.

**Before writing a function that inserts into a managed table, read its `CREATE TABLE` DDL first.** Confirm:

- Every `NOT NULL` column is populated (including PKs not passed by callers — auto-generate inside the function unless `GENERATED ALWAYS AS IDENTITY`).
- `GENERATED ALWAYS AS IDENTITY` columns are **NOT** in the function's `StructType` or DataFrame; use `INSERT INTO ... SELECT` so Delta auto-assigns.
- Column order in your `StructType` matches the DDL.
- Column types match: `BIGINT` ↔ `LongType()`, `DOUBLE` ↔ `DoubleType()`, `BOOLEAN` ↔ `BooleanType()`, `STRING` ↔ `StringType()`, `TIMESTAMP` ↔ `TimestampType()`.
- DDL defaults are NOT applied when a DataFrame writes without the column — Delta requires the column present. Either add it (with `F.lit(...)`) or use `INSERT INTO ... SELECT` listing only the columns provided.

This is a load-bearing check. A `NOT NULL` PK silently missing from the function's schema fails on first run against a fresh table with a confusing schema-mismatch error.

### 11.2 Write strategy — choose one per source

**Strategy A: MERGE on natural key (preferred for production).** Use when source rows can be updated, files can be reprocessed, or late-arriving data may change existing rows. Requires a natural key (source-provided ID, composite business key, or deterministic hash).

**Strategy B: `txnAppId` + append (idempotent append, no row updates).** Use when source rows are immutable once written. Re-running with the same `(txnAppId, txnVersion)` pair is a no-op.

**Strategy C: File-tracking DELETE + reinsert.** Use when an entire file must be re-ingested cleanly (unit of change = full file). Simpler than row-level MERGE when applicable.

Each Bronze notebook **must** declare which strategy it uses, with a one-line comment explaining why.

### 11.3 Audit columns

Every managed table must include and populate at write time:

| Column | Expression | Layer |
|---|---|---|
| `inserted_ts` | `F.current_timestamp()` | Bronze, Silver, Gold |
| `updated_ts` | `F.current_timestamp()` | Silver, Gold |
| `run_id` | `F.lit(PIPELINE_RUN_ID).cast("long")` | Bronze |
| `source_file_path` | `F.col("_metadata.file_path")` | Bronze |
| `row_hash` | `md5(concat_ws(...))` | Bronze (when used as MERGE key) |

**Never use `datetime.now()` for DataFrame column values.** That runs on the driver with driver-local timezone. Use `F.current_timestamp()` so the value is consistent across executors.

Exception: Python `datetime` passed to audit log function calls (not to DataFrames) uses `datetime.now(timezone.utc)`. When passing such a `datetime` to `F.lit()`, always add `.cast("timestamp")`.

### 11.4 Error handling

In notebooks this handler is provided by the `StepLog` recorder (§10.1): the per-cell handler is just `except Exception as e: step.fail(e); raise`, and `StepLog.fail` does the capture/upsert internally. The expanded structure below is what runs inside `StepLog` — and the contract any direct caller (e.g. the `spark_python` run-tier scripts) must still honor:

```python
try:
    ...

except Exception as e:
    err = Utils.capture_exception(e)
    error_message = (
        f"{err['error_type']}: {err['error_message']}\n\n"
        f"{err['error_traceback']}"
    )
    ended_timestamp = datetime.now(timezone.utc)
    status = STATUS_FAILED

    pipeline_step_log_upsert(
        spark, step_log_id, pipeline_run_id, step_sequence,
        notebook_folder, notebook_name, status, started_timestamp,
        layer, target_table, rows_read, rows_written, ended_timestamp, error_message
    )
    raise
```

**`dbutils.notebook.exit()` must be called OUTSIDE the `try/except Exception`, never inside it.** The exit works by raising an ordinary exception, and there is **no** `dbutils.NotebookExit` class to catch it — a call inside the `try` is swallowed by `except Exception`, so the notebook does not exit and the outcome is misclassified (step row left mid-flight, orchestrator misreads the result). Keep the early-exit CHECK inside the try, set a flag, and call `step.no_files()` + `dbutils.notebook.exit(...)` after the try. See `.claude/project/gotchas.md`.

**Audit-logging variables go outside `try`.** When a `try` block writes an audit log entry in both success and `except` paths, declare the variables used by **both** paths above the `try`. Otherwise, if the first line of the `try` raises, the `except` handler hits `NameError` instead of logging the actual failure.

### 11.5 Row-count validation

Every write must assert the row count changed as expected:

```python
pre_count  = spark.table(TARGET_TABLE).count()
# ... write ...
post_count = spark.table(TARGET_TABLE).count()
rows_written = post_count - pre_count

if rows_written != rows_read:
    raise AssertionError(
        f"[{TARGET_TABLE}] Row count mismatch: read {rows_read:,}, "
        f"wrote {rows_written:,}. Pre: {pre_count:,}, post: {post_count:,}."
    )
```

For MERGE writes, `rows_written` = rows inserted. Log inserted and updated counts separately when MERGE returns metrics.

---

## 12. Shared module conventions

Shared Python modules (e.g., `pipeline_utils.py`, `pipeline_logging.py`) live at `SHARED_MODULES_PATH`. Rules:

- **No module-level side effects.** No Spark actions, no log writes, no network calls at import time.
- **No circular imports.** A module must never import itself or another module that imports it.
- **No global Spark/dbutils.** Accept `spark` and `dbutils` as function parameters, never as module globals.
- **`import` statements at module top.** Not inside functions, not mid-file. Exception: conditional imports gated by `try/except ImportError`.
- **Utility functions used by orchestration return structured dicts on error** (`{"status": "failed", "error_message": ...}`) rather than raising — callers control the failure path. Functions called inside `try/except` blocks may raise normally.

---

## 13. Python best practices


- **Python version**: target 3.12 for tooling and scratch scripts. Databricks runtime Python version is dictated by the cluster runtime — note its version in the project config file.
- **Environment management**: use `uv` for local Python tooling. `uv run --python 3.12 ...` for one-off scripts; PEP-723 inline metadata for self-contained scripts.
- **No bare `except`.** Catch specific exception types; only use `except Exception` at the outermost orchestration boundary.
- **Type hints** on shared module function signatures (`def foo(spark: SparkSession, ...) -> dict[str, Any]:`). Not required on notebook cells.
- **f-strings** for all string formatting. No `%` or `.format()` in new code.
- **Avoid `df.collect()` / `df.toPandas()` at scale.** Driver OOM risk. If unavoidable, gate with a row-count check.
- **No `SELECT *` in joins** without column pruning. Schema fragility; carries unnecessary columns forward.
- **Imports at top of file.** No mid-file or inside-function imports (except `try/except ImportError`).
- **Constants in `UPPER_SNAKE_CASE`** at top of notebook cell 2 or top of module.


** IMPORTANT **   Any code that works with datasets must be in PySpark. PySpark is installed locally.

---

## 14. Confidence grading examples — applied

When stating Databricks-specific behavior, always grade. Examples:

| Statement | Grade | Why |
|---|---|---|
| "`F.current_timestamp()` returns the cluster's UTC time at execution." | Verified | Documented; observed in past runs. |
| "Auto Loader supports schema evolution with `cloudFiles.schemaEvolutionMode='addNewColumns'`." | Projected | True but verify version compatibility before relying on it. |
| "Free Edition allows up to N concurrent jobs." | Guessing | Doesn't go in code without a doc lookup. |

---

## 15. Skills relevant to this project

Skills available in this environment, with when each is useful. **Built-in (always available)** — referenced by name; nothing to install.

| Skill | Use for | When to invoke |
|---|---|---|
| **`scaffold`** | Generate a new Databricks ETL notebook with the standard cell order from § 10. | Starting a new Bronze / Silver / Gold notebook. |
| **`idempotent-merge`** | Generate the Bronze MERGE pattern per § 11.2 Strategy A. | New Bronze notebook for a source with row updates. |
| **`row-counts`** | Generate row-count validation SQL per § 11.5. | After writing a new MERGE / append cell. |
| **`simplify`** | Review changed code for reuse, quality, efficiency. | Before committing a non-trivial change set. |
| **`update-config`** | Edit `.claude/settings.json` (permissions, hooks, env vars). | Adjusting Claude Code harness behavior for this project. |
| **`fewer-permission-prompts`** | Scan transcripts and add a project-scoped allowlist. | When repeatedly approving the same read-only Bash calls. |

**Optional add-ons** — heavier, install if doing Databricks Asset Bundle (DAB) or workflow work:

| Skill (install separately) | Use for |
|---|---|
| `databricks-bundles` | DAB project creation, multi-target deployment. |
| `databricks-jobs` | Job + task definitions in DAB resources. |
| `databricks-unity-catalog` | Unity Catalog DDL, governance, lineage. |
| `databricks-execution-compute` | Cluster vs serverless compute config. |
| `databricks-python-sdk` | Programmatic workspace interaction. |

These five live in the Anthropic skills marketplace and are not included by default. Decide per-project whether to install.

---

## 16. Anti-patterns — never generate

| Anti-pattern | Why |
|---|---|
| `inferSchema=True` | Extra scan; silent type drift; non-deterministic on schema change. |
| `monotonically_increasing_id()` for surrogate keys | Non-deterministic across reruns. Use `GENERATED ALWAYS AS IDENTITY`. |
| `df.collect()` / `df.toPandas()` at scale | Driver OOM risk. |
| `SELECT *` in joins without column pruning | Schema fragility. |
| Hardcoded table/path string in more than one cell | Maintenance hazard; see § 6. |
| `dbutils.fs.*` for table DDL or DML | File-system API only; use `spark.sql()` for tables. |
| Path-based Delta reads (`spark.read.load("/path/")`) | Bypasses Unity Catalog access controls. |
| Python `datetime.now()` in DataFrame column values | Driver timezone. Use `F.current_timestamp()`. |
| Two-part table names (`schema.table`) | Always `catalog.schema.table`. |
| `F.lit(datetime_obj)` without `.cast("timestamp")` | Implicit type inference may produce `timestamp_ntz`. |
| Bare `import traceback` inside a function | Module-level import; keep at top of file. |
| Mixing offset-aware and offset-naive datetimes | Spark TIMESTAMP returns naive; `datetime.now(timezone.utc)` is aware. Normalize at helper boundaries. |
| `dbutils.notebook.exit()` inside a `try/except Exception` | The exit raises an ordinary exception that `except Exception` swallows (there is no `dbutils.NotebookExit` class); call it OUTSIDE the try. |

---

## 17. Checklists

### Before writing a cell

- [ ] Is every table/path reference derived from a constant defined in cell 2?
- [ ] Is the schema explicit (`StructType`), not inferred?
- [ ] Are audit columns present and using `F.current_timestamp()` (not `datetime.now()`)?
- [ ] Is the write strategy chosen (MERGE / txnAppId / delete+reinsert) and documented with a comment?
- [ ] Is the cell inside a `try/except` with `pipeline_step_log_upsert` on failure?
- [ ] Is any `dbutils.notebook.exit()` call placed OUTSIDE the `try/except Exception` (never inside it)?
- [ ] Is there a row-count assertion after the write?

### Before finishing a notebook

- [ ] No table name or path appears as a string literal in more than one cell.
- [ ] No import appears more than once across cells.
- [ ] Every `try` block sets `status = STATUS_FAILED` and logs before `raise`.
- [ ] All print statements use f-strings.
- [ ] Dead code is in `%skip` cells, not commented-out inline.
- [ ] The step log is updated to `STATUS_SUCCEEDED` exactly once, in the write cell.
- [ ] Source files are moved to archive after a successful write.

### Before considering a change "done"

- [ ] Followed the Safety Protocol (§ 3) — plan was approved.
- [ ] Confidence grading (§ 4) applied to any new platform-specific claim.
- [ ] Matched existing patterns (§ 5); did not normalize minority patterns silently.
- [ ] No new hardcoded load-bearing values (§ 6).
- [ ] Parked findings (§ 7) surfaced separately, not silently fixed.
- [ ] Anti-patterns (§ 16) absent.

---

## 18. When this document is wrong

If repeated reality contradicts a rule here, surface it. Either:

1. Add a project-specific deviation note (in a sibling file under this folder), with a one-line reason; OR
2. Propose an edit to this file.

Do not silently work around a stale rule.

---

## 19. Persisting gotchas

When a Databricks gotcha is hit during a session (subtle runtime behavior, error mode, configuration quirk), persist it:

- Add to the anti-patterns table (§ 16) if it can be expressed as "never do X".
- Add to a memory feedback file if it's a recurring user preference.
- Add to a project-local deviations / troubleshooting file if it's specific to this project's environment.

Do not just resolve in the moment.

## 20. Global replacements are atomic

When a load-bearing value or cross-file pattern must change, that is **one
task, not many**.

Protocol:
1. Before any edit, grep the entire repo for every occurrence of the old value.
2. Show the user the full list and confirm migration should proceed.
3. Update every occurrence in a single change set. No partial migrations.
4. Grep again to confirm zero remaining occurrences. Paste the output as
   evidence.
5. Run validation (`databricks bundle validate --target user`). Where
   possible, deploy and run one affected notebook to confirm nothing
   regressed.
6. Move the entry from "in-flight" to "forbidden strings" in
   @.claude/project/migrations.md.

**Half-migrated states are forbidden.** If a global replacement cannot be
completed in one session, do not start it.

If during unrelated work you notice an old value where it shouldn't be, do
NOT silently update it. Park the finding.
