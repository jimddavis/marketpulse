# Zillow Wide→Long Transpose Step — Design

**Status:** Proposed (pending confirmation of the marked decisions).
**Scope:** Add one task to the `download_sources` job that transposes the three
Zillow wide CSVs into long-form **Parquet datasets**, and define where those land
and how the (future) Bronze loader finds them. **Out of scope:** creating Bronze
managed tables — that is the next increment.

---

## 1. Motivation

The three Zillow feeds are **wide** panels: 5 id columns + one date column per
month (currently 316, growing by one every monthly download). A wide schema can't
be loaded into a stable table — it changes shape every month. We already built and
verified (this session, full 321-column file → 282,820 long rows) the `wide_to_long`
module, which reshapes wide → long. This design wires that module into the pipeline
as a **discrete, observable job step** that runs right after the download, so the
transpose can be proven green in the job **before** any table work begins.

The long output is **materialized as a staging artifact** (a `_long` Parquet dataset
per feed) rather than reshaped inline at table-load time. See §7 for the tradeoff.

---

## 2. The three Zillow feeds

Source files (landed by `download_sources` into `RAW_ZILLOW` =
`/Volumes/{CATALOG}/raw/zillow/`):

| Feed | Landed wide file |
|---|---|
| ZHVI (home values) | `zhvi_home_values_metro_monthly.csv` |
| ZORI (asking rents) | `zori_asking_rents_metro_monthly.csv` |
| Inventory (for sale) | `inventory_for_sale_metro_monthly.csv` |

All share the same shape: id columns `RegionID, SizeRank, RegionName, RegionType,
StateName`, then a contiguous tail of `YYYY-MM-DD` date columns. `wide_to_long`
auto-detects the id/date split via its contiguous-tail rule — no per-feed config.

---

## 3. Decision 1 — Output format: **Parquet**, not CSV

The transpose writes **Parquet**, because:

- The long output is **typed** — `wide_to_long` emits `period_date` as `DATE` and
  `value` as `DOUBLE` (verified via the module's integration test + this session's
  smoke run). Parquet preserves those types; CSV would force the Bronze loader to
  re-infer or re-declare them.
- It's an **intermediate** artifact, not a human deliverable — columnar + compressed
  is the right call.
- Spark reads it back natively with `spark.read.parquet(path)` (schema embedded).

**Note on "files":** Spark writes a Parquet **dataset directory** (one or more
`part-*.parquet` files + a `_SUCCESS` marker), not a single named file — this is the
same directory-of-parts behavior covered earlier. The Bronze loader reads the
*directory*, so this is a non-issue. "Appending `_long`" therefore names the
**dataset directory**, not a lone file.

---

## 4. Decision 2 — Where the `_long` datasets are stored

**Proposed:** a dedicated `_long/` subfolder under the existing Zillow raw volume:

```
/Volumes/{CATALOG}/raw/zillow/                       ← RAW_ZILLOW (wide source CSVs land here)
    zhvi_home_values_metro_monthly.csv               ← wide (source of truth)
    zori_asking_rents_metro_monthly.csv
    inventory_for_sale_metro_monthly.csv
    _long/                                            ← RAW_ZILLOW_LONG (derived, this step)
        zhvi_home_values_metro_monthly_long/         ← Parquet dataset dir
        zori_asking_rents_metro_monthly_long/
        inventory_for_sale_metro_monthly_long/
```

Rationale:
- The `_`-prefixed `_long/` subfolder keeps **derived** data out of any glob over the
  raw landing zone (`raw/zillow/*.csv` never matches it), so wide source and long
  derived never collide.
- Reuses the **existing** `zillow` volume — **zero new DDL / volume provisioning**,
  which keeps this increment small. (A dedicated `staging` volume schema would be
  marginally cleaner — "raw = only what was downloaded" — but costs a `catalog_ddl`
  change + redeploy. Deferred; noted in §8.)
- The `_long` suffix on each dataset keeps it self-describing.

**New constant** (add to `notebook_init`, single source of truth):
```python
RAW_ZILLOW_LONG = f"{RAW_ZILLOW}_long/"
```

> **DECISION TO CONFIRM (4a):** `_long/` subfolder inside the `zillow` volume (proposed)
> vs. a dedicated `staging` volume vs. flat `_long`-suffixed dirs as siblings of the
> CSVs.

### 4.1 Archiving — none, by design

Nothing archives today: the per-source `archive/` folders (created by `catalog_ddl`
via `needs_archive`) and `Utils.archive_source_files` exist but are unused. This step
keeps it that way, deliberately:

- **Wide source files are NOT moved to archive after transposing.** The Zillow feeds
  are **single rolling full-snapshot files** under fixed names, overwritten by each
  monthly download. Moving the wide file would (a) **break within-period
  re-runnability** — download idempotency keys off the audit log (sha), not file
  presence, so a skipped re-download would leave the transpose with nothing to read —
  and (b) buy nothing, since revision capture is out of scope (no need to retain
  monthly vintages).
- **The `_long` datasets get no archive folder and are not archived** — derived,
  overwritten each run, fully reproducible from the wide file.
- The archive **move-after-load** pattern fits **accumulating-drop** sources (a new
  dated file each period), not full-snapshot rolling files. Revisit when/if such a
  source is added.
- *Optional, deferred:* if raw monthly **vintages** are later wanted for
  lineage/debugging, **copy** (not move) the wide file to `archive/{period}/` each
  run — out of scope here.

---

## 5. Decision 3 — How the Bronze process identifies the correct files

**By deterministic convention, derived from a shared registry — not by globbing.**

A single feed registry (defined once, e.g. in `notebook_init` or a small shared
module) is the source of truth for *both* the transpose step and the future Bronze
loader:

```python
# feed key -> (wide source filename, long dataset dir name)
ZILLOW_FEEDS = {
    "zhvi":      "zhvi_home_values_metro_monthly",
    "zori":      "zori_asking_rents_metro_monthly",
    "inventory": "inventory_for_sale_metro_monthly",
}
# wide source : f"{RAW_ZILLOW}{stem}.csv"
# long dataset: f"{RAW_ZILLOW_LONG}{stem}_long/"
```

The Bronze loader will read each feed's long dataset by its **constant-derived path**
(`spark.read.parquet(f"{RAW_ZILLOW_LONG}{stem}_long")`) — no directory listing,
no pattern matching, no ambiguity (CLAUDE.md §6/§9: paths derive from constants).
Format is Parquet, so the typed schema (`DATE`/`DOUBLE`) comes back without
re-inference.

*(Optional, future:* the transpose step can log each produced long-dataset path +
row count to an audit table for lineage, mirroring `download_log`. Not required for
this increment.)*

---

## 6. Decision 4 — Job modification (`job_download_sources.yml`)

Insert `transpose_zillow_long` between `download_sources` and `finalize`, and
re-point `finalize`'s dependency to it. New order:

```
init_pipeline_log → download_sources → transpose_zillow_long → finalize_pipeline_log (ALL_DONE)
```

```yaml
        - task_key: transpose_zillow_long
          depends_on:
            - task_key: download_sources          # ALL_SUCCESS (default): only transpose
          notebook_task:                           #   if the wide files actually landed
            notebook_path: ../bronze/load_zillow_long.ipynb
            base_parameters:
              catalog: "{{job.parameters.catalog}}"
              shared_lib_path: "{{job.parameters.shared_lib_path}}"

        - task_key: finalize_pipeline_log
          depends_on:
            - task_key: transpose_zillow_long      # was: download_sources
          run_if: ALL_DONE                          # unchanged — closes the run regardless
          spark_python_task: { ... unchanged ... }
```

- `transpose_zillow_long` uses **default `run_if: ALL_SUCCESS`** — it is data-dependent;
  if `download_sources` aborted, the Zillow files may be absent, so it must not run.
- `finalize` stays **`ALL_DONE`** so the `pipeline_log` row still closes if the
  transpose fails (it derives final status by scanning `pipeline_step_log`).
- It is a serverless **`notebook_task`**, so it needs **no** `environment_key`
  (only the `spark_python_task`s do — same as `download_sources`).

---

## 7. The transpose notebook — `bronze/load_zillow_long.ipynb`

Standard cell order + `StepLog` (CLAUDE.md §10). One `StepLog` row for the whole
step (`step_sequence=2`, `layer="bronze"`, `target_table=None` — output is files,
not a table; mirrors how `download_sources` logs a multi-file step).

| Cell | Purpose |
|---|---|
| 1 | `%run "../libs/notebook_init"` |
| 2 | Constants — `ZILLOW_FEEDS` registry; `RAW_ZILLOW`, `RAW_ZILLOW_LONG` |
| 3 | `StepLog` open (RUNNING) |
| 4 | **Loop feeds**: `df = read_and_unpivot(spark, f"{RAW_ZILLOW}{stem}.csv")`; assert `df.count() == wide_data_rows × date_cols`; `df.write.mode("overwrite").parquet(f"{RAW_ZILLOW_LONG}{stem}_long")`; accumulate `rows_read` / `rows_written` |
| 5 | `step.rows_read/written = …`; `step.succeed()` |

- **Write mode `overwrite`** — each monthly run fully replaces each `_long` dataset
  (full-snapshot semantics; idempotent — re-running a month reproduces identical output).
- **Error handling**: per-cell `except Exception as e: step.fail(e); raise`. No
  `dbutils.notebook.exit()` / no-files branch — a missing Zillow file here is a real
  failure (download is an upstream `ALL_SUCCESS` dependency), so let it fail loudly.
- **Column names**: the staging dataset preserves the **source** id-column names
  (`RegionID`, …); `snake_case` renaming is deferred to the Bronze loader, keeping
  this step a **pure reshape**.

> **DECISION TO CONFIRM (7a):** one notebook looping all three feeds with a single
> `StepLog` row (proposed) vs. one task/notebook per feed (finer-grained per-feed
> audit, more wiring). Recommend single-loop now; per-feed can come with the tables.

---

## 8. Design tradeoff — materialized staging vs. inline read-adapter

This design **materializes** an intermediate `_long` artifact: `wide raw CSV →
_long Parquet → (future) long Bronze table`. The alternative is an **inline
read-adapter**: call `wide_to_long` *inside* the Bronze table loader (`wide raw CSV
→ long Bronze table`), with no staging file.

Chosen: **materialized staging**, because it (a) lets the transpose run and be
verified as a discrete green job step **now**, before tables exist; (b) gives clean
separation of concerns; (c) leaves an inspectable intermediate. The cost is one
extra on-disk copy of the data.

**Future consolidation (flag, not now):** once the Bronze table loader exists, the
team may choose to fold the transpose into it (inline read-adapter) and retire the
`_long` staging datasets. That is a deliberate decision to revisit then — not a
silent redundancy.

---

## 9. Confidence summary

| Claim | Grade | Basis |
|---|---|---|
| `wide_to_long` reshapes the full 321-col file correctly | **Verified** | Smoke run this session: 895×316 → 282,820 rows, typed schema. |
| `read_and_unpivot` emits `period_date`:DATE, `value`:DOUBLE | **Verified** | Module integration test + smoke run. |
| `import wide_to_long` resolves on Databricks serverless | **Projected** | It's a `databricks_code/libs` module like `data_fetch` (which works); the job run will confirm. |
| Spark Parquet write to a `/Volumes/...` path works on serverless | **Projected** | Volume FUSE writes verified for `data_fetch`; Spark `.write.parquet` to a Volume path to be confirmed on the run. |
| Bundle task insertion + `run_if` wiring | **Verified** | Matches the existing `download_sources` / `step_log_test` job patterns. |

---

## 10. Open decisions (recap)

1. **(4a)** `_long/` subfolder (proposed) vs. dedicated `staging` volume vs. flat siblings.
2. **(7a)** Single looping notebook (proposed) vs. one task per feed.
3. Notebook filename: `bronze/load_zillow_long.ipynb` (proposed) — confirm.
4. New constant names: `RAW_ZILLOW_LONG`, `ZILLOW_FEEDS` — confirm.

After these are settled, implement via `/sc:implement` (or a numbered plan): add the
constant + registry, write `bronze/load_zillow_long.ipynb`, edit
`job_download_sources.yml`, deploy, and run the job to confirm green + the
`pipeline_step_log` row.
```
