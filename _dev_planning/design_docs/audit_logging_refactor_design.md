# Audit Logging — Refactor Design

**Status:** Draft for review · **Scope:** design only (no implementation) ·
**Target module:** `databricks_code/libs/pipeline_logging.py` (+ `notebook_init.ipynb`,
`libs/init_pipeline_run_log.py`, `libs/finalize_pipeline_run_log.py`, bundle resources)

A refactor of the run/notebook/table/file audit-logging stack inherited from the
vinoworld project. The bones (a multi-tier audit hierarchy bracketed by an
init/finalize pair) are sound and are **kept**. Four conventions are **changed**
to remove hidden coupling, duplication, and per-cell boilerplate — done now,
at project start, rather than propagated.

> **Reading order for `/sc:implement`:** §10 (Implementation Contract) is the
> normative checklist. §1–§9 are rationale. If they ever disagree, **§10 wins** —
> raise the conflict, do not silently pick one.

---

## 1. Motivation — what we inherited and why it broke

marketpulse copied vinoworld's `pipeline_logging.py`, then partially rewrote it
for the data-acquisition framework. The rewrite **dropped the entire run-level
tier** (`pipeline_log_upsert`, `pipeline_log_finalize`, `configure`, the
`STATUS_*` constants) while keeping the `init_pipeline_run_log.py` script that
imports them. Result, observed empirically on a `bundle run`:

```
ImportError: cannot import name 'pipeline_log_upsert' from 'pipeline_logging'
  File .../libs/init_pipeline_run_log.py:22
    from pipeline_logging import pipeline_log_upsert, configure, STATUS_RUNNING
```

That traceback also **settles an open platform question**: the
`spark_python_task` *executed* on Free-Edition serverless (it reached line 22 via
`exec(compile(...))`). So Python-script tasks are **Verified** on this edition —
we keep init/finalize as scripts and do not convert them to notebooks.

The fix is not a straight port-back. vinoworld's run tier carries three habits we
should not replicate, plus the marketpulse rewrite established two *better*
conventions (explicit `audit_schema`, swallow-and-return on leaf writes) that the
run tier must now match. This doc reconciles them into one consistent module.

---

## 2. The audit model — KEPT as-is

Four FK-chained tiers, keyed `pipeline_run_id` → `step_log_id`. DDL already exists
in `libs/ddl/audit_ddl.py` (`create_audit_tables`) — **no schema change**.

| Tier | Table | Grain | Write semantics | Writer |
|---|---|---|---|---|
| Run | `pipeline_log` | 1 / pipeline run | MERGE on `pipeline_run_id` (upsert) | `init_…` opens, `finalize_…` closes |
| Notebook | `pipeline_step_log` | 1 / notebook execution | MERGE on `step_log_id` (upsert) | each notebook (via §7 `StepLog` recorder) |
| Table | `transform_detail_log` | 1 / silver-gold transform | append (insert-only, immutable) | silver / gold |
| File | `ingestion_log` | 1 / source file | `INSERT … SELECT` (insert-only) | bronze |
| File | `download_log` | 1 / downloaded file | append (insert-only) | `download_sources` (already built) |

**Kept patterns** (do not redesign):
- The **open/close bracket**: `init_pipeline_run_log.py` runs first (writes
  `STATUS_RUNNING`, sets the `pipeline_run_id` taskValue); `finalize_pipeline_run_log.py`
  runs last with **`run_if: ALL_DONE`** so it fires on success, failure, or skip.
- **Data-driven final status**: `pipeline_log_finalize` derives the run's status
  by scanning `pipeline_step_log` for `failed` rows — it trusts the audit table,
  not the Databricks task outcomes.
- **Idempotent MERGE on natural keys** so retries/re-runs never duplicate.

---

## 3. Decision 1 — drop `configure()`; pass `audit_schema` explicitly

**Change.** Delete `configure()`, the module global `_AUDIT_SCHEMA_NAME`, and the
`_audit(table)` helper. Every public function takes `audit_schema: str` as its
second positional argument (after `spark`), then derives `f"{audit_schema}.{table}"`
locally.

**Why.** `configure()` is hidden temporal coupling: every function silently
assumes it was called first, and forgetting it fails at *call* time, not import.
It also contradicts project CLAUDE.md §12 ("no global Spark/dbutils; pass as
parameters") and — decisively — **marketpulse already moved this way**:
`download_log_insert(spark, audit_schema, …)` and `download_log_last_sha256(spark,
audit_schema, …)` already take the schema explicitly. Per CLAUDE.md §5, the newer
pattern is canonical; we converge the run/notebook tiers onto it rather than
reviving the global.

**Call-site impact.** `init_pipeline_run_log.py` and `finalize_pipeline_run_log.py`
compute `audit_schema = f"{catalog}.audit"` from `sys.argv[2]` and pass it
explicitly. They no longer import or call `configure`.

---

## 4. Decision 2 — centralize `STATUS_*`, re-export via `notebook_init`

**Change.** The status vocabulary lives in **one** place — `pipeline_logging.py`:

```python
STATUS_RUNNING   = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED    = "failed"
STATUS_NO_FILES  = "no_files"
STATUS_SKIPPED   = "skipped"
```

`notebook_init` does `from pipeline_logging import STATUS_RUNNING, …` and
re-exports them into the notebook namespace (notebooks keep using the bare names).
The existing private `_STATUS_SUCCEEDED` in `pipeline_logging` is removed in favor
of `STATUS_SUCCEEDED`.

**Why.** Today the literals are duplicated: inline in `notebook_init` **and** a
private `_STATUS_SUCCEEDED` in `pipeline_logging` — a CLAUDE.md §6 load-bearing
duplication. And the `spark_python` scripts cannot see `notebook_init`'s copies at
all, which is the proximate cause of the `ImportError`. Centralizing in the module
that scripts already import fixes both at once: scripts `import` them, notebooks
get them re-exported.

---

## 5. Decision 3 — per-tier error contract (raise vs swallow)

vinoworld uniformly **raised**; the marketpulse rewrite made leaf writes
**swallow and return a dict**. Both are right — for different tiers. Make the
choice explicit and consistent:

| Function | Contract | Rationale |
|---|---|---|
| `pipeline_log_upsert` | **May raise** | Called at controlled points (init script, finalize). A failure here means the run record is untrustworthy — fail loudly. |
| `pipeline_step_log_upsert` | **May raise** | Wrapped by the §7 `StepLog` recorder; the notebook's per-cell `except` calls `step.fail(e)`. |
| `pipeline_log_finalize` | **May raise** | Last task; a finalize failure should surface. |
| `ingestion_log_insert` | **Swallow → `{"status","error_message"}`** | Leaf write *after* a committed Bronze write. A logging hiccup must not roll back data (CLAUDE.md §11.4 / §12). |
| `transform_detail_log_insert` | **Swallow → dict** | Same: leaf write after a committed transform. |
| `download_log_insert` | **Swallow → dict** | Already implemented this way; keep. |

So the rule is: **upserts on the run/notebook tiers raise; insert-only leaf
writes swallow and return a status dict.** Callers of leaf writes check the
returned dict and `print` a warning; they never let it abort the data write.

---

## 6. Decision 4 — `download_sources` writes a `pipeline_step_log` row

**Change.** `bronze/download_sources.ipynb` opens and closes a `pipeline_step_log`
row like every other Bronze notebook (via the §7 `StepLog` recorder). Suggested
field mapping for the download step:

- `layer = "bronze"`, `step_sequence` = its ordinal in the job,
- `rows_read` = files **attempted**, `rows_written` = files **landed**
  (from the `run_all` summary),
- `target_table = None` (downloads land files in Volumes, not a single table; the
  per-file detail is already in `download_log`).

**Why.** `pipeline_log_finalize` derives run status solely from `pipeline_step_log`.
When the download tier was added it deliberately wrote only `download_log` and
**no** step_log row — so a download failure would not surface in the run's final
status. Having `download_sources` write a step_log row closes that gap without
making finalize scan a second table. (The download was abort-on-first, so a failed
batch raises; the cell's `except` calls `step.fail(e)` → `FAILED`, and finalize sees it.)

---

## 7. Decision 5 — a `StepLog` recorder object kills the per-cell boilerplate

**Change.** Replace the repeated ~12-line `except` block (currently copy-pasted
into cells 4/5/6 of every Bronze and Silver notebook) with a single recorder
**class** in `pipeline_logging.py`. It is constructed once (writing the `RUNNING`
row) and held in a `step` variable; each cell keeps its own small `try/except`.

> **Why a recorder object and not a context manager.** A context-manager (`with
> step_log(...) as step:`) form was considered and **rejected**: a `with` block is
> one compound statement that cannot span notebook cells, so it would force the
> whole validate → read → write flow into a single cell, defeating cell-by-cell
> interactive execution. The recorder object keeps each step in its own runnable
> cell, which is the higher priority for this project's dev loop.

```python
class StepLog:
    """One pipeline_step_log row, opened on construction, closed explicitly.

    Holds step_log_id + mutable rows_read / rows_written so notebooks carry no
    loose status/ended_timestamp/error_message vars (removes the §11.4 footgun).
    `dbutils` is accepted only so callers stay uniform; it is never a module global.
    """
    def __init__(self, spark, audit_schema, dbutils, *, pipeline_run_id,
                 step_sequence, notebook_folder, notebook_name,
                 layer=None, target_table=None):
        self._spark = spark; self._audit = audit_schema
        self.step_log_id  = str(uuid.uuid4())
        self._started     = datetime.now(timezone.utc)
        self.rows_read    = 0
        self.rows_written = 0
        self._common = dict(pipeline_run_id=pipeline_run_id, step_sequence=step_sequence,
                            notebook_folder=notebook_folder, notebook_name=notebook_name,
                            layer=layer, target_table=target_table)
        pipeline_step_log_upsert(spark, audit_schema, self.step_log_id,
                                 status=STATUS_RUNNING, started_timestamp=self._started,
                                 **self._common)                      # OPEN: RUNNING row

    def _close(self, status, error_message=None):
        pipeline_step_log_upsert(
            self._spark, self._audit, self.step_log_id, status=status,
            started_timestamp=self._started, ended_timestamp=datetime.now(timezone.utc),
            rows_read=self.rows_read, rows_written=self.rows_written,
            error_message=error_message, **self._common)

    def succeed(self):  self._close(STATUS_SUCCEEDED)
    def no_files(self): self._close(STATUS_NO_FILES)
    def fail(self, exc):
        err = Utils.capture_exception(exc)
        self._close(STATUS_FAILED,
                    error_message=f"{err['error_type']}: {err['error_message']}")
```

Usage keeps the original cell structure intact:

```python
# Cell 3 — open (RUNNING)
step = StepLog(spark, AUDIT, dbutils, pipeline_run_id=PIPELINE_RUN_ID,
               step_sequence=1, notebook_folder=nb["notebook_folder"],
               notebook_name=nb["notebook_name"], layer="bronze",
               target_table=TARGET_TABLE)

# Cell 4 — validate (separately runnable)
no_files = False
try:
    files = [...]
    if not files:
        no_files = True
    ...
except Exception as e:
    step.fail(e); raise           # the whole handler, in 2 lines
if no_files:                      # OUTSIDE the try — exit() can't be swallowed
    step.no_files(); dbutils.notebook.exit("No CSV files at " + SOURCE_PATH)

# Cell 5 — read/shape: step.rows_read = bronze_df.count()  (same 2-line except)
# Cell 6 — write: step.rows_written = post - pre; step.succeed()  (same 2-line except)
```

**Why.** The current pattern repeats the same handler three times per notebook and
is *the* reason the CLAUDE.md §11.4 "pre-declare variables outside the try" gotcha
exists — a footgun baked into every file. The recorder collapses each handler to
`step.fail(e); raise` (2 lines) and moves the state onto `step`, so the loose vars
disappear and the footgun with them. At project start this is the right time;
doing it later means rewriting every notebook.

**Per-cell contract (canonical):**
- Every work cell ends with `except Exception as e: step.fail(e); raise`.
- A cell that may call `dbutils.notebook.exit()` calls it **OUTSIDE** the `try`
  (set a flag inside, exit after), and calls the matching terminal recorder method
  (`step.no_files()`) immediately before exiting. The exit raises an ordinary
  exception that `except Exception` would swallow — there is no `dbutils.NotebookExit`
  class (CLAUDE.md §11.4 / `.claude/project/gotchas.md`).
- Success is closed **explicitly** with `step.succeed()` in the write cell. (The
  recorder does not auto-close — that is the deliberate price of keeping cells
  separate; an un-closed step left at `RUNNING` is a visible signal the notebook
  did not reach its write cell.)
- Leaf writes (`ingestion_log_insert`) run **after** `step.succeed()` and only
  warn on failure (Decision 3) — they never flip the step.

**Consequence — convention update (must be approved):** §10 notebook cell-order in
this project's `.claude/CLAUDE.md` gains the `StepLog` open/close pattern and the
2-line `except` as canonical, replacing the inline 12-line handler. Cell *granularity
is unchanged* (validate / read / write stay separate), so this is an additive
clarification rather than a restructure — but still a deliberate convention change,
not a silent one (CLAUDE.md §2). (The generic `databricks/.claude/CLAUDE.md` is a
shared parent outside this repo — not a target here.)

**Confidence: Verified (corrected 2026-05-30).** Empirically checked via the
`step_log_test` run: there is **no** `dbutils.NotebookExit` class, so the early exit
must be placed OUTSIDE the `try` (the `step.no_files()` clean-exit path then works).
The earlier `except dbutils.NotebookExit: raise` ordering was a no-op and has been
dropped. `dbutils` is passed in (never a module global), per CLAUDE.md §12.

---

## 8. Module API after refactor (specification)

Signatures `/sc:implement` should produce. All take `spark, audit_schema` first.
Types per the DDL (`STRING↔StringType`, `INT↔IntegerType`, `BIGINT↔LongType`,
`DOUBLE↔DoubleType`, `TIMESTAMP↔TimestampType`). Reuse `Utils.normalize_aware_datetime`
for the offset-naive/aware fix (already used by `download_log_insert`) — do **not**
re-introduce vinoworld's `_to_utc_aware`.

```python
# --- constants (single source of truth; notebook_init re-exports) ---
STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_NO_FILES, STATUS_SKIPPED

# --- run tier (upsert; may raise) ---
def pipeline_log_upsert(spark, audit_schema, pipeline_run_id, pipeline_name,
                        status, started_timestamp,
                        ended_timestamp=None, error_message=None) -> None
def pipeline_log_finalize(spark, audit_schema, pipeline_run_id) -> None
    # reads pipeline_name/started_timestamp from pipeline_log; scans
    # pipeline_step_log for STATUS_FAILED rows; upserts final status + duration.

# --- notebook tier (upsert; may raise) ---
def pipeline_step_log_upsert(spark, audit_schema, step_log_id, pipeline_run_id,
                             step_sequence, notebook_folder, notebook_name,
                             status, started_timestamp,
                             layer=None, target_table=None,
                             rows_read=None, rows_written=None,
                             ended_timestamp=None, error_message=None) -> None

class StepLog(spark, audit_schema, dbutils, *, pipeline_run_id, step_sequence,
              notebook_folder, notebook_name, layer=None, target_table=None)
    # constructor opens RUNNING; .rows_read / .rows_written are mutable;
    # .succeed() / .no_files() / .fail(exc) close the row (full body in §7).

# --- leaf tier (insert-only; swallow -> {"status","error_message"}) ---
def ingestion_log_insert(spark, audit_schema, df_files, pipeline_run_id,
                         step_log_id, source_system, target_table,
                         error_message=None, ingested_timestamp=None) -> dict
def transform_detail_log_insert(spark, audit_schema, ...) -> dict   # full param list per DDL
def download_log_insert(spark, audit_schema, *, ...) -> dict        # EXISTS — unchanged
def download_log_last_sha256(spark, audit_schema, source_url) -> str | None  # EXISTS
```

Write idioms (keep simple, one per semantic):
- **Upsert** (`pipeline_log`, `pipeline_step_log`): `DeltaTable.forName(...).merge(...)`
  on the natural key.
- **Insert-only** (`ingestion_log`, `transform_detail_log`, `download_log`):
  `createDataFrame(schema=…).write.format("delta").mode("append").saveAsTable(...)`,
  generating the STRING PK with `str(uuid.uuid4())`. No audit table has an IDENTITY
  column (§9.3), so this one idiom covers all three — `ingestion_log` drops vinoworld's
  `INSERT … SELECT` variant.

`StructType` column **order and types must match** `audit_ddl.py` exactly
(CLAUDE.md §11.1 load-bearing check). `pipeline_log`'s schema:
`pipeline_run_id, pipeline_name, status, started_timestamp, ended_timestamp,
duration_seconds, error_message`.

---

## 9. Resolved questions (answered in review — 2026-05-30)

1. **`StepLog` + early `dbutils.notebook.exit()`** — **Corrected 2026-05-30.** The
   original answer here (keep `except dbutils.NotebookExit: raise` before
   `except Exception`, "proven in vinoworld") was WRONG: there is no
   `dbutils.NotebookExit` class — the guard was a no-op, and `dbutils.notebook.exit()`
   inside the `try` is swallowed by `except Exception`. **Resolution:** call
   `dbutils.notebook.exit()` OUTSIDE the try (flag inside, exit after);
   `step.no_files()` still leaves a `NO_FILES` row. Empirically confirmed via the
   `step_log_test` run. See `.claude/project/gotchas.md`.
2. **`taskValues` across the bracket** — **Resolved / Verified.** `init` calls
   `dbutils.jobs.taskValues.set(key="pipeline_run_id", value=PIPELINE_RUN_ID)`;
   `notebook_init` and `finalize` read it via
   `taskValues.get(taskKey="init_pipeline_log", key="pipeline_run_id", …)`. It works
   as a per-run "environment variable" all downstream code assumes exists. **Key name
   `pipeline_run_id` is kept** — it names exactly what it holds, taskValues are already
   namespaced by `taskKey`, and it is a load-bearing value wired into `notebook_init` +
   both scripts (renaming would be a §20 atomic migration for no real gain). The init
   **task_key must stay `init_pipeline_log`**.
3. **`ingestion_log` write idiom** — **Resolved.** No IDENTITY columns anywhere in the
   audit DDL. (IDENTITY was tried first in vinoworld and caused conflicts — see note.)
   So **every** insert-only audit write uses
   `createDataFrame(schema=…).write…mode("append")` and generates its STRING PK with
   `str(uuid.uuid4())`. Drop the `INSERT … SELECT` variant entirely.
4. **`download_sources` step fields** — **Resolved / accepted as proposed in §6:**
   `rows_read` = files attempted, `rows_written` = files landed, `target_table = None`,
   `layer = "bronze"`.

> **Gotcha recorded (CLAUDE.md §19):** `GENERATED ALWAYS AS IDENTITY` audit PKs were
> rejected after vinoworld hit conflicts with them. Audit PKs are application-generated
> UUID strings (`STRING NOT NULL`, `str(uuid.uuid4())`), which keeps `createDataFrame`
> append valid on every audit table and sidesteps the IDENTITY write-path conflicts
> (IDENTITY columns can't be written via `createDataFrame` — they force `INSERT … SELECT`
> with the column omitted, and collide across MERGE / re-run paths).

---

## 10. Implementation Contract — guardrails for `/sc:implement`

Normative. If any item conflicts with §1–§9, this section wins; raise it.

1. **`audit_schema` is an explicit parameter** on every `pipeline_logging`
   function (2nd positional, after `spark`). **No `configure()`, no module global
   `_AUDIT_SCHEMA_NAME`, no `_audit()` helper.** Delete them.
2. **`STATUS_*` constants live only in `pipeline_logging.py`** (all five). Remove
   the inline copies from `notebook_init` and the private `_STATUS_SUCCEEDED`;
   `notebook_init` imports and re-exports the five names.
3. **init/finalize stay `spark_python_task`** (Verified to run on serverless). They
   compute `audit_schema = f"{sys.argv[2]}.audit"`, pass it explicitly, and **drop
   the `configure` import**. `init` requires `sys.argv[2]` (catalog) — raise if
   absent; **no `vinoworld` / `marketpulse` hardcoded default that could mis-route
   writes**. `PIPELINE_NAME` = `"marketpulse_pipeline"`.
4. **Error contract by tier:** `pipeline_log_upsert`, `pipeline_log_finalize`,
   `pipeline_step_log_upsert` **may raise**; `ingestion_log_insert`,
   `transform_detail_log_insert`, `download_log_insert` **swallow and return
   `{"status","error_message"}`** (never abort a committed data write — §11.4/§12).
5. **`StepLog` recorder class** is the canonical notebook step-logging surface (NOT
   a context manager — cells must stay separately runnable, §7). Constructor opens
   `RUNNING`; `.succeed()` / `.no_files()` / `.fail(exc)` close the row by MERGE on
   the same `step_log_id`. `dbutils` is a parameter, never a global. Each work cell
   ends with `except Exception as e: step.fail(e); raise`; cells that may
   `dbutils.notebook.exit()` call it OUTSIDE the try (flag inside, exit after) and
   call `step.no_files()` immediately before exiting. Success is closed explicitly
   with `step.succeed()`. (Corrected 2026-05-30: there is no `dbutils.NotebookExit`
   class; the old guard was a no-op — see §9.1 and `.claude/project/gotchas.md`.)
6. **`download_sources.ipynb` writes a `pipeline_step_log` row** via `StepLog`
   (§6 mapping) so download failures reach `pipeline_log_finalize`.
7. **Reuse `Utils.normalize_aware_datetime`** for tz normalization. Do not
   re-introduce `_to_utc_aware`.
8. **`StructType` order/types mirror `ddl/audit_ddl.py`** for every table
   (CLAUDE.md §11.1). The live table is `pipeline_log` (not `pipeline_run_log` —
   fix any stale docstring).
9. **Module hygiene (CLAUDE.md §12):** imports at top (`from delta.tables import
   DeltaTable`, `uuid`, `datetime`/`timezone`); no module-level side effects;
   `spark`/`dbutils` only ever parameters.
10. **Convention change is explicit:** adopting `StepLog` (§7) requires updating the
    §10 notebook cell-order guidance in this project's `.claude/CLAUDE.md` to describe
    the `StepLog` open/close + 2-line `except` pattern (cell granularity unchanged). Do
    this in the same change set and call it out; do not silently diverge (CLAUDE.md §2).
    (The shared `databricks/.claude/CLAUDE.md` is out of scope — outside this repo.)
11. **Validation before done:** `databricks bundle validate --target user` passes;
    deploy and run `download_sources` (init → download → and, if wired, finalize)
    to confirm the run row opens and the step row closes (`SUCCEEDED`, and `NO_FILES`
    on an empty source folder).

---

## 11. Confidence summary

| Claim | Grade | Basis |
|---|---|---|
| `spark_python_task` runs on Free-Edition serverless | **Verified** | The init task executed to its import line (this session's traceback). |
| Explicit `audit_schema` is the marketpulse-canonical pattern | **Verified** | `download_log_insert`/`download_log_last_sha256` already use it. |
| `pipeline_log` is the live table name | **Verified** | `ddl/audit_ddl.py` `create_audit_tables`. |
| Serverless non-notebook tasks need `environments` + `environment_key` | **Verified** | Databricks bundle docs (prior session) + the deployed `job_download_sources.yml`. |
| `StepLog` + per-cell `except`, with `dbutils.notebook.exit()` OUTSIDE the try, handles `NO_FILES` correctly | **Verified** | Confirmed via the `step_log_test` run (§9.1); the old `dbutils.NotebookExit` guard was a no-op and was dropped. |
| `createDataFrame` append valid for every audit table | **Verified** | No IDENTITY columns in the audit DDL; UUID-string PKs (§9.3). |
