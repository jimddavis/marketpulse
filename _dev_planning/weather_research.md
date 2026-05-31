# Weather / Climate & Natural-Hazard Data Sources — Research Report

**Scope:** Identify and verify free, batch-downloadable US weather/climate and natural-hazard
datasets that fit the marketpulse architecture (Databricks medallion ETL, Unity Catalog, Free
Edition serverless, batch-only; CBSA-grained conformed `dim_geo` with an existing county-FIPS →
CBSA bridge from the OMB 2023 delineation).

**Method:** Web verification against primary source pages (NCEI, FEMA/OpenFEMA, USFS, PRISM,
Census), May 2026. Confidence is graded per claim. This is a **research report only** — no schema
design or implementation.

**Bottom line:** Two sources are clear Tier-1 wins for this architecture —
**FEMA National Risk Index** (all hazard categories, one county-FIPS CSV, pre-normalized) and a
**NOAA county-climate source** (Climate Normals *or* EpiNOAA/nClimGrid). **NOAA Storm Events**
is a strong Tier-2 add for actual event-frequency history. PRISM is **disqualified on licensing**;
NFHL and GHCN-Daily are **deferred** as heavy ETL with low marginal value over the Tier-1/2 set.

---

## Recommended shortlist (ranked by value-to-effort for *this* architecture)

| Rank | Source | Category | Grain | ETL effort | Why |
|---|---|---|---|---|---|
| **1** | **FEMA National Risk Index (NRI)** | Hazard | County-FIPS (+ tract) | **Low** | All 18 hazard types in one pre-normalized county CSV; joins the existing county→CBSA bridge directly. Single best hazard dataset. |
| **2** | **NOAA Climate Normals (1991–2020)** *or* **EpiNOAA / nClimGrid (county)** | Climate | Station *or* County-FIPS | **Low–Med** | Ready-made seasonal/annual temp, precip, snowfall, HDD/CDD. Normals = pre-aggregated but station-level (needs station→county); EpiNOAA = county-native but daily (needs aggregation). Pick one — see §2. |
| **3** | **NOAA Storm Events Database** | Hazard (events) | County-FIPS (+ NWS zone) | **Med** | Actual historical tornado/hail/wind/flood **counts per decade** — complements NRI's modeled scores. Yearly gzip CSVs. |
| 4 (opt) | **USFS Wildfire Risk to Communities** | Hazard (wildfire) | County (+ community) | **Low** | Direct county `.xlsx`. Mostly redundant with NRI's wildfire score; add only if wildfire detail is a priority. |
| 5 (opt) | **NOAA GHCN-Daily** | Climate (extremes) | Station | **High** | Raw daily station obs to derive days>95°F / freeze days. Only if EpiNOAA/Normals don't cover the extreme-day metrics wanted. |
| — | ~~PRISM~~ | Climate | 4 km / 800 m grid | — | **Disqualified:** terms prohibit redistribution + commercial use. |
| — | ~~FEMA NFHL~~ | Hazard (flood) | GIS polygons | Very High | **Deferred:** ~12 GB shapefiles, zonal GIS ETL; NRI already supplies a flood-risk score. |

**Supporting reference (needed for rollup):** Census **county population estimates** (CO-EST), a
small county-FIPS CSV, for population-weighted county→CBSA aggregation (§4).

---

## 1. Hazard sources

### FEMA National Risk Index (NRI) — Tier 1 ✅

- **Download / mechanism** *(Verified)*: OpenFEMA dataset page provides **direct CSV** (also File
  Geodatabase + Shapefile) for all US **counties** and **census tracts**, plus an OpenFEMA **API**
  endpoint. Landing: `https://www.fema.gov/about/openfema/data-sets/national-risk-index-data`;
  data-resources mirror under `hazards.fema.gov/nri/data-resources`.
- **Format / size** *(Verified)*: CSV (county file is small — one row per county, ~3,200 rows).
- **Grain** *(Verified)*: **County-FIPS keyed** (and tract). Joins the existing county→CBSA bridge
  with zero new geography work.
- **Temporal** *(Verified)*: Static vintaged release. Current = **December 2025 v1.20**. Refreshed
  roughly annually → belongs as a **reference seed**, not a monthly pipeline feed.
- **Variables** *(Verified)*: Composite risk + per-hazard scores/ratings for **18 hazards**:
  avalanche, coastal flooding, cold wave, drought, earthquake, hail, heat wave, hurricane, ice
  storm, inland flooding, landslide, lightning, strong wind, tornado, tsunami, volcanic activity,
  wildfire, winter weather. Each hazard exposes Risk Index score/rating + components (expected
  annual loss, social vulnerability, community resilience).
- **Auth** *(Verified)*: None. Public download + open API.
- **License** *(Verified)*: US federal work — public domain; free to redistribute.
- **Fit:** Highest value-to-effort of any source here. Covers hurricane, tornado, flood, wildfire,
  hail, high wind, earthquake, winter storm — i.e. the entire hazard goal — in one county CSV.

### NOAA Storm Events Database — Tier 2 ✅

- **Download / mechanism** *(Verified)*: Bulk **gzipped CSV** over HTTP/FTP at
  `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/`.
- **Format / size** *(Verified)*: One **details file per year**, naming
  `StormEvents_details-ftp_v1.0_dYYYY_cYYYYMMDD.csv.gz` (parallel `fatalities` and `locations`
  files per year). Coverage **1950 → 2026**.
- **Grain** *(Verified)*: Event-level. Small-area events (**tornado, thunderstorm wind, flash
  flood, hail**) are tagged by **county FIPS**; large-area events (heat, cold, drought, flood,
  tropical, winter) are tagged by **NWS forecast zone** — the zone-vs-county split is the main ETL
  wrinkle (zone events need a zone→county crosswalk or must be handled separately).
- **Temporal** *(Verified)*: Event time-series; new months appended continuously.
- **Variables** *(Verified)*: Event type, date, county/zone, magnitude, damages, injuries,
  fatalities → aggregate to **events-per-decade / damages** per county→CBSA.
- **Auth / License** *(Verified)*: None / public domain.
- **Fit:** Complements NRI — NRI is a *modeled* score; Storm Events is *observed history*. Moderate
  ETL: download N yearly gzips, filter to county-coded event types, aggregate, roll up.

### USFS Wildfire Risk to Communities — Tier 3 (optional)

- **Download** *(Verified)*: Direct county/community **`.xlsx`** at
  `https://wildfirerisk.org/wp-content/uploads/2026/04/wrc_download_20260415.xlsx` (dated filename;
  refreshed periodically). GIS rasters separately at the Forest Service Research Data Archive
  (RDS-2020-0016 / RDS-2020-0060).
- **Grain** *(Verified)*: Communities, tribal areas, **counties**, states. FIPS keying not confirmed
  on the page — likely derivable from county name+state if no FIPS column *(Projected)*.
- **Variables** *(Verified)*: Risk to Homes, Wildfire Likelihood, Risk Reduction Zones.
- **License** *(Projected)*: USFS product, expected public/open; terms not stated on the download
  page — confirm before redistribution.
- **Fit:** Low ETL (one spreadsheet) but **largely redundant** with NRI's wildfire score. Add only
  if you want wildfire-specific depth (e.g. burn probability, exposure) beyond NRI.

### FEMA National Flood Hazard Layer (NFHL) — Deferred ⛔

- **Download / format** *(Verified)*: GIS **shapefiles** (`.shp/.dbf/.xml`) per county/state via the
  Map Service Center (`https://msc.fema.gov/portal/advanceSearch`); also a national KMZ. Full
  national layer ≈ **12 GB uncompressed**.
- **Grain** *(Verified)*: Flood-zone **polygons** — requires spatial/zonal ETL to derive
  "% of homes in flood zone" per county.
- **Fit:** High-effort GIS work not aligned with a CSV/county batch pipeline, and NRI already
  delivers a flood-risk score. **Defer** unless flood-zone exposure becomes a first-class metric.

---

## 2. Climate sources

The key decision is **Climate Normals vs. EpiNOAA/nClimGrid** for the county climate profile.

### NOAA U.S. Climate Normals (1991–2020) — Tier 1/2 ✅

- **Download / mechanism** *(Verified)*: CSVs via NCEI **Web Accessible Folders**, organized
  by-station or by-variable. Product page:
  `https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals`; Quick Access:
  `https://www.ncei.noaa.gov/access/us-climate-normals/`.
- **Format / size** *(Verified)*: CSV. The **Annual/Seasonal** product is the relevant one — one
  compact value-set per station.
- **Grain** *(Verified, with caveat)*: **Station-level** (~thousands of GHCN stations). **No native
  county/CBSA aggregation** — needs a station→county (→CBSA) mapping step. This is the main ETL cost.
- **Temporal** *(Verified)*: **Static** 30-year normal (1991–2020 vintage), refreshed ~decadally →
  a **reference seed**.
- **Variables** *(Verified)*: Pre-computed **seasonal/annual temperature** (incl. max/min),
  **precipitation & snowfall totals**, **heating/cooling degree days**, growing-degree-days — i.e.
  exactly the "climate profile" goal, ready-made (no daily aggregation).
- **Auth / License** *(Verified)*: None / public domain.
- **Fit:** Best when you want **ready-made degree-days and seasonal averages** and are willing to
  build a station→county rollup (nearest-station or county-stations average).

### NOAA nClimGrid / EpiNOAA (county) — Tier 1/2 ✅ (climate alternative)

- **Download / mechanism** *(Verified)*: **EpiNOAA** is an analysis-ready **county-scale** daily
  time series derived from nClimGrid, on AWS S3:
  `https://noaa-nclimgrid-daily-pds.s3.amazonaws.com/index.html#EpiNOAA/` (also NCEI + R package).
  CSV, one file per region type per month.
- **Grain** *(Verified)*: **County-native** (county is one of the nine region types) — **no
  station→county mapping needed**, joins the existing bridge directly. (Base nClimGrid is a 5 km
  grid; EpiNOAA is the county roll-up.)
- **Temporal** *(Verified)*: Daily, **1951 → present**; preliminary refreshed every ~3 days, scaled
  (QC'd) every ~3 months. Variables: tmax, tmin, tavg, precip.
- **Trade-off vs Normals:** county-native (cleaner geography) but **daily** — you must aggregate to
  seasonal/annual normals yourself, and it lacks ready-made degree-days/snowfall. More compute,
  fewer derived fields.
- **Auth / License** *(Verified)*: None / public domain (NOAA Big Data Program).
- **Fit:** Best when **county-native geography** matters more than ready-made degree-days, or when
  you also want a true time series rather than a static normal.

> **Recommendation for climate:** If the dashboard wants a *static climate profile* (seasonal
> temps, annual precip/snow, HDD/CDD), **Climate Normals** gives the most fields with the least
> compute — accept the station→county step. If you'd rather avoid station mapping and/or want an
> actual time series, use **EpiNOAA**. Either is Tier-1-viable; don't load both.

### PRISM — Disqualified ⛔

- **Download** *(Verified)*: 4 km (and, since March 2025, 800 m) gridded data, free via FTP/web
  services at `https://prism.oregonstate.edu/`.
- **License** *(Verified)*: **Terms prohibit duplication/redistribution; commercial use prohibited
  without prior arrangement.** This is a hard blocker for a redistributable analytics app.
- **Grain:** gridded raster → zonal aggregation (different ETL paradigm). **Excluded on license
  grounds regardless of effort.**

### NOAA GHCN-Daily — Deferred (Tier 3)

- **Download** *(Verified)*: Per-station daily CSVs at NCEI (`by_station`), 1763→present, station
  grain, public domain.
- **Fit:** Heavy — raw daily obs across thousands of stations, station→county mapping, then derive
  extreme-day counts (days>95°F, freeze days, heavy-rain days). **Defer** unless those extreme-day
  metrics are specifically wanted and EpiNOAA daily data (which can produce similar county counts)
  doesn't suffice. EpiNOAA likely makes GHCN-Daily unnecessary.

---

## 3. Comparison matrix

| Source | Category | Native grain | County/CBSA path | Format | Cadence | Auth | License | ETL effort | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| FEMA NRI | Hazard (18 types) | County-FIPS + tract | **Direct** (bridge) | CSV / GDB / SHP + API | ~Annual vintage | None | Public domain | **Low** | **Tier 1** |
| NOAA Storm Events | Hazard events | County-FIPS + NWS zone | Direct (county events); zone xwalk for rest | CSV.gz / yr | Continuous | None | Public domain | Med | **Tier 2** |
| NOAA Climate Normals | Climate | Station | Station→county→CBSA | CSV (WAF) | Static (decadal) | None | Public domain | Low–Med | **Tier 1/2** |
| EpiNOAA / nClimGrid | Climate | **County-FIPS** (5 km grid base) | **Direct** (bridge) | CSV (S3) | Daily (3-day/3-mo) | None | Public domain | Med | **Tier 1/2** |
| USFS WRC | Wildfire | County / community | Direct (name; FIPS TBD) | XLSX + raster | Periodic | None | USFS (confirm) | Low | Tier 3 opt |
| GHCN-Daily | Climate extremes | Station | Station→county→CBSA | CSV | Daily | None | Public domain | High | Tier 3 defer |
| PRISM | Climate | 4 km / 800 m grid | Grid zonal agg | Grid (FTP) | Daily–monthly | None | **No redistribution** | High | **Excluded** |
| FEMA NFHL | Flood polygons | Polygon | Spatial zonal agg | SHP (~12 GB) | Periodic | None | Public domain | Very High | Deferred |
| Census CO-EST (support) | Reference | County-FIPS | Direct (bridge) | CSV | Annual | None | Public domain | Trivial | Support |

---

## 4. County → CBSA rollup — weighting consideration

All of these are county-grain (or roll up to county); CBSAs span multiple counties, so values must
be **aggregated county→CBSA**. The aggregation rule is a modeling decision per metric:

- **Risk scores (NRI) and climate averages:** **population-weighted mean** across a CBSA's counties
  is the most defensible (a metro's "felt" climate/risk tracks where people live), vs. the simpler
  **principal-county** (the CBSA's largest/central county) or **max** (conservative for risk).
- **Event counts (Storm Events):** **sum** across the CBSA's counties (events are additive), not a
  weighted mean.
- **Reference data required for weighting:** Census **county population estimates** —
  `CO-EST2024-ALLDATA` CSV, county-FIPS keyed, 2020–2024
  (`https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html`). Trivial
  to ingest; joins the existing bridge. *(Verified availability; exact column layout per the
  published file layout doc.)*

Note these are **geo-keyed CBSA characteristics**, not monthly facts — NRI and Climate Normals are
static per vintage, so they join housing facts on metro (geo) only, not on date. Storm Events is the
one genuinely time-series hazard source (aggregable to county×year/decade).

---

## 5. Confidence summary

- **Verified** (read on primary source pages this session): all download mechanisms, formats,
  grains, cadences, and licenses in the matrix above — NRI (OpenFEMA CSV county+tract, 18 hazards,
  Dec 2025 v1.20), Storm Events (yearly `.csv.gz`, 1950–2026, county/zone), Climate Normals (station
  CSV via WAF), EpiNOAA (county-scale daily CSV on S3), PRISM redistribution prohibition, NFHL ~12 GB
  shapefiles, USFS WRC county `.xlsx`, Census CO-EST CSV.
- **Projected** (not confirmed on-page, low risk): exact NRI/EpiNOAA column names; whether the USFS
  WRC spreadsheet carries a FIPS column vs. name-only; precise Storm Events zone→county handling;
  USFS WRC license text.
- **Not yet checked:** the exact OpenFEMA NRI API endpoint path and field dictionary (the bulk CSV
  is sufficient for batch ingest, so this only matters if you prefer the API over the file).

---

## 6. Sources

- FEMA NRI — OpenFEMA data set: https://www.fema.gov/about/openfema/data-sets/national-risk-index-data
- FEMA NRI — product page: https://www.fema.gov/flood-maps/products-tools/national-risk-index
- FEMA NRI — data resources: https://hazards.fema.gov/nri/data-resources
- FEMA NRI — technical documentation (Dec 2025 v1.20): https://www.fema.gov/sites/default/files/documents/fema_national-risk-index_technical-documentation.pdf
- NOAA Storm Events — FTP/bulk page: https://www.ncei.noaa.gov/stormevents/ftp.jsp
- NOAA Storm Events — CSV directory: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/
- NOAA Storm Events — bulk CSV format doc: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/Storm-Data-Bulk-csv-Format.pdf
- NOAA U.S. Climate Normals — product page: https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals
- NOAA U.S. Climate Normals — quick access: https://www.ncei.noaa.gov/access/us-climate-normals/
- NOAA nClimGrid-Daily / EpiNOAA — product page: https://www.ncei.noaa.gov/products/land-based-station/nclimgrid-daily
- NOAA nClimGrid / EpiNOAA — AWS Open Data: https://registry.opendata.aws/noaa-nclimgrid/ (S3: https://noaa-nclimgrid-daily-pds.s3.amazonaws.com/index.html#EpiNOAA/)
- NOAA nClimGrid-Monthly — Drought.gov: https://www.drought.gov/data-maps-tools/gridded-climate-datasets-noaas-nclimgrid-monthly
- PRISM — Oregon State: https://prism.oregonstate.edu/ (orders/terms: https://prism.oregonstate.edu/orders/)
- USFS Wildfire Risk to Communities — download: https://wildfirerisk.org/download/
- USFS WRC — Forest Service Research Data Archive: https://www.fs.usda.gov/rds/archive/catalog/RDS-2020-0016
- FEMA National Flood Hazard Layer: https://www.fema.gov/flood-maps/national-flood-hazard-layer (MSC: https://msc.fema.gov/portal/advanceSearch)
- NOAA GHCN-Daily: https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily
- Census county population estimates (CO-EST 2020–2024/2025): https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html

---

*Research report only — per `/sc:research` boundaries, no schema or implementation produced. Next
step is yours: `/sc:design` to model the chosen sources into Bronze/Silver, or pick the shortlist
to pursue.*

---

## Appendix A — Climate Normals station→county→CBSA mapping plan

*(Follow-up discussion. Addresses the "main ETL cost" caveat on Climate Normals in §2: the product
is station-level with no native county/CBSA aggregation.)*

**No download required to plan this.** The key fact that shapes the approach: the Normals CSVs
already carry each station's `LATITUDE`/`LONGITUDE` (station name, lat, lon, elevation are in the
per-station file header). So this is **not** a geocoding problem — it's a **point-in-polygon**
problem, solvable **once, offline, as a static reference build** — the same pattern already used for
`scripts/build_crosswalk.py` + the reference Volume. *(Station coords inline: Projected — high
confidence; confirm exact column names against one downloaded file before coding.)*

### Shape: a one-time static lookup, not a runtime spatial join

Stations don't move and the 1991–2020 normals are a frozen vintage → the mapping is **reference
data**. Build it locally with geopandas/shapely, emit a `station_id → county_fips` CSV, upload to
the reference Volume, seed it. No spatial library needed on Databricks serverless (right call —
Apache Sedona availability on Free-Edition serverless is unverified; avoid the dependency).

### Steps

1. **Station coordinates** — parse `LATITUDE`/`LONGITUDE` from the normals files, or pull the NCEI
   normals **station inventory** (small metadata file: id/name/lat/lon/state). One row per station,
   a few thousand rows.
2. **County polygons** — Census **TIGER/Line** or the lighter **cartographic boundary** county
   shapefile (one polygon per county FIPS). Consistent with the OMB/Census geography already trusted.
3. **Point-in-polygon** — spatial-join each station point to its containing county
   (`geopandas.sjoin(..., predicate="within")`) → `station_id, county_fips`. Offline, deterministic.
   The entire geospatial step.
4. **county_fips → CBSA** — join through the **existing county→CBSA bridge** (OMB `list1_2023.xlsx`).
   Stations in non-metro counties drop out (no CBSA) — expected.
5. **Aggregate stations → CBSA value** — a CBSA usually has several stations; collapse to one
   climate row per CBSA (rule below), which then joins `dim_geo` on `geo_key`.

### The two real decisions

- **Geospatial mechanism:** point-in-polygon (offline, deterministic, no API) **vs.** reverse-geocode
  API (FCC/Census geocoder, per-point network calls). **Point-in-polygon wins** — faster, offline, no
  rate limits, reproducible. The API path only makes sense if avoiding a shapefile entirely.
  *(Verified reasoning — standard GIS.)*
- **Station→CBSA aggregation** (this choice moves the numbers):
  - **Mean of all stations in the CBSA** — simplest; climate is fairly uniform within a metro.
    *Risk:* a high-elevation or coastal outlier station skews the average.
  - **Nearest station to the principal city** — one representative station; avoids elevation skew but
    discards coverage.
  - **Elevation/area-filtered mean** — drop outliers, then average.

  Recommended start: **mean-of-stations**, with elevation-outlier filtering as a refinement.
  Population-weighting (which matters for *risk*) is overkill for climate — climate doesn't vary by
  where people live within a metro the way risk does.

### Edge cases

- **Coastal/island stations** falling just outside a county polygon → add a nearest-county fallback
  (`sjoin_nearest`) for unmatched points.
- **Sparse metros** with zero stations → null climate profile (acceptable, or nearest-station
  fallback).
- **Coverage match** — keep only stations whose county rolls up to a CBSA in `dim_geo`; territory
  coverage (PR, etc.) depends on what's in the geo dimension.

### Confirm from one downloaded file before building

1. Exact coordinate column names + that the **Annual/Seasonal** product carries the wanted fields
   inline (seasonal temp, precip, snowfall, HDD/CDD).
2. Inline coords vs. separate station inventory (inventory is cleaner if it exists).
3. Station count and per-CBSA density (coverage sanity check).

**Net:** a ~half-day offline reference-build mirroring `build_crosswalk.py`, not a runtime burden —
keeps Climate Normals firmly Tier-1-viable.

---

## Appendix B — Rollup aggregation methods (county/station → CBSA)

*(Follow-up discussion. Expands §4: which algorithms correctly roll values up to a larger region.)*

**Core principle: the correct algorithm is dictated by the variable type, not chosen by taste.**
Spatial statistics splits variables into two families:

- **Intensive** (averages that don't add up): temperature, degree days, precipitation/snowfall
  *rates* → **spatially average**.
- **Extensive** (quantities that accumulate): event counts, dollar losses → **sum**.

The classic error is mixing these — *summing* precipitation across a metro's counties is
meaningless; *averaging* storm-event counts hides the real total.

### Established methods for intensive climate variables (low → high rigor)

| Method | What it does | When it's standard |
|---|---|---|
| **Simple mean** of stations/counties | Unweighted average | OK when within-metro variance is low (temperature usually is) |
| **Area-weighted mean** (areal interpolation) | Weight each county by its land-area share of the CBSA | Default geographically-faithful method |
| **Population-weighted mean** | Weight by population | **Official method for degree days** — NOAA/EIA publish population-weighted HDD/CDD by region; best for "human-experienced" climate *(Verified — established practice)* |
| **Thiessen / Voronoi polygons** | Each station owns a polygon; weight by polygon area in region | Classic hydrology method for areal precipitation from point data |
| **IDW / Kriging / regression interpolation** | Build a continuous surface from stations, then area-average | Research-grade; **PRISM** = elevation-aware regression; **nClimGrid** uses a published interpolation |

### Key insight for this project: source choice answers most of the "accuracy" question

The bottom row (the rigorous, elevation-aware interpolation) **is already done if you pick
EpiNOAA/nClimGrid instead of station Normals.** NOAA interpolated stations to a 5 km grid
(kriging-quality, elevation-aware) and area-averaged to **county**.

- **Station Normals path:** *you* own the station→region interpolation; a naive mean carries an
  **elevation bias** (a mountain station skews a valley metro — lapse rate is real). Needs at least
  area- or population-weighting to be defensible.
- **EpiNOAA path:** you inherit research-grade aggregation; the only remaining hop is
  **county→CBSA** (a handful of counties), so even a simple area-/population-weighted mean is
  defensible because the hard interpolation is already baked in.

→ "Which algorithm do I need?" is substantially answered by the **source choice**: EpiNOAA skips the
algorithmically hardest step.

### Two named caveats

- **MAUP (Modifiable Areal Unit Problem):** aggregated values shift with how the zone is drawn — an
  inherent property of any rollup. Can't be eliminated, only kept consistent (always roll up the
  same way).
- **Elevation / lapse rate:** dominant error source for temperature and snowfall. Methods that
  ignore elevation (simple/area-weighted station mean) misstate mountainous metros; elevation-aware
  interpolation (PRISM/nClimGrid) is why gridded products are more accurate.

### Hazard side (resolves §4 weighting cleanly via the same split)

- **NRI Expected Annual Loss ($) is *extensive* → SUM** across a CBSA's counties (dollar losses add
  up; exact, no weighting choice).
- **NRI Risk Index score/rating is a *percentile* → NOT additive.** Population-weight it (risk to
  people) or take principal-county / max (conservative). Never sum percentiles.
- **Storm Events counts are *extensive* → SUM.**

### Recommendation for the build

1. **Climate → use EpiNOAA** (rigor problem mostly disappears); county→CBSA via **population-weighted
   mean** (reuses the Census CO-EST file from §4), or area-weighted to avoid pulling population.
2. **Degree days → population-weighted** (matches official NOAA/EIA convention).
3. **NRI dollar losses & Storm Events → sum; NRI scores → population-weighted.**

This gives **one consistent weighting input (county population)** across climate *and* hazard, with
each metric aligned to its mathematically correct aggregation family.

---

## Appendix C — Normals vs EpiNOAA decision

*(Follow-up discussion. Resolves the climate-source choice flagged in §2 / the shortlist. Corrects
the assumption that the two are "comparable work, different inaccuracies" — they are not symmetric.)*

### Decisive functional gap: EpiNOAA has no snowfall (or ready-made degree days)

nClimGrid/EpiNOAA carries exactly four variables — **tmax, tmin, tavg, precipitation**
*(Verified)*. Therefore:

- **Snowfall → not available at all.** Snowfall is a stated dashboard goal; EpiNOAA cannot produce
  it. Climate Normals has snowfall totals (and snow depth) *(Verified)*.
- **Degree days / growing-degree-days → not present;** you'd derive them from daily temps. Normals
  ships HDD/CDD/GDD pre-computed.

For snowfall this is **present vs. absent**, not "different accuracy" — close to decisive on its own.

### The work is not balanced

| | Climate Normals | EpiNOAA |
|---|---|---|
| Download | Small — Annual/Seasonal is one consolidated, pre-computed set | **~360 county files** to build a 1991–2020 normal (30 yrs × 12 mo, county region type); more for a time series |
| Spatial rollup | Hard-ish: station→county→CBSA (Appendix A) | **Easy: county→CBSA only** (county-native) |
| Temporal aggregation | **None** — seasonal/annual normals pre-built by NOAA | **Hard, and per-variable** (avg temp, **sum** precip, **accumulate** degree days, **count** extremes) + must replicate NOAA's QC/completeness rules to be a true "normal" |
| Algorithm diversity | One weighting scheme (all intensive per-station values → weighted mean) | Per-variable temporal algorithm **+** spatial |

Asymmetry: **Normals front-loads the spatial problem and gives the temporal answer for free.
EpiNOAA gives the spatial answer for free but hands back the harder, more algorithm-diverse temporal
half — which is exactly the work NOAA already did and ships *as* the Normals product.**

### Accuracy is also not even

- **Climate Normals *is* the authoritative 30-year normal** (full NOAA QC + WMO completeness rules).
  Its only error for us is the station→region spatial step — bounded; metros are station-dense;
  elevation outliers are the main risk, manageable with weighting.
- **EpiNOAA-derived normals *approximate* that authoritative product.** Homemade temporal
  aggregation won't exactly reproduce NOAA's methodology → more work for a *less* authoritative
  number. EpiNOAA's gridding is more spatially accurate, but that edge is wasted on a static normal
  because it's given back through the temporal approximation.

### The decision reduces to one question

**Static climate *profile*, or *time series* / extreme-day metrics?**

- **Static profile** (seasonal temps, annual precip + snowfall, degree days beside pricing) →
  **Climate Normals.** Authoritative, ready-made, includes snowfall, one uniform spatial weighting;
  only cost is the one-time static station→county build (Appendix A).
- **Year-over-year trends, anomalies, or extreme-day counts** (days > 95°F, freeze days) →
  **EpiNOAA.** Then daily county-native data is the right tool and temporal work is the point — and
  you accept losing snowfall.

### Recommendation

For the goal as stated — a quality-of-life climate snapshot beside pricing — **use NOAA U.S. Climate
Normals.** Less total work (no temporal reimplementation, one weighting algorithm), authoritative,
and the only one of the two that delivers snowfall. Reserve EpiNOAA for a later phase *if* the
dashboard grows toward climate trends or extreme-event counts.

**Corrected premise:** not comparable-effort/different-error. **Normals is less work *and* more
authoritative for a normals profile; EpiNOAA only pulls ahead when a true time series is needed.**
