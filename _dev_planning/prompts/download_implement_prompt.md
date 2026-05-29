/sc:implement WS0 of the marketpulse data-acquisition framework, against the approved design doc.

THE SPECIFICATION IS NORMATIVE
- The spec is `_dev_planning/design_docs/data_acquisition_framework_design.md`. Read it in full before writing anything.
- **§16 "Implementation Contract" is the load-bearing checklist.** Every one of its 14 rules is a hard constraint; violating one is a defect even if the code "works."
- **§16 wins on any conflict with §1–§15. If you find such a conflict, STOP and raise it — do not pick a side.**
- This prompt governs *how* you implement. It does not restate the design. Where this prompt and the spec disagree, the spec's technical content governs; where behavior/scope/sequencing is concerned, this prompt governs.

READ-FIRST (before writing a single line)
These pin the interfaces and conventions you must match. Do not infer their contents:
- `databricks_code/libs/notebook_init.ipynb` — the composition root; owns CATALOG, RAW_FILES/RAW_*, AUDIT, STATUS_*, PIPELINE_RUN_ID, spark, dbutils.
- `databricks_code/libs/pipeline_logging.py` — the functional logging seam (currently a stub). WS-D extends it; do not refactor it.
- `AUDIT_DDL.py` — existing audit DDL; `download_log` is specified in spec §9 and added here in WS-D.
- `databricks_code/libs/catalog_setup.py` — the existing module + `_run_ddl` pattern to match.
- `databricks_code/databricks.yml` — bundle/target/catalog/variable conventions.
- The four source READMEs in `_dev_planning/datasource_descriptions/{fred,zillow,fhfa,realtor}_README.md`.

BEHAVIORAL RULES (from .claude/CLAUDE.md — non-negotiable)
- **Safety Protocol (§3):** produce a numbered plan and STOP for approval before writing code. After approval, execute only the approved steps, summarize, and stop again.
- **Pause on ambiguity.** If anything is unclear or a decision is missing, ASK. Do not fill gaps with assumptions. This is the single most important instruction.
- **Confidence-grade** every Databricks-specific claim (Verified / Projected / Guessing). Do not ship anything graded Guessing — verify via WebFetch or a probe first.
- **Match existing patterns (§5).** Mirror the closest existing analog (catalog_setup style, pipeline_logging signatures). Do not normalize a minority pattern to the majority silently.
- **Centralize load-bearing values (§6).** No hardcoded catalog/schema/path/status strings; derive from notebook_init constants or module-top UPPER_SNAKE_CASE constants.

ANTI-DRIFT — HARD CONSTRAINTS (these are the traps; treat as DO-NOT)
1. Entry point is a **`notebook_task` whose cell 1 is `%run "../../libs/notebook_init"`** — NOT a spark_python_task and NOT a wheel. (spec §8.1, §8.2)
2. Logging is **functional** — `download_log_insert` / `download_log_last_sha256` surfaced as a two-callable `DownloadJournal`. **No logger class hierarchy.** (spec §16.10)
3. Scratch dir = `ctx.scratch_dir`, default `tempfile.gettempdir()`. **Never hardcode `/local_disk0`.** (spec §16.8)
4. `source_url` logged to `download_log` is the **key-free `canonical_url`** — strip FRED `api_key`. (spec §16.5)
5. Batch policy is **abort-on-first-failure**, sequential, one journal row per attempted file. **No continue-and-collect, no concurrency.** (spec §16.3, §16.12)
6. Header validation is **PREFIX match, CSV only**; xlsx/json are opaque. (spec §16.6)
7. The package imports neither `notebook_init`, `dbutils`, nor a live `SparkSession` at module load — they arrive only as arguments. Must unit-test with no Databricks present. (spec §16.1)
8. `PIPELINE_RUN_ID` is **assumed present** (dummy "LOCALDEV" locally); the package never mints it. (spec §16.9)

PARKED — DO NOT TOUCH
- `init_pipeline_run_log.py` is vinoworld-drifted (imports `pipeline_log_upsert`/`configure`/`STATUS_RUNNING` not in marketpulse's stub; `vinoworld` default). This is NOT download-framework work. WS-D adds ONLY the two `download_log_*` functions to `pipeline_logging.py`. (spec §13)
- `wide_to_long` vendoring, Bronze parsing, XLSX banner handling, job scheduling — all out of scope (spec §13).

SCOPE GATE
- Implement **WS0 (Foundations) ONLY** in this pass — the types, Protocols, factory skeleton, and module-top constants per spec §12. WS0 blocks everything; it must land and be reviewed before the A–F band.
- After WS0 is approved and committed, STOP and await direction before starting WS-A…F.
- Tests live at `marketpulse/tests/data_fetch/` (outside the bundle root); no network, no SparkSession, inject fakes. (spec §16.13)

DELIVERABLE FOR THIS PASS
A numbered implementation plan for WS0 — files to create, the interfaces/types each will contain (matching spec §5 and §16 exactly), and the local test scaffold — then STOP for approval. No code until the plan is approved.
