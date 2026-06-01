# Weather Sources — File→Bronze Load Process Design

**Scope:** the data-file → Bronze-table load step for the two weather/hazard sources,
consistent with the project's Medallion conventions. The DDL is already built
(`databricks_code/libs/ddl/weather_data.py`); this designs the **loaders** that populate
those tables. Silver/Gold (station→county mapping, CBSA rollup, blending) remain out of
scope.

**Inputs (already landed by the annual `weather_download` job):**
- `raw.fema_nri/nri_counties.csv` — 3,232 rows × 467 cols (ArcGIS-sourced; all source
  columns + `OBJECTID`/`Shape__*` artifacts).
- `raw.climate_normals/_processed/normals_stations/` — Parquet, 15,493 US rows × 44
  all-`STRING` cols (the normalize step's output; hyphenated measure names + the
  `comp_flag_`/`years_` companions).

**Targets (DDL done):**
- `bronze.fema_nri_counties` — 31 data + 3 audit, all `STRING`, per-column `COMMENT`.
- `bronze.climate_normals_stations` — 18 data + 3 audit, all `STRING`, per-column `COMMENT`.

**Template:** both loaders follow the canonical `bronze/load_fhfa.ipynb` cell order
(§10/§10.1): `%run notebook_init` → constants → `StepLog` open → per-file/schema validation
→ read + audit columns → MERGE + row-count assertion + `ingestion_log`. Two new notebooks:
`bronze/load_fema_nri.ipynb`, `bronze/load_climate_normals.ipynb`.

---

## 1. Decision — Column scope: the curated selection, all-STRING

Already decided + reviewed (READMEs' "Selected columns for ingestion"):
- **NRI** = 31 (4 identity + 7 composite + 10 hazards × {score, rating}). The full 467-col
  CSV stays in the Volume as the fidelity record; Bronze carries the analytical subset. The
  composite 7 = risk {score, rating}, `eal_valt`, sovi {score, rating}, resl {score, rating}
  — every index a uniform score+rating pair (`sovi_score`/`resl_score` added 2026-06-01; see §10.4).
- **Climate Normals** = 18 (5 identity + 13 measure NORMAL values). The `comp_flag_`/`years_`
  companions are dropped (no reporting use; remain in `_processed` if a QC pass is ever
  wanted).

Bronze stays all-`STRING`, no casting (CLAUDE.md §11.1); casting is Silver's job.

---

## 2. Decision — NRI read: all-string-by-header + select-by-name (467-col deviation)

`load_fhfa` reads with an **explicit `StructType` of every source column** (12 fields) and
validates the header by **exact equality**. That does **not** scale to NRI's 467 columns,
and the 29 we want are scattered through them. So the NRI loader deviates (recorded per §18):

- **Read** `spark.read.format("csv").option("header","true").option("inferSchema","false")`
  → all 467 columns as `STRING`, keyed by header **name**. *This is not `inferSchema` — it is
  the opposite: type inference is explicitly disabled, every column is `STRING`, no guessing.
  The §11.1 intent (never let Spark infer types) is satisfied; reading by name is also more
  robust than a positional schema (immune to source column reordering).*
- **Validate** the 29 required source columns are a **subset** of the actual header (fail on
  any missing), rather than exact 467-equality.
- **Select + rename** the 29 by name to the snake_case DDL names (`STCOFIPS`→`stcofips`,
  `HRCN_RISKS`→`hrcn_risks`, …). The `OBJECTID`/`Shape__*` artifacts and the ~438 loss-model
  columns are simply not selected.

**Required source columns (UPPER, in the CSV):** `STCOFIPS, COUNTY, STATEABBRV, POPULATION,
RISK_SCORE, RISK_RATNG, EAL_VALT, SOVI_SCORE, SOVI_RATNG, RESL_SCORE, RESL_RATNG,` and
`{HRCN,CFLD,IFLD,TRND,WFIR,ERQK,HAIL,SWND,HWAV,WNTW}_{RISKS,RISKR}` — a single-source-of-truth
constant in cell 2.

---

## 3. Decision — Normals read: from `_processed` Parquet, alias hyphen→snake, drop companions

The Normals loader reads the **normalize step's `_processed` Parquet**, not the raw tarball —
the same pattern as Zillow's Bronze reading the `_long` Parquet (the curated/normalized
dataset *is* the readable landing).

- **Read** `spark.read.parquet(RAW_CLIMATE_NORMALS_PROCESSED)` — Parquet is self-describing
  (44 all-`STRING` cols); no schema or `inferSchema` involved.
- **Validate** the 18 required columns are present in the Parquet schema.
- **Select + rename** the 5 identity + 13 measures, aliasing the **hyphenated** source names
  to snake_case (`ANN-TAVG-NORMAL`→`ann_tavg_normal`). Hyphenated names require backtick
  quoting in Spark (`F.col("\`ANN-TAVG-NORMAL\`")`). The 26 `comp_flag_`/`years_` companions
  are not selected.

---

## 4. Decision — Write strategy: MERGE on the natural key (Strategy A)

Both are **annual single-vintage snapshots**, so MERGE-on-natural-key (matching every other
Bronze table) is the fit:
- `fema_nri_counties` — MERGE key `stcofips` (one row per county).
- `climate_normals_stations` — MERGE key `station` (one row per GHCN station).

`WHEN MATCHED THEN UPDATE SET * / WHEN NOT MATCHED THEN INSERT *`. Re-running the same vintage
is a no-op (idempotent); a new vintage updates in place. Insert count comes from the MERGE
metrics dict (`num_inserted_rows`) with a post−pre fallback, then a row-count assertion — same
as `load_fhfa`.

**Orphan handling (DECIDED: upsert-only).** Plain upsert does not delete a county/station that
disappears from a new vintage (it would linger). Accepted — dropped counties/stations are rare
and harmless in Bronze, and this matches every existing loader. (If exact snapshot mirroring is
ever wanted, add `WHEN NOT MATCHED BY SOURCE THEN DELETE` — standard Delta.)

---

## 5. Decision — Audit columns + no archiving

- **Audit columns** (added at read, per §11.3): `source_file_path` = `F.col("_metadata.file_path")`,
  `inserted_ts` = `F.current_timestamp()` (never `datetime.now()`), `run_id` =
  `F.lit(PIPELINE_RUN_ID)` (STRING — the §18 run_id-as-STRING fix). `_metadata.file_path`
  works for both CSV and Parquet reads *(Projected for Parquet — confirm on first run)*.
- **No archiving** (deliberate, recorded per §18, same rationale as `load_fhfa`): annual
  full-snapshots, re-downloaded idempotently; archiving the raw file serves no purpose. (The
  §10 cell-7 archive step is omitted.)
- **`ingestion_log`** one row per ingested file, written AFTER `step.succeed()` and OUTSIDE
  the write `try` (the helper swallows its own errors so a logging hiccup can't roll back the
  MERGE) — verbatim from `load_fhfa`.

---

## 6. The loader notebooks (cell order, per §10.1)

Both mirror `load_fhfa` exactly:

| Cell | `load_fema_nri` | `load_climate_normals` |
|---|---|---|
| 0 md | source, strategy, no-archive note, DDL ref | same |
| 1 | `%run "../libs/notebook_init"` | same |
| 2 | constants: `SOURCE_SYSTEM="fema_nri"`, `SOURCE_PATH=RAW_FEMA_NRI`, `TARGET_TABLE={BRONZE}.fema_nri_counties`, `REQUIRED_SOURCE_COLS` (29), rename map, `MERGE_KEYS=["stcofips"]` | `SOURCE_SYSTEM="climate_normals"`, `SOURCE_PATH=RAW_CLIMATE_NORMALS_PROCESSED`, `TARGET_TABLE={BRONZE}.climate_normals_stations`, `REQUIRED_SOURCE_COLS` (18), hyphen→snake map, `MERGE_KEYS=["station"]` |
| 3 | `StepLog` open (RUNNING) | same |
| 4 | CSV present? + header **subset** validation; no-files exit OUTSIDE the try | Parquet present? + schema-has-required-columns validation; no-data exit OUTSIDE the try |
| 5 | all-string CSV read → select+rename 29 → audit cols; `step.rows_read` | Parquet read → select+rename 18 (backtick the hyphens) → audit cols; `step.rows_read` |
| 6 | MERGE on `stcofips` + row-count assert + `step.succeed()` + `ingestion_log` | MERGE on `station` + row-count assert + `step.succeed()` + `ingestion_log` |

---

## 7. Wiring (build-time, after design approval)

1. **DDL registration:** `from ddl.weather_data import create_weather_bronze_tables`; re-export
   in `ddl/__init__.py`; call it in `setup/catalog_ddl.ipynb` (after `create_bronze_tables`).
2. **Job:** a **new** `resources/job_weather_bronze.yml`, SEPARATE from `weather_download`.
   Rationale: `weather_download` takes several minutes (54 MB tarball + normalize), and the
   Bronze loaders are iterated frequently during dev — coupling them would re-run the slow
   download on every loader change. Structure (the two loaders are independent — different
   tables — so they run in parallel):
   ```
   init_pipeline_log
     ├─ load_fema_nri            (depends_on init_pipeline_log)
     └─ load_climate_normals     (depends_on init_pipeline_log)
          finalize_pipeline_log  (depends_on BOTH loaders, run_if: ALL_DONE)
   ```
   **Prereq the operator owns:** `weather_download` has already landed
   `raw.fema_nri/nri_counties.csv` and the `_processed` Parquet. **At production maturity**
   the two loaders can be folded into `weather_download` (one annual download→process→load→
   finalize job); kept separate now purely for dev iteration speed.

---

## 8. Medallion consistency check

- ✅ Bronze = raw, all-`STRING`, no casting; faithful to the landed file's (selected) columns.
- ✅ Full source fidelity preserved (the 467-col CSV + the tarball live in the Volumes).
- ✅ Audit columns on every row; idempotent MERGE on a natural key; per-file `ingestion_log`.
- ✅ Explicit schema / no type inference (NRI uses `inferSchema=false` all-string; Normals
  reads self-describing Parquet).
- ✅ Geo/measure semantics deferred to Silver (cast, trim the leading-space padding,
  station→county→CBSA mapping, rollup).

---

## 9. Confidence

- **Verified:** the `load_fhfa` loader pattern (read this session); the DDL targets;
  `WHEN NOT MATCHED BY SOURCE` is standard Delta; `inferSchema=false` yields all-`STRING`.
- **Projected (confirm on first run):** `_metadata.file_path` on a **Parquet** read; the MERGE
  metrics dict keys on this runtime (already `load_fhfa`-flagged); backtick handling of
  hyphenated Parquet column names (standard, but verify).
- **Guessing:** none.

---

## 10. Decisions (resolved)

1. **Orphan handling** — ✔ **upsert-only** (no `BY SOURCE DELETE`).
2. **Job placement** — ✔ **new separate `weather_bronze` job** for dev (download takes
   minutes; Bronze is iterated often). Fold into `weather_download` at the final/production
   stage.
3. Column scope, all-STRING, audit, naming — settled in §1–§5.
4. **SOVI/RESL score+rating reconciliation (2026-06-01)** — the original curated set took the
   *score* for the composite RISK and all 10 hazards (`RISK_SCORE`, `*_RISKS`) but the *rating*
   for SOVI/RESL (`SOVI_RATNG`, `RESL_RATNG`) — an inconsistent split with no stated reason, and
   one that left `weather_silver_gold_design` §1/§4 (scores-only serving, `sovi_score`/`resl_score`
   pop-weighted) with no source column to read. **Resolved: add `SOVI_SCORE`/`RESL_SCORE`
   alongside the retained ratings** (29 → 31 curated cols), making every index a uniform
   score+rating pair — consistent with the scores-only serving rule and with how RISK is carried.
   Both numeric scores already exist in the landed 467-col CSV (cols 31/34), so this is a
   **select-more-columns reload, not a re-download**: `_migrate_fema_nri` (in `weather_data.py`,
   mirroring `silver_ddl._migrate_dim_geo`) `ALTER ... ADD COLUMN`s them onto the existing table,
   then `load_fema_nri` re-MERGEs on `stcofips` to populate. The unused ratings stay as Bronze
   fidelity, exactly like the unused `risk_ratng`/`*_riskr`. (Swap-out was rejected: it would
   make SOVI/RESL the only indices lacking a rating — a different asymmetry.)

Nothing outstanding — the design is ready to implement.

*Design only. Next: `/sc:implement` builds the two loaders + the wiring, behind the usual
plan/approve gate.*
