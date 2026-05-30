/sc:implement the marketpulse audit-logging refactor, against the approved design doc.

THE SPECIFICATION IS NORMATIVE
- The spec is `_dev_planning/design_docs/audit_logging_refactor_design.md`. Read it in full before writing anything.
- **§10 "Implementation Contract" is the load-bearing checklist.** Every one of its 11 rules is a hard constraint; violating one is a defect even if the code "works."
- **§10 wins on any conflict with §1–§9. If you find such a conflict, STOP and raise it — do not pick a side.**
- §9 questions are RESOLVED (do not re-open them); their answers are part of the spec.

READ-FIRST (before writing a single line — do not infer their contents)
- `databricks_code/libs/pipeline_logging.py` — the module being refactored (currently: stubs for the step/ingestion/transform tiers + working `download_log_*`; a private `_STATUS_SUCCEEDED`; the run tier is MISSING).
- `databricks_code/libs/notebook_init.ipynb` — defines STATUS_* inline today and resolves PIPELINE_RUN_ID from the `init_pipeline_log` taskValue; it must re-export, not redefine.
- `databricks_code/libs/init_pipeline_run_log.py` — the spark_python init script to fix (drops `configure`, explicit audit_schema).
- `databricks_code/libs/ddl/audit_ddl.py` — the audit table DDL; your StructTypes mirror it exactly (table is `pipeline_log`).
- `databricks_code/bronze/download_sources.ipynb` — gets a StepLog row (§6 mapping).
- `databricks_code/resources/job_download_sources.yml` — already wires init (spark_python_task) + the `environments` block; finalize wiring goes here.
- REFERENCE ONLY (do not copy verbatim — adapt to marketpulse conventions): `vinoworld/databricks_code/libs/pipeline_logging.py` (bodies for `pipeline_log_upsert` / `pipeline_log_finalize`), `vinoworld/.../finalize_pipeline_run_log.py`, and `vinoworld/.../notebooks/bronze/brz_01_arancione_sales.ipynb` (StepLog usage shape). NOTE: vinoworld's `except dbutils.NotebookExit: raise` guard is SUPERSEDED — there is no such class; call `dbutils.notebook.exit()` OUTSIDE the try instead (`.claude/project/gotchas.md`). Do NOT copy that guard.

BEHAVIORAL RULES (from .claude/CLAUDE.md — non-negotiable)
- **Safety Protocol (§3):** produce a numbered plan and STOP for approval before writing code. After approval, execute only the approved steps, summarize, stop again.
- **Pause on ambiguity.** If anything is unclear or a decision is missing, ASK. Do not fill gaps with assumptions. Single most important instruction.
- **Atomic migration (§20):** the `audit_schema`-explicit signature change and the STATUS_* relocation touch multiple files. Grep every occurrence first, show the list, change them in ONE set, grep again to prove zero stragglers. **Half-migrated states are forbidden** — if it can't all land this session, don't start it.
- **Confidence-grade** every Databricks-specific claim (Verified / Projected / Guessing). Don't ship Guessing.
- **Match existing patterns (§5):** mirror `download_log_insert` (explicit audit_schema, swallow→dict) and `Utils.normalize_aware_datetime`. Do not normalize a minority pattern silently.
- **Centralize load-bearing values (§6):** no hardcoded catalog/schema/path/status strings.

ANTI-DRIFT — HARD CONSTRAINTS (these are the traps; treat as DO-NOT)
1. `StepLog` is a **recorder CLASS, not a context manager.** A `with`-block form was explicitly REJECTED (§7) because it can't span notebook cells. Cells stay separately runnable; each work cell ends `except Exception as e: step.fail(e); raise`.
2. **No `configure()`, no `_AUDIT_SCHEMA_NAME`, no `_audit()`.** `audit_schema` is an explicit 2nd positional arg on every function. Delete the old globals.
3. **STATUS_* (all five) live ONLY in `pipeline_logging.py`.** Remove the inline copies from `notebook_init` and the private `_STATUS_SUCCEEDED`; `notebook_init` imports + re-exports them.
4. **Error contract by tier:** `pipeline_log_upsert` / `pipeline_log_finalize` / `pipeline_step_log_upsert` MAY RAISE; `ingestion_log_insert` / `transform_detail_log_insert` / `download_log_insert` SWALLOW and return `{"status","error_message"}`. Leaf writes never abort a committed data write.
5. **No IDENTITY columns.** Every insert-only audit write uses `createDataFrame(schema=…).write…mode("append")` with a `str(uuid.uuid4())` STRING PK. No `INSERT … SELECT`.
6. **Reuse `Utils.normalize_aware_datetime`.** Do NOT re-introduce vinoworld's `_to_utc_aware`.
7. **init/finalize stay `spark_python_task`** (Verified on serverless). They compute `audit_schema=f"{sys.argv[2]}.audit"`, pass it explicitly, drop the `configure` import, and REQUIRE `sys.argv[2]` (raise if absent — no `vinoworld`/`marketpulse` default that could mis-route writes). `PIPELINE_NAME="marketpulse_pipeline"`.
8. **StructType order/types mirror `audit_ddl.py`.** Live table is `pipeline_log` (fix any `pipeline_run_log` docstring).
9. **Do NOT rename** the taskValue key `pipeline_run_id` or the init `task_key` `init_pipeline_log` — both load-bearing across notebook_init + scripts (§9.2).

SCOPE (this pass)
- `pipeline_logging.py`: add the five STATUS_*; implement `pipeline_log_upsert`, `pipeline_log_finalize`, `pipeline_step_log_upsert`, the `StepLog` class, and real `ingestion_log_insert` / `transform_detail_log_insert`; keep `download_log_*` unchanged; remove `configure`/globals/`_STATUS_SUCCEEDED`.
- `notebook_init.ipynb`: import + re-export STATUS_* and `StepLog` from `pipeline_logging`; remove inline literals.
- `init_pipeline_run_log.py`: fix per constraint #7.
- `finalize_pipeline_run_log.py`: CREATE it (port `pipeline_log_finalize` call shape from vinoworld, explicit audit_schema) and wire it into `job_download_sources.yml` as the last task — `depends_on: [download_sources]`, `run_if: ALL_DONE`, `environment_key: default`.
- `download_sources.ipynb`: open/close a `StepLog` row (§6 field mapping).
- Update §10 notebook cell-order in BOTH CLAUDE.md files to make the `StepLog` + 2-line `except` pattern canonical (cell granularity unchanged) — same change set, called out (§2 — not silent).
- Grep for any other caller of the changed signatures and migrate them atomically (§20).

VALIDATION GATE (before "done")
- `databricks bundle validate --target user` passes.
- Deploy + run `download_sources`: confirm the `pipeline_log` run row opens (RUNNING) and closes via finalize, the `pipeline_step_log` step row closes (SUCCEEDED), and an empty source folder yields a `NO_FILES` step row.

DELIVERABLE FOR THIS PASS
A numbered implementation plan — files touched, the exact function signatures and the StepLog class surface (matching §7/§8), the grep evidence for the atomic migration, and the job-wiring change — then STOP for approval. No code until the plan is approved.
