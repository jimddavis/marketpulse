# FEMA NRI + NOAA Climate Normals — Download Process Design

**Scope (per request):** design **the download process only** for the two
weather/hazard sources selected in `_dev_planning/weather_research.md` — FEMA
National Risk Index (county) and NOAA U.S. Climate Normals (1991–2020
Annual/Seasonal). Bronze/Silver modelling is **out of scope** here; this design
stops at "the bytes Bronze will read are landed and, for NOAA, normalized into a
readable shape."

**Guiding constraint:** *match the existing `data_fetch` framework*, don't invent
a parallel one. Per `manifest.py`, "adding a source = appending one `SourceSpec`
to `SOURCES` — no change to providers, runner, writer, or journal." We honor that
for NOAA (reuses `http_file`) and extend it minimally for FEMA (one new provider
class + one registry entry).

---

## 1. The two sources are asymmetric

| | FEMA NRI | NOAA Climate Normals |
|---|---|---|
| Native delivery | Paginated ArcGIS Feature Service (canonical `hazards.fema.gov` CSV is TLS-blocked from our env) | Single 54 MB `.tar.gz` of 15,616 ragged per-station CSVs |
| Download mechanism | **New** `arcgis_feature_service` provider (assemble pages → CSV) | **Existing** `http_file` provider (plain GET of the tarball + inventory) |
| Post-download work | None — lands as one clean CSV | **Extract + normalize** (untar, select columns, resolve ragged schema) before Bronze can read it |
| Landed shape | `raw.fema_nri/nri_counties.csv` (one file → one Bronze table) | `raw.climate_normals/_processed/normals_stations/` (Parquet → one Bronze table) |

The NOAA case is the one the request flags: it "needs a place to be downloaded,
extracted, processed, then referenced." That place is the `raw.climate_normals`
Volume with a `_processed/` subfolder — directly mirroring the **Zillow
wide→long precedent** (`raw.zillow/` holds wide CSVs; `raw.zillow/_long/` holds
the transposed Parquet that Bronze reads; see
`zillow_wide_to_long_step_design.md`).

---

## 2. Decision 1 — Schema placement: **`raw`** (both)

Per the request, FEMA NRI goes in a new Volume under **`raw`**. For consistency
and to reuse the `VolumeFileWriter` (which is hard-wired to the `RAW_FILES`
base = `/Volumes/{catalog}/raw/`), NOAA goes under `raw` too.

```
/Volumes/{CATALOG}/raw/fema_nri/
    nri_counties.csv                         ← downloaded (ArcGIS provider)

/Volumes/{CATALOG}/raw/climate_normals/
    us-climate-normals_..._c20230404.tar.gz  ← downloaded (http_file)
    inventory_30yr.txt                       ← downloaded (http_file)
    _processed/normals_stations/             ← extracted+normalized Parquet (notebook) → Bronze reads this
```

> **Note / open decision:** these are *static reference-cadence* data (NRI annual,
> Normals decadal), unlike the monthly `raw` feeds. `reference` schema was a
> candidate (it's where crosswalks live). We defer to the request's `raw`
> direction + the `VolumeFileWriter` base-path constraint. Revisit if a
> reference-schema home is preferred — it would require teaching the writer a
> second base path (a real change, not config).

**Volume provisioning** — append to `VOLUME_DEFINITIONS` in
`setup/catalog_ddl.ipynb` (the existing `create_volumes(...)` call handles it):

```python
{"name": "fema_nri",        "needs_archive": False},
{"name": "climate_normals", "needs_archive": False},
```

`needs_archive=False`: these are re-fetched in place (idempotent via sha256), not
archived-after-load like the monthly sources.

---

## 3. Decision 2 — FEMA NRI: one new provider, `arcgis_feature_service`

NRI doesn't fit `http_file` (it's not a single GET) or `fred_api` (not FRED). It
is a **third provider family**: paginate an ArcGIS Feature Service `query` and
assemble the attribute rows into a CSV. This is the only genuinely new code.

### 3.1 New file — `libs/data_fetch/providers/arcgis_feature_service.py`

Implements the `Provider` Protocol (`fetch_to` / `probe` / `canonical_url`),
constructed uniformly as `cls(secrets=..., session=...)` (uses `session`, ignores
`secrets` — no auth). Models on `FredApiProvider` (generates a CSV from JSON; no
resumable byte stream, so `resume_from` is ignored; `content_length=None`).

```python
class ArcGisFeatureServiceProvider:
    PAGE = 2000  # ArcGIS maxRecordCount

    def fetch_to(self, scratch_path, spec, f, *, resume_from, ctx) -> ProviderFetch:
        # f.url carries the .../FeatureServer/0/query endpoint (KEY-FREE).
        rows, status = [], None
        offset = 0
        while True:
            status, payload = self._get_json(f.url, params={
                "where": "1=1", "outFields": "*", "returnGeometry": "false",
                "orderByFields": "OBJECTID",          # deterministic order → stable sha256 (§journal no-op)
                "f": "json", "resultOffset": offset, "resultRecordCount": self.PAGE,
            })
            feats = payload.get("features", [])
            if not feats:
                break
            rows.extend(x["attributes"] for x in feats)
            if not payload.get("exceededTransferLimit") and len(feats) < self.PAGE:
                break
            offset += self.PAGE
        bytes_written = self._write_csv(scratch_path, rows)   # header = first row's keys (service field order)
        return ProviderFetch(bytes_written, http_status=status, canonical_url=f.url)

    def canonical_url(self, spec, f) -> str:
        return f.url or f"{spec.name}/{f.landed_filename}"     # KEY-FREE; no secret to strip

    def probe(self, spec, f) -> ProbeResult:
        # returnCountOnly=true → cheap reachability + row count, lands nothing (§7.1)
        ...
```

Two framework-aware details:
- **`orderByFields=OBJECTID`** makes the assembled CSV byte-stable across runs, so
  the runner's sha256 idempotent no-op (`journal.last_sha256`) actually fires when
  NRI is unchanged. Without it, ArcGIS pagination order isn't guaranteed and every
  run would re-promote. `OBJECTID` (every layer's mandatory, unique primary key) is
  chosen over a domain column like `STCOFIPS` so the provider stays generic and the
  sort is a guaranteed total order (no ties).
- The provider stays **generic** (any feature service → CSV). It writes *all*
  returned attributes — including the ArcGIS artifacts `OBJECTID`,
  `Shape__Area`, `Shape__Length` (returned even with `returnGeometry=false`).
  Dropping those is a Bronze/Silver concern, documented in the source README — the
  provider does not carry NRI-specific column logic.

### 3.2 Register it — `libs/data_fetch/providers/__init__.py`

```python
PROVIDERS = {
    "http_file": HttpFileProvider,
    "fred_api": FredApiProvider,
    "arcgis_feature_service": ArcGisFeatureServiceProvider,   # +1 line
}
```

(and re-export from `data_fetch/__init__.py` to match the existing pattern.)

### 3.3 Manifest — append to the new `WEATHER_SOURCES` tuple

Because these are an **annual, separately-triggered** refresh (Decision 5), the
two new specs go into a **new tuple `WEATHER_SOURCES`**, *not* the monthly
`SOURCES`. The monthly `download_sources.ipynb` (`run_all(SOURCES)`) is then
**unchanged** and never re-pulls them; the new annual job runs
`run_all(WEATHER_SOURCES)`. Single manifest file, two explicit cadence groups —
self-documenting and zero risk to the working monthly pipeline.

```python
# manifest.py — alongside SOURCES (monthly feeds), a separate annual group:
WEATHER_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="fema_nri", provider="arcgis_feature_service",
        files=(
            SourceFile(
                "nri_counties.csv",
                url=("https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
                     "National_Risk_Index_Counties/FeatureServer/0/query"),
                fmt="csv",
                expected_header=("OBJECTID", "NRI_ID", "STATE", "STATEABBRV", "STATEFIPS"),
                note="paginated ArcGIS FS; canonical hazards.fema.gov CSV is TLS-blocked from our env",
            ),
        ),
    ),
    # climate_normals SourceSpec (§4.1) joins this same tuple.
)
```

`expected_header` (prefix) gives the runner's CSV validation a schema-drift guard.
NRI lands at `raw.fema_nri/nri_counties.csv` via the new weather-download job (§6).

---

## 4. Decision 3 — NOAA: reuse `http_file`; the tarball is opaque bytes

The Normals tarball and the station inventory are plain GETs from NCEI — exactly
`http_file`. No new provider.

### 4.1 Manifest — the second member of `WEATHER_SOURCES`

```python
SourceSpec(
    name="climate_normals", provider="http_file", user_agent=BROWSER_UA,
    files=(
        SourceFile(
            "us-climate-normals_1991-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz",
            url=("https://www.ncei.noaa.gov/data/normals-annualseasonal/1991-2020/archive/"
                 "us-climate-normals_1991-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz"),
            fmt="tar.gz",                       # NOT "csv" → header validation skipped; size-match still applies
            note="54 MB; 15,616 ragged per-station CSVs; normalized post-download",
        ),
        SourceFile(
            "inventory_30yr.txt",
            url=("https://www.ncei.noaa.gov/data/normals-annualseasonal/1991-2020/doc/"
                 "inventory_30yr.txt"),
            fmt="txt",
            note="station id/lat/lon/elev/state — input to station→county mapping (later)",
        ),
    ),
),
```

`fmt="tar.gz"`/`"txt"` (anything ≠ `"csv"`) routes past header validation; the
runner's **size-match check vs server `Content-Length` still fires** (NCEI sends
it — verified), catching a truncated 54 MB pull. Both files land in
`raw.climate_normals/`.

### 4.2 The extract + normalize step — new notebook `bronze/process_climate_normals.ipynb`

The analog of `load_zillow_long.ipynb`. Solves the **ragged-schema problem**:
station CSVs have 508–2,140 columns and a Spark bulk read maps schema
*positionally*, so it would misalign. Resolution: process in **pure Python with
`csv.DictReader` (name-based)**, select the fixed column set, then hand the small
result to Spark for the Parquet write.

Cell sequence (standard §10 order — `%run notebook_init`, `StepLog`, work, succeed):

```python
# read tarball from the Volume, untar to scratch, select columns by NAME (ragged-safe)
import tarfile, csv, tempfile, os

selected_columns = IDENTITY_COLS + MEASURE_COLS + [
    f"{flag_prefix}_{measure}"
    for measure in MEASURE_COLS
    for flag_prefix in ("comp_flag", "years")
]
station_rows = []
tarball_path = f"{RAW_CLIMATE_NORMALS}{NORMALS_TARBALL}"

with tarfile.open(_copy_to_scratch(tarball_path), "r:gz") as tarball:
    for member in tarball:
        if not member.name.endswith(".csv"):
            continue
        # Each station file is a single-row CSV. Read its bytes from the tar, decode to
        # text, and parse with DictReader so columns key by HEADER NAME (not position) —
        # this is what makes the ragged 508-vs-2,140-column schema safe. Take that one row.
        station = next(csv.DictReader(tarball.extractfile(member).read().decode().splitlines()))
        if not station["STATION"].startswith("US"):   # US stations only (see Decision 5)
            continue
        # Keep only the wanted columns; a column absent from this station null-fills.
        station_rows.append(
            {column: (station.get(column) or None) for column in selected_columns}
        )

spark.createDataFrame(station_rows, schema=_all_string_schema(selected_columns)) \
     .write.mode("overwrite").parquet(RAW_CLIMATE_NORMALS_PROCESSED)
```

- **All-`StringType`** output — preserves Bronze "no casting" fidelity; Silver casts.
- **One row per station**, fixed ~44-column schema → Bronze reads it like any
  Parquet source. ~15k rows is trivial (no driver-OOM concern; this is not
  `collect()`-at-scale).
- Output → `raw.climate_normals/_processed/normals_stations/` (Parquet dir).

### 4.3 Constants — paths in `notebook_init`, columns in a source module

Two different scopes, two different homes (per the `notebook_init`-scope principle):

**Cross-cutting paths → `notebook_init`.** Append next to the existing `RAW_*`
block (same family as `RAW_ZILLOW` / `RAW_ZILLOW_LONG`):

```python
RAW_FEMA_NRI                  = f"{RAW_FILES}fema_nri/"
RAW_CLIMATE_NORMALS           = f"{RAW_FILES}climate_normals/"
RAW_CLIMATE_NORMALS_PROCESSED = f"{RAW_CLIMATE_NORMALS}_processed/normals_stations/"
NORMALS_TARBALL               = "us-climate-normals_1991-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz"
```

**Source-specific column list → a dedicated module, NOT `notebook_init`.** The
selected-column list is load-bearing (used by the normalize notebook now, the
climate-normals Bronze loader later), so it gets **one** definition — in a
source-scoped module **`libs/climate_normals_columns.py`**:

```python
# libs/climate_normals_columns.py
IDENTITY_COLS = ("STATION", "LATITUDE", "LONGITUDE", "ELEVATION", "NAME")          # 5
MEASURE_COLS  = ("ANN-TAVG-NORMAL", "DJF-TAVG-NORMAL", "MAM-TAVG-NORMAL",          # 13
                 "JJA-TAVG-NORMAL", "SON-TAVG-NORMAL", "ANN-TMAX-NORMAL",
                 "ANN-TMIN-NORMAL", "JJA-TMAX-NORMAL", "DJF-TMIN-NORMAL",
                 "ANN-PRCP-NORMAL", "ANN-SNOW-NORMAL", "ANN-HTDD-NORMAL",
                 "ANN-CLDD-NORMAL")
```

Both consumers `from climate_normals_columns import IDENTITY_COLS, MEASURE_COLS`
(the lib path that already serves `pipeline_logging` / `data_fetch`). It does
**not** go in `notebook_init`: that prelude is `%run` into *every* notebook, and a
single source's column shape is noise to all the others. The no-duplication rule
(CLAUDE.md §6) is satisfied by any single home — and the correctly-scoped home is a
source module, not the global bootstrap. (Paths are the exception precisely because
they *are* the cross-cutting `RAW_*` family.)

---

## 5. Decision 4 — Station filter: **US-only now, defer `USW`/`USC` to aggregation**

The README notes `US1` (CoCoRaHS) stations are precip-only. But dropping them at
*process* time discards legitimate precipitation coverage. The
station→CBSA aggregation (a later step) is where "which stations represent this
metro" is decided. So the normalize step keeps **all US stations** (`STATION`
starts `US`), null-filling absent measures; the `USW`/`USC` completeness filter
moves downstream. This keeps the processed extract faithful and flexible.

*(Reversible — it's a one-line predicate. Flagged as an open decision.)*

---

## 6. Decision 5 — A dedicated annual job (`job_weather_download.yml`)

These refresh **once a year**, so they get their **own job**, fully decoupled from
the monthly `download_sources` job (which is left untouched — zero risk to the
working pipeline). On Free Edition there is no scheduler, so "annual" is an
**operator-triggered** run, not a cron.

A new thin entry notebook `bronze/download_weather_sources.ipynb` — a near-copy
of `download_sources.ipynb`'s composition root — wires the same collaborators but
runs `run_all(WEATHER_SOURCES)` instead of `SOURCES`:

```python
from data_fetch import run_all, WEATHER_SOURCES, RunContext, VolumeFileWriter, \
    DownloadJournal, DatabricksSecretResolver
summary = run_all(WEATHER_SOURCES, ctx, writer=VolumeFileWriter(RAW_FILES),
                  journal=..., secrets=...)        # identical wiring; only the source tuple differs
```

The job mirrors the init→work→finalize shape of the others:

```
init_pipeline_log
  └─ download_weather_sources    (run_all(WEATHER_SOURCES) → fema_nri.csv + climate_normals tarball)
       └─ process_climate_normals  (untar + normalize → _processed/ Parquet; depends_on download)
            finalize_pipeline_log   (depends_on process_climate_normals, run_if: ALL_DONE)
```

```yaml
# resources/job_weather_download.yml (NEW) — same parameters + environments block
# as job_download_sources.yml. Tasks:
- task_key: init_pipeline_log
  spark_python_task: {python_file: ../libs/init_pipeline_run_log.py, parameters: [...]}
  environment_key: default
- task_key: download_weather_sources
  depends_on: [{task_key: init_pipeline_log}]
  notebook_task:
    notebook_path: ../bronze/download_weather_sources.ipynb
    base_parameters: {catalog: "{{job.parameters.catalog}}", shared_lib_path: "{{job.parameters.shared_lib_path}}"}
- task_key: process_climate_normals
  depends_on: [{task_key: download_weather_sources}]
  notebook_task:
    notebook_path: ../bronze/process_climate_normals.ipynb
    base_parameters: {catalog: "{{job.parameters.catalog}}", shared_lib_path: "{{job.parameters.shared_lib_path}}"}
- task_key: finalize_pipeline_log
  depends_on: [{task_key: process_climate_normals}]
  run_if: ALL_DONE                  # lifecycle task — fires even if upstream failed (CLAUDE.md bundle rules)
  spark_python_task: {python_file: ../libs/finalize_pipeline_run_log.py, parameters: [...]}
```

The monthly `download_sources.ipynb` / `job_download_sources.yml` are **not
touched**, and the 54 MB tarball is pulled only on the annual run (sha256 no-ops
it if a re-run lands identical bytes).

---

## 7. Local dev + tests

- **Local harness** (`scripts/download_local.py`): add a `dl_weather()` running
  `run_all(WEATHER_SOURCES)` → `LocalFileWriter` → `_local_downloads/<name>/`
  (the monthly `dl_all` keeps using `SOURCES`, so it won't touch these). The
  proven extraction logic already exists in `scripts/scratch/fetch_nri_counties.py`
  and `fetch_climate_normals.py` — the new provider + normalize notebook are
  re-homings of that code into the framework. (The normalize step is Spark/notebook;
  its Python core is runnable locally for validation.)
- **Tests** (match existing `tests/` for the framework): add
  `ArcGisFeatureServiceProvider` unit tests with a fake `session` — pagination
  assembles all rows, `canonical_url` is key-free, `probe` returns count,
  `>=400` raises `ProviderHttpError` (so `RetryingProvider` retries transients).
  No test needed for the `http_file` reuse beyond a manifest smoke check.

---

## 8. File-by-file change list (for `/sc:implement`)

| # | File | Change |
|---|---|---|
| 1 | `libs/data_fetch/providers/arcgis_feature_service.py` | **New** — `ArcGisFeatureServiceProvider` (Protocol-compliant, paginated). |
| 2 | `libs/data_fetch/providers/__init__.py` | Register `"arcgis_feature_service"` in `PROVIDERS`. |
| 3 | `libs/data_fetch/__init__.py` | Re-export the new provider **and `WEATHER_SOURCES`** (pattern parity). |
| 4 | `libs/data_fetch/manifest.py` | Add new **`WEATHER_SOURCES`** tuple (`fema_nri` + `climate_normals`); `SOURCES` unchanged. |
| 5 | `libs/notebook_init.ipynb` | Add `RAW_FEMA_NRI`, `RAW_CLIMATE_NORMALS`, `RAW_CLIMATE_NORMALS_PROCESSED`, `NORMALS_TARBALL`. |
| 6 | `libs/climate_normals_columns.py` | **New** — source-scoped module: `IDENTITY_COLS` (5) + `MEASURE_COLS` (13); imported by the normalize notebook + the climate-normals Bronze loader. **Not** in `notebook_init`. |
| 7 | `setup/catalog_ddl.ipynb` | Add `fema_nri` + `climate_normals` to `VOLUME_DEFINITIONS`. |
| 8 | `bronze/download_weather_sources.ipynb` | **New** — thin composition root; `run_all(WEATHER_SOURCES)`. |
| 9 | `bronze/process_climate_normals.ipynb` | **New** — untar + ragged-safe column select → `_processed/` Parquet. |
| 10 | `resources/job_weather_download.yml` | **New** — annual job: init → download_weather_sources → process_climate_normals → finalize. |
| 11 | `scripts/download_local.py` | Add `dl_weather()` (`run_all(WEATHER_SOURCES)`). |
| 12 | `tests/…` | `ArcGisFeatureServiceProvider` unit tests. |

**Net new code:** one provider class + two thin notebooks (entry + normalize) + one
job yml. The monthly pipeline is untouched; the framework's "append a `SourceSpec`"
promise holds (into `WEATHER_SOURCES`), extended by exactly one provider for FEMA.

---

## 9. Confidence summary

- **Verified** (read this session): the `Provider`/`FileWriter` Protocols, the
  Template-Method runner lifecycle (validate→sha256→no-op→promote), the
  `VolumeFileWriter` `raw`-base constraint, `validate_download` skipping header
  checks for non-CSV `fmt`, the `create_volumes(schema=...)` signature, the
  Zillow `_long` precedent + job-task shape, the ArcGIS endpoint (3,232 rows / 467
  cols / `orderByFields` support), and the NCEI tarball + inventory URLs.
- **Projected**: ArcGIS `services.arcgis.com` and NCEI reachability **from
  Databricks serverless** (both reachable from this env; verify via the framework
  `healthcheck` probe before first job run). Stable ArcGIS field order across
  pages (mitigated by writing header from the first page and `orderByFields`).
- **Guessing — do not ship without a probe:** none. (The canonical
  `hazards.fema.gov` host is confirmed blocked here; the ArcGIS substitute is the
  design's basis.)

---

## 10. Open decisions (recap)

1. **Schema** = `raw` for both (per request + writer constraint). `reference` shelved. ✔ confirmed
2. **Station filter** = US-only at process time; `USW`/`USC` deferred to aggregation. ✔ confirmed
3. **Cadence** = **dedicated annual job** (`job_weather_download.yml` +
   `WEATHER_SOURCES` tuple + `download_weather_sources.ipynb`); monthly
   `download_sources` untouched. Free-Edition = operator-triggered, no cron. ✔ confirmed
4. **ArcGIS artifacts** (`OBJECTID`, `Shape__*`) kept in the landed CSV (generic
   provider); dropped at Bronze/Silver. ✔ confirmed

*Design only — no implementation produced. Next: `/sc:implement` against the
§8 change list (provider + manifest + volumes first; entry notebook + normalize
notebook + job second), each behind the usual plan/approve gate.*
