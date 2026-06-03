# Deploy & populate a new target environment

End-to-end runbook to bring a **fresh** Databricks target (`dev` / `staging` / `prod`) from empty
to fully populated at the project's current state (Bronze + Silver; Gold not yet implemented).

Every job is **idempotent** (CREATE IF NOT EXISTS / MERGE on natural key), so re-running a step is
safe. Run the steps **in order** — the ordering encodes real data dependencies, not just preference.

---

## 0. Set target + catalog

`databricks bundle` commands run from **`databricks_code/`** (the bundle root). `databricks fs cp`
runs from the **repo root** (where `data/` lives). Pick the target and its catalog:

| Target | Catalog (`var.catalog`) | Mode |
|---|---|---|
| `user` (default) | `dev_marketpulse` | development |
| `dev` | `dev_marketpulse` | production |
| `staging` | `staging_marketpulse` | production |
| `prod` | `marketpulse` | production |

```bash
export TARGET=prod          # ← the target you are deploying
export CATALOG=marketpulse  # ← its catalog from the table above
```

---

## 1. Prerequisites (once per workspace)

1. **Databricks CLI authenticated** to the workspace `https://dbc-d0f295f4-d028.cloud.databricks.com/`.
   Confirm: `cd databricks_code && databricks bundle validate -t $TARGET` → `Validation OK!`

2. **FRED API key secret.** `download_sources` reads the FRED key via
   `dbutils.secrets.get(scope="marketpulse", key="FRED_API_KEY")`. The scope name is fixed
   (`marketpulse`) and **secrets are workspace-level, not per-catalog** — so if you already set this
   up for `dev` on this workspace, every other target reuses it; skip this step. Otherwise:
   ```bash
   databricks secrets list-scopes                       # is "marketpulse" already present?
   databricks secrets create-scope marketpulse          # if not
   databricks secrets put-secret marketpulse FRED_API_KEY --string-value "<your-fred-key>"
   ```
   (Only FRED needs a key. Zillow / FHFA / Realtor / FEMA-NRI / NOAA-Normals are keyless.)

---

## 2. Deploy the bundle

```bash
cd databricks_code
databricks bundle deploy -t $TARGET
```
Uploads notebooks + libs and registers every job for this target.

---

## 3. Create the catalog, schemas, volumes, and all tables

```bash
databricks bundle run -t $TARGET catalog_setup
```
Creates the catalog; the `bronze/silver/gold/audit/reporting/reference` schemas; the raw source
Volumes + the `reference/crosswalks` Volume; all audit, Bronze (housing + weather), and Silver
(housing + weather facts) tables. Gold is a no-op stub today. **Must finish before step 4** — the
reference Volume must exist before you upload crosswalks.

> Re-running `catalog_setup` also applies the idempotent column migrations
> (`_migrate_dim_geo`, `_migrate_fema_nri`) to any pre-existing tables.

---

## 4. Upload the reference crosswalks

These are committed reference data the seed/silver jobs read at runtime. Upload all five to the
`reference/crosswalks` Volume (run from the **repo root**):

```bash
cd ..   # repo root (where data/ lives)
for f in cbsa_master.csv zillow_region_to_cbsa.csv zillow_overrides.csv \
         county_to_cbsa.csv station_to_cbsa.csv; do
  databricks fs cp "data/crosswalks/$f" \
    "dbfs:/Volumes/$CATALOG/reference/crosswalks/$f" --overwrite
done
databricks fs ls "dbfs:/Volumes/$CATALOG/reference/crosswalks/"   # confirm all 5 present
```
Runtime consumers: `seed_dim_geo` reads `cbsa_master.csv` + `zillow_region_to_cbsa.csv` +
`county_to_cbsa.csv`; `load_silver_fema_hazard` reads `county_to_cbsa.csv`;
`load_silver_noaa_climate` reads `station_to_cbsa.csv`. (`zillow_overrides.csv` is build-time only
for `build_crosswalk.py`, but is uploaded to keep the reference set complete.)

---

## 5. Download raw source files (from the internet → raw Volumes)

```bash
cd databricks_code
databricks bundle run -t $TARGET download_sources    # Zillow, Realtor, FHFA, FRED  (+ zillow→long transpose)
databricks bundle run -t $TARGET weather_download     # FEMA NRI + NOAA Climate Normals (+ normalize)
```
Independent of each other (different Volumes) — order between the two doesn't matter, and they may
run concurrently in separate terminals. Both only require step 3.
`weather_download` is the slow one (≈ 54 MB tarball + normalize).

---

## 6. Load Bronze (raw files → Bronze tables)

```bash
databricks bundle run -t $TARGET bronze_load      # load_fhfa, load_realtor, load_fred, load_zillow
databricks bundle run -t $TARGET weather_bronze   # load_fema_nri, load_climate_normals
```
- `bronze_load` requires **step 5 `download_sources`** (reads the landed files + the Zillow `_long`
  Parquet the transpose produced).
- `weather_bronze` requires **step 5 `weather_download`** (reads `raw.fema_nri/nri_counties.csv` +
  the climate-normals `_processed` Parquet).
- The two are independent of each other.

---

## 7. Seed the conformed dimensions

```bash
databricks bundle run -t $TARGET seed_dims        # seed_dim_date, seed_dim_geo, seed_dim_fred_series
```
**Requires step 6 (both Bronze jobs) + step 4 (crosswalks).** `seed_dim_geo` enriches
`household_rank` from `bronze.realtor_metro_monthly` and `cbsa_population` from
`bronze.fema_nri_counties` (summed over `county_to_cbsa.csv`), and reads `cbsa_master.csv` +
`zillow_region_to_cbsa.csv`. `seed_dim_date`/`seed_dim_fred_series` have no upstream data
dependency but run in the same job.

---

## 8. Load Silver (Bronze + dims → conformed facts)

```bash
databricks bundle run -t $TARGET silver_load          # realtor, fhfa, zillow, fred  (housing facts)
databricks bundle run -t $TARGET weather_silver_gold  # fema_hazard, noaa_climate    (weather CBSA atoms)
```
- `silver_load` requires **step 6 `bronze_load` + step 7 `seed_dims`** (joins `dim_geo`/`dim_date`/
  `dim_fred_series`).
- `weather_silver_gold` requires **step 6 `weather_bronze` + step 7 `seed_dims`** (+ the
  `county_to_cbsa.csv` / `station_to_cbsa.csv` crosswalks from step 4).
- The two are independent of each other.

---

## 9. Gold — not yet implemented

`gold_ddl.py` is a stub and there is no Gold build job today. `weather_silver_gold` is named for the
future Gold task (`gold/build_weather_profiles.ipynb`), which will be appended to that job in a later
slice. **Nothing to run for Gold yet.**

---

## Dependency graph (what gates what)

```
deploy
  └─ catalog_setup ─┬─ (upload crosswalks) ───────────────────────────────┐
                    ├─ download_sources ─→ bronze_load ─┐                  │
                    └─ weather_download ─→ weather_bronze ┤                 │
                                                          ├─ seed_dims ─────┤
                                                          │                 ├─ silver_load
                                                          │                 └─ weather_silver_gold
                                                   (seed_dims also needs the crosswalks)
```

One-line order:
**deploy → catalog_setup → upload crosswalks → {download_sources, weather_download} →
{bronze_load, weather_bronze} → seed_dims → {silver_load, weather_silver_gold}**.

---

## Verification (after step 8)

Each `databricks bundle run` blocks and prints `TERMINATED SUCCESS` on success; a failure prints the
failing task. For a data-level check, query the new catalog (replace `<WAREHOUSE_ID>` with a SQL
warehouse in this workspace):

```bash
cat > /tmp/verify.json <<EOF
{"warehouse_id":"<WAREHOUSE_ID>","catalog":"$CATALOG","schema":"silver","wait_timeout":"50s",
 "statement":"SELECT 'dim_geo' t, count(*) n FROM dim_geo UNION ALL SELECT 'fact_fema_hazard_cbsa', count(*) FROM fact_fema_hazard_cbsa UNION ALL SELECT 'fact_noaa_climate_cbsa', count(*) FROM fact_noaa_climate_cbsa UNION ALL SELECT 'quarantine', count(*) FROM quarantine"}
EOF
databricks api post /api/2.0/sql/statements --json @/tmp/verify.json
```
Sanity baseline (matches `dev` at current state): `dim_geo` ≈ 935; `fact_fema_hazard_cbsa` = 935;
`fact_noaa_climate_cbsa` ≈ 924; `quarantine` should contain only genuine cast failures (no rows for
rural-drop counties/stations). Also confirm `pipeline_log` / `pipeline_step_log` in the `audit`
schema show `succeeded` for each job run.

---

## Notes

- **Idempotency:** every step is safe to re-run. Bronze loaders MERGE on natural keys; seeds MERGE on
  `cbsa_code` (keeping `geo_key` stable); Silver MERGEs on `geo_key`; quarantine writes
  delete-by-`source_system` then re-append.
- **Production mode** targets deploy under `/Workspace/Users/zieder0022@gmail.com/.bundle/...`; the
  `shared_lib_path` resolves at deploy time, and `catalog_ddl` self-discovers the libs path.
- **Annual vs monthly cadence:** `weather_download`/`weather_bronze` are annual-refresh sources kept
  in separate jobs from the monthly `download_sources`/`bronze_load`; for a first population you run
  all of them once, as above.
