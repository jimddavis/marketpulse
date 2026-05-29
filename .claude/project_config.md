# project_config.md — marketpulse Databricks project values

This file documents the project's load-bearing values. Implementation lives in `libs/notebook_init.ipynb` and `databricks.yml`. Do not hardcode any value below in pipeline notebook code — read it from the `notebook_init`-injected constant.

---

## Databricks Code

All code to deploy to Databricks is in the folder datgabricks_code.  This prevents databricks cli from deploying other files in the project not related to the deployment.

## Databricks Host
The databricks.com account for this project

host: https://dbc-d0f295f4-d028.cloud.databricks.com/

## Catalog resolution (multi-target DAB)

`CATALOG` is NOT a static constant. With DAB + multi-target deployment, it is resolved at runtime by `libs/notebook_init.ipynb` in this priority order:

1. **Job runs** — bundle injects `${var.catalog}` into the `catalog` widget.
2. **Manual runs from a deployed notebook** — path inspection finds `/marketpulse/<target>/files/...` and looks up the catalog in `_target_catalog_map`.
3. **Fallback** — `marketpulse` (prod catalog).

### Target → catalog map (committed)

| Target    | Catalog               | Mode         |
|-----------|-----------------------|--------------|
| `dev`     | `dev_marketpulse`     | development  |
| `staging` | `staging_marketpulse` | production   |
| `prod`    | `marketpulse`         | production   |

**Sources of truth that must agree:**
- `databricks.yml` `targets:` variable overrides
- `libs/notebook_init.ipynb` `_target_catalog_map` dict

Renaming a catalog requires editing BOTH places. Run `.claude/commands/bundle-add-variable.md` for the canonical add-or-change recipe.

---

## Schemas (all derived from `CATALOG` at runtime)

```
BRONZE   = f"{CATALOG}.bronze"   # source-fidelity ingested tables
SILVER   = f"{CATALOG}.silver"   # typed, conformed dimensions + per-source facts
GOLD     = f"{CATALOG}.gold"     # business-rule joined facts and aggregates
AUDIT    = f"{CATALOG}.audit"    # pipeline_run_log, pipeline_step_log, ingestion_log, transform_detail_log
RAW      = f"{CATALOG}.raw"      # holds per-source Volumes; NO tables
```

---

## Raw landing Volumes

One Volume per source, all in the `raw` schema (vinoworld pattern, renamed from `datafiles`):

| Volume name | Filesystem path                       | Source        |
|-------------|---------------------------------------|---------------|
| `zillow`    | `/Volumes/{CATALOG}/raw/zillow/`      | Zillow Research |
| `realtor`   | `/Volumes/{CATALOG}/raw/realtor/`     | Realtor.com   |
| `fhfa`      | `/Volumes/{CATALOG}/raw/fhfa/`        | FHFA HPI      |
| `fred`      | `/Volumes/{CATALOG}/raw/fred/`        | FRED          |

Each Volume has an `archive/` subfolder for post-ingest file moves. Files are date-stamped at fetch time (`zhvi_home_values_metro_monthly_YYYY-MM-DD.csv`), then moved to `archive/` after a successful Bronze write. See `re_project_research/docs/designs/vinoworld_migration.md` "Follow-ups" #3.

`notebook_init.ipynb` exposes these as named constants: `RAW_ZILLOW`, `RAW_REALTOR`, `RAW_FHFA`, `RAW_FRED` (plus the root `RAW_FILES`).

---

## Workspace + runtime

```
WORKSPACE_USER_PATH = "/Workspace/Users/zieder0022@gmail.com/Marketpulse/"
```

Case-sensitive in Databricks. Verify this matches the actual deployed location before relying on it.

```
DATABRICKS_RUNTIME  = "18.1.x"
```

Probed 2026-05-28 via `spark.sql("SELECT current_version()")`:
`18.1.x-aarch64-photon-scala2.13`

- `aarch64` = Graviton (ARM64) architecture
- `photon` = Photon query engine enabled
- `scala2.13` = Scala 2.13

Free Edition serverless rolls forward automatically. This entry is observational, not pinned. 18.1 is **not** an LTS release; Databricks may roll the runtime forward without notice. If something behaves oddly, re-probe `current_version()` to check whether the runtime moved underneath you.

---

## Shared library path

Not a static constant — derived at runtime by `libs/notebook_init.ipynb` from the notebook's own path. After `databricks bundle deploy --target <target>`, the bundle deploys to:

```
/Workspace/<user>/.bundle/marketpulse/<target>/files/libs/
```

`notebook_init.ipynb` extracts this from `dbutils.notebook.entry_point.getDbutils()....notebookPath()`, exposes it as `shared_lib_path`, and inserts it into `sys.path` so `pipeline_logging` and `pipeline_utils` import correctly.

**Why this works for both job runs and manual runs:** the deployed path encodes the target name (`/marketpulse/dev/files/...`), so even when running a notebook by hand from the workspace UI (no job parameters), `notebook_init` can identify the target from its own path and pick the right catalog. See `libs/notebook_init.ipynb` cell 1 for the implementation.
