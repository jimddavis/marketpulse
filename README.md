# Databricks ETL Project

A medallion (Bronze / Silver / Gold) ETL project on Unity Catalog.

## Where to start

- **Working conventions for this project**: see [`.claude/CLAUDE.md`](.claude/CLAUDE.md). That document defines the Safety Protocol, naming standards, notebook structure, write strategies, audit columns, and the skills available to use. Read it before generating or modifying any code.

- **Project-specific configuration** (catalog name, schemas, workspace user path, source data, runtime version) lives in a separate config file alongside `.claude/CLAUDE.md`. Until that file exists, treat such values as TBD and confirm with the project owner before committing them.

## Layout (expected, once scaffolded)

```
.
├── .claude/
│   └── CLAUDE.md                  # Project operating manual (generic)
├── README.md                      # This file
├── pipeline_orchestrator.ipynb    # Top-level runner (created at project root)
├── setup/
│   └── catalog_ddl.ipynb          # CREATE TABLE, schemas, volumes — run once
├── bronze/                        # Source-fidelity ingest notebooks
├── silver/                        # Typed, conformed dimensions + per-source facts
├── gold/                          # Business-rule joined facts and aggregates
├── utilities/                     # Ad-hoc exploration, audits
└── libs/                          # Bundle-deployed shared modules
    ├── notebook_init.ipynb        # Target-aware catalog resolution + constants
    ├── pipeline_utils.py
    ├── pipeline_logging.py
    └── catalog_setup.py
```

The orchestrator lives at the project root because `dbutils.notebook.run()` resolves paths relative to the calling notebook — child paths stay clean (`"bronze/source_name"` rather than `"../bronze/source_name"`).

## Conventions in one paragraph

Three-part Unity Catalog table names everywhere. Explicit `StructType`, never `inferSchema`. Audit columns on every managed table. Idempotent writes — one of MERGE / `txnAppId` / DELETE+reinsert per source, documented in a cell comment. Row-count assertion after every write. `try/except` with `except dbutils.NotebookExit: raise` before `except Exception`. Constants for any value that appears in more than one cell. See `.claude/CLAUDE.md` for the full spec.
