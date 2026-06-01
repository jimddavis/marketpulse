# Weather Sources — Silver → Gold Design (geography, rollup, serving)

**Scope:** model the two weather Bronze tables into the serving layer that the reporting
drill-down (Region → State → CBSA) consumes, consistent with the project's Medallion
conventions and the housing facts. Covers the conformed geography, the Silver conform/rollup,
and the Gold serving tables. The download + Bronze tiers are done
(`weather_sources_download_design.md`, `weather_bronze_load_design.md`).

**Inputs (Bronze, on dev):**
- `bronze.fema_nri_counties` — county grain (`stcofips`), all-STRING: 29 cols incl. `population`,
  `eal_valt`, composite + 10 per-hazard `_risks`/`_riskr`.
- `bronze.climate_normals_stations` — station grain (`station`), all-STRING: 18 cols
  (`latitude`/`longitude` + 13 measures).

**Geography inputs (procured, in repo):**
- `scripts/list1_2023.xlsx` — OMB delineation: county FIPS → CBSA, `Central/Outlying County`,
  metro/micro. → the **county→CBSA bridge** (NRI path).
- `_dev_planning/TIGER_2025_cbsa/tl_2025_us_cbsa.shp` — 935 CBSA polygons, `CBSAFP` = `cbsa_code`,
  EPSG:4269. → the **station→CBSA** point-in-polygon (Normals path).

---

## 1. Resolved decisions (the design rests on these)

| # | Decision |
|---|---|
| **Q1 rollup layer** | station/county → **CBSA at Silver** (the conform step, matching the housing CBSA facts); **CBSA → State → Region at Gold** (serving). |
| **#1 coverage** | **CBSA-footprint** — State/Region weather aggregates over metros only, to align with the CBSA-only pricing data. |
| **Q6 serving model** | **Option C** — per-domain, per-level serving tables `gold.climate_profile` / `gold.hazard_profile`, stacked by `geo_level ∈ {region, state, cbsa}`, geo-keyed, **static** (no date). Correctness materialized in Gold. Climate and hazard kept separate (different aggregation semantics). |
| **Weighting input** | **From NRI** — county `population` summed to CBSA = `cbsa_population`; the weight for every intensive (weighted-mean) rollup. **No Census CO-EST download.** |
| **NRI score county→CBSA** | **population-weighted mean** (consistent with all other intensive rollups). *Resolved §6.1.* |
| **Ratings (`*_riskr`)** | **Dropped from the serving layer — scores only.** *Resolved §6.2.* |

**Aggregation rule per measure family** (the load-bearing correctness):

| Measure family | Type | Rollup rule (all levels) |
|---|---|---|
| NRI `eal_valt` (dollars), `population` | extensive | **SUM** |
| NRI risk scores (`*_risks`, composite `risk_score`, `sovi`/`resl`) | intensive (percentile) | **population-weighted mean** |
| NRI ratings (`*_riskr`, …) | categorical | **dropped** — scores-only serving (resolved §6.2); cut points stay in the tech-doc PDF if ratings are wanted later |
| Climate normals (temps, precip, snow, degree days) | intensive | station→CBSA = **mean-of-stations**; CBSA→State/Region = **population-weighted mean** |

---

## 2. Conformed geography

The drill-down needs a `region → state → cbsa` hierarchy shared by weather *and* housing.
`dim_geo` already carries `cbsa_code`, `primary_state`, `state_list`. Two additions (same
enrichment pattern as the existing `household_rank` from `bronze.realtor`):

- **`census_region`** — NE / MW / S / W, from a static `primary_state → Census region` lookup
  (50 states + DC + territories). A small seed/constant.
- **`cbsa_population`** — `SUM(bronze.fema_nri_counties.population)` per CBSA. The shared weight
  for *all* intensive State/Region rollups (weather and housing). Enrich during `seed_dim_geo`
  (or a dedicated step), mirroring `household_rank`.

**Two reference crosswalk builds (offline, seeded to the `reference` Volume — like the existing
crosswalks):**

1. **County→CBSA bridge** (`county_to_cbsa.csv`: `stcofips, cbsa_code`) — a ~5-line extension to
   `scripts/build_crosswalk.py` emitting county-grain rows from the same `list1_2023.xlsx`
   DataFrame it already parses (dedup the 2 near-duplicate counties). Used by the **NRI** Silver
   rollup. `stcofips` format already matches NRI exactly.
2. **Station→CBSA crosswalk** (`station_to_cbsa.csv`: `station, cbsa_code`) — a **new** offline
   geopandas script: read `bronze.climate_normals_stations` lat/lon (or the NCEI inventory),
   reproject to EPSG:4269, point-in-polygon `sjoin(predicate="within")` against the TIGER CBSA
   shapefile → `station, CBSAFP`. Stations outside any CBSA drop out (rural — expected).
   *(geopandas/GIS stack confirmed installable via `uv`; runs offline, NOT on Databricks.)*

Both crosswalks are static reference data (stations/counties don't move; CBSA vintage frozen) →
seed to `reference`, never a runtime spatial join (Sedona-on-serverless avoided).

---

## 3. Silver — conform + roll up to the CBSA atom

Two new Silver facts at **CBSA grain** (geo-keyed, **no date** — static characteristics),
matching the housing facts' `geo_key` join and the project's cast/quarantine pattern.

### `silver.fact_fema_hazard_cbsa` (one row per CBSA)
- Read `bronze.fema_nri_counties`; cast `population`→BIGINT, `eal_valt`/scores→DOUBLE (trim, cast
  via `double` to dodge ANSI `CAST_INVALID_INPUT`); quarantine bad casts (`cast_failed:<col>`).
- Join the **county→CBSA bridge**; counties with no CBSA drop (quarantine `unmatched_geography`
  only if a county we expected is missing — rural counties dropping is normal, not quarantine).
- Group by CBSA: `eal_valt`/`population` **SUM**; the intensive scores **population-weighted mean**
  (`SUM(score*population)/SUM(population)`) — composite `risk_score`, the 10 per-hazard `*_risks`,
  and `sovi_score`/`resl_score`. Ratings (`*_riskr`, `sovi_ratng`, `resl_ratng`) are **not**
  carried — scores-only. (`sovi_score`/`resl_score` come from the reconciled NRI Bronze — see §6.5.)
- `geo_key` via `dim_geo` on `cbsa_code`. Audit `inserted_ts`/`updated_ts`. Value columns COMMENTed.

### `silver.fact_noaa_climate_cbsa` (one row per CBSA)
- Read `bronze.climate_normals_stations`; cast the 13 measures→DOUBLE (trim the leading-space
  padding first); quarantine bad casts.
- Join the **station→CBSA crosswalk**; group by CBSA: **mean-of-stations** for every measure.
- `geo_key` via `dim_geo`. Audit + COMMENTs.

**Quarantine** reuses the consolidated `silver.quarantine` (`source_system` = `fema_nri` /
`climate_normals`), per the existing pattern — no silent drops.

*(The CBSA atom is the Silver conformed grain, exactly like the housing Silver facts; the
station→CBSA and county→CBSA rollups are the conform step.)*

---

## 4. Gold — the level-aware serving tables (Option C)

Two stacked serving tables. `geo_id` is the natural id of the level (`cbsa_code`, state postal,
region name); `geo_level` discriminates.

### `gold.climate_profile`
```
geo_level   STRING   -- 'region' | 'state' | 'cbsa'
geo_id      STRING   -- region name / state postal / cbsa_code
geo_name    STRING   -- display label
<13 climate measures, DOUBLE>          -- ann_tavg_normal, jja_tmax_normal, ann_snow_normal, ...
cbsa_count  INT      -- metros covered (1 at cbsa level) — conveys footprint
inserted_ts / updated_ts
PK (geo_level, geo_id)
```

### `gold.hazard_profile`
```
geo_level, geo_id, geo_name
risk_score DOUBLE, eal_valt BIGINT, sovi_score, resl_score, <10 hazard *_risks DOUBLE>
population BIGINT          -- summed metro population in scope
cbsa_count INT
inserted_ts / updated_ts
PK (geo_level, geo_id)
```

**Build (from the Silver CBSA atoms + `dim_geo` hierarchy):**
- `cbsa` rows = pass through the Silver CBSA atoms.
- `state` rows = aggregate CBSA atoms grouped by `dim_geo.primary_state` (multi-state CBSAs assigned
  to their primary state).
- `region` rows = aggregate CBSA atoms grouped by `dim_geo.census_region`.
- Per-measure rule from §1: dollars/population/counts **SUM**; everything intensive
  **population-weighted mean** using `dim_geo.cbsa_population`. (Climate at `cbsa` is the Silver
  mean-of-stations; State/Region re-weight those CBSA values by `cbsa_population`.)

The reporting UI filters `geo_level` to the drill-down level and joins `climate`+`hazard` on
`(geo_level, geo_id)`. Numbers are correct regardless of BI tool — the math lives in Gold.

---

## 5. Reference builds, wiring, jobs

- **Crosswalk builds (local, offline):** extend `build_crosswalk.py` for `county_to_cbsa.csv`;
  new `scripts/build_station_cbsa.py` (geopandas) for `station_to_cbsa.csv`. Upload both to the
  `reference` Volume (operator step, like the existing crosswalks). `notebook_init` constant for
  each path.
- **DDL:** `dim_geo` migration for `census_region` + `cbsa_population` — CREATE-IF-NOT-EXISTS is a
  no-op on an existing table, so a one-time `ALTER TABLE … ADD COLUMNS` (or recreate) is needed
  (resolved §6.3). New `silver.fact_noaa_climate_cbsa` / `fact_fema_hazard_cbsa` go in **`silver_ddl.py`**;
  new `gold.climate_profile` / `hazard_profile` go in **`gold_ddl.py`** (currently a stub) —
  *resolved §6.4: layer modules, not a separate weather module.*
- **Notebooks:** `silver/load_silver_noaa_climate.ipynb`, `silver/load_silver_fema_hazard.ipynb` (cast +
  rollup to CBSA, MERGE on `geo_key`); `gold/build_weather_profiles.ipynb` (the level stack).
- **Jobs:** a `weather_silver_gold` job (dev), separate from the Bronze job for the same
  iteration-speed reason (§7 of the bronze-load design). Prereq: the Bronze tables + the seeded
  crosswalks + the `dim_geo` enrichment.

---

## 6. Resolved (was open)

1. **NRI score county→CBSA rule** — **population-weighted mean**, consistent with every other
   intensive rollup. (Principal-county rejected.)
2. **Ratings** — **scores-only serving**; `*_riskr` dropped from Silver/Gold. The score→rating cut
   points remain in the tech-doc PDF (`_local_downloads/fema_nri/`) if a future UI wants chips.
3. **`dim_geo` migration** — proceed: a one-time `ALTER TABLE … ADD COLUMNS` (or recreate) for
   `census_region` + `cbsa_population`, since CREATE-IF-NOT-EXISTS won't alter the existing table.
4. **Module placement** — **layer modules**: `silver_ddl.py` (the two Silver facts) and `gold_ddl.py`
   (the two profiles). No separate weather DDL module at Silver/Gold.
5. **SOVI/RESL scores in Bronze (prerequisite)** — this design's `sovi_score`/`resl_score` were
   originally missing from `bronze.fema_nri_counties`, which had curated the *ratings*
   (`sovi_ratng`/`resl_ratng`) instead. Reconciled 2026-06-01: `SOVI_SCORE`/`RESL_SCORE` added to
   the curated NRI Bronze set (29 → 31) and back-filled from the already-landed CSV — no
   re-download. See `weather_bronze_load_design` §10.4. **Prereq for the hazard Silver fact:** the
   NRI Bronze reload must have run so the two score columns are populated.

---

## 7. Limitations (accepted)

- **CBSA-footprint:** a "South" value is its *metros'* value, not rural South — UI should label
  coverage as metro-based.
- **Multi-state CBSAs** roll into `primary_state` (NYC → NY); minor cross-state leakage.
- **Metro-pop-weighted** Region/State climate is a deliberate, defensible definition, not a
  physical regional mean.
- **Static** — no date dimension; weather is context beside the time-series housing facts, joined
  on geo only. (A future EpiNOAA time series would add a date grain — out of scope.)

---

## 8. Confidence

- **Verified:** the geography inputs (`list1` county/CBSA/Central-Outlying; TIGER 935 polygons =
  `cbsa_code`; geopandas via uv); the Silver `dim_geo`/fact/quarantine pattern; population present
  in NRI Bronze.
- **Projected (confirm on build):** `_metadata`-free Parquet rollup perf at 15k stations (trivial);
  the NRI score→rating cut points (in the tech-doc PDF); `dim_geo` ALTER vs recreate on dev.
- **Guessing:** none.

*Design complete — §6.1–§6.4 resolved. Next: `/sc:implement` the geography builds → Silver → Gold,
each behind the usual plan/approve gate.*
