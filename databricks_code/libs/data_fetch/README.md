# `data_fetch` — data-acquisition framework

A small, environment-agnostic Python package that downloads raw source files for the
marketpulse pipeline — Zillow, FHFA, Realtor.com, FRED, and the annual weather/hazard
sources (FEMA NRI, NOAA Climate Normals) — and lands them, validated and de-duplicated,
in the Bronze raw landing zone (a Unity Catalog Volume on Databricks, a local directory
when developing).

This document is for two audiences:

- **Developers** who need to add a source, change download behavior, or call the
  framework from a notebook or script.
- **IT managers** who need to understand what the module does, how it is structured, and
  why — without reading the code.

---

## 1. Purpose

The Bronze layer needs raw files on disk before any Spark job can read them. `data_fetch`
is the component that puts them there. For every configured source file it runs an
identical, auditable lifecycle:

```
fetch → validate → hash (sha256) → idempotent no-op check → promote to destination → journal
```

Concretely it:

- Pulls each file over HTTP (plain file download, FRED JSON API, or paginated ArcGIS
  Feature Service) with **retry-and-backoff** on transient failures.
- **Validates** every download before it is allowed to land: non-empty, byte-count match
  against the server's declared size (truncation guard), and a CSV header check.
- **Skips re-downloading unchanged files** — if the bytes hash identical to what landed
  last time *and* the file is still present, it records `skipped` instead of rewriting.
- **Writes an audit row** (`download_log`) for every file — succeeded, skipped, or failed
  — capturing URL, byte count, sha256, attempt count, timing, and any error.
- Uses an **abort-on-first** batch policy: the first file that fails stops the run, so a
  partial/broken refresh never masquerades as a complete one.

The package is **standalone**: it never imports `notebook_init`, never touches
`dbutils`, `os.environ`, or a `SparkSession` on its own. Everything environment-specific
(the catalog, the run id, the secret store, where files land, the audit-log writer) is
*injected* by the caller. That is what lets the exact same code run locally and on
Databricks.

---

## 2. Architecture (and why)

The design goal that shaped everything else is: **adding a new data source should be
config-only.** Append one `SourceSpec` to the manifest — no change to the runner, the
providers, the writer, or the journal.

This is achieved with three classic patterns:

| Pattern | Where | What it buys us |
|---|---|---|
| **Template Method** | `DownloadRunner.run_file` | The per-file lifecycle (fetch → validate → hash → no-op → promote → journal) is written **once**. Only the fetch step varies per source. |
| **Strategy** | `Provider` protocol + concrete providers | The one real axis of variation — *how* you fetch (HTTP file vs JSON API vs ArcGIS) — lives behind a single interface, selected by a string key in the manifest. |
| **Adapter** | `FileWriter`, `SecretResolver`, `DownloadJournal` | The environment seams — where files land, how secrets resolve, how audit rows persist — are interfaces with a local and a Databricks implementation. The core depends on the interface, not the environment. |
| **Decorator** | `RetryingProvider` | Retry/backoff wraps *any* provider without that provider knowing about retries. |

### Dependency injection / composition root

`RunContext` is a frozen value object carrying the per-run facts (catalog, run id, step
log id, scratch dir, clock). The caller — the **composition root** — builds it along with
the writer, journal, and secret resolver, and hands them to `run_all`. The package itself
reads nothing from the environment.

There are two composition roots:

- **Databricks:** the `bronze/download_sources.ipynb` notebook wires `VolumeFileWriter`,
  a `DownloadJournal` bound to `pipeline_logging.download_log_insert`, and
  `DatabricksSecretResolver`.
- **Local:** `runner.main` (the `python -m data_fetch` CLI) and `scripts/download_local.py`
  wire `LocalFileWriter`, a no-op journal, and `DotenvSecretResolver`.

### Why this was chosen

- **Extensibility is the headline.** A new source is a new manifest entry; a genuinely
  new *kind* of source (a new transport) is one new provider class plus one line in the
  `PROVIDERS` registry. The core is untouched, so the blast radius of a new source is
  tiny and the regression risk is low.
- **Testability.** Because every collaborator is injected, tests substitute fakes (a fake
  provider, an in-memory journal, an injected clock and sleep function) and exercise the
  full lifecycle deterministically with no network and no Spark.
- **Portability.** The same package runs on a laptop and on serverless Databricks with no
  conditional `if running_on_databricks` branches inside it — the difference is entirely
  in which adapters the composition root injects. To run locally, pyspark must be installed.  pip install pyspark
- **Auditability.** One lifecycle means one place that writes the audit row, so every
  file — including failures — is logged consistently.

---

## 3. File-by-file

### Package core (`databricks_code/libs/data_fetch/`)

| File | Purpose |
|---|---|
| `__init__.py` | Public surface. Re-exports the value types, manifest, providers, adapters, and runner entry points (see `__all__`). Importing `data_fetch` gets you everything the composition roots need. |
| `__main__.py` | Makes `python -m data_fetch` work — delegates to `runner.main`. |
| `constants.py` | Module-top tuning constants: browser User-Agent, retry/backoff caps, HTTP timeouts, and the four pipeline `STATUS_*` literals. Standalone copy of the status strings (must equal `pipeline_logging`'s; a drift test enforces it). |
| `context.py` | `RunContext` — the frozen, injected per-run value object (catalog, run id, step log id, audit schema, scratch dir, clock). The package never fills it from the environment itself. |
| `manifest.py` | The **source registry**. `SourceSpec` / `SourceFile` dataclasses plus the populated `SOURCES` (monthly) and `WEATHER_SOURCES` (annual) tuples. **This is the file you edit to add a source.** |
| `runner.py` | The integration capstone: `DownloadRunner` (Template Method lifecycle), the `run_all` / `healthcheck` / `main` entry functions, `local_run_context`, and the `FileOutcome` / `RunSummary` / `HealthCheckResult` result types. |
| `file_writer.py` | `FileWriter` protocol + `LocalFileWriter` (local dir, atomic rename) and `VolumeFileWriter` (copy into a Unity Catalog Volume). The "promote validated file to its destination" seam. |
| `journal.py` | `DownloadJournal` (two injected callables: `record`, `last_sha256`) and the `DownloadLogRow` dataclass whose field names match `pipeline_logging.download_log_insert` exactly. `DownloadJournal.noop()` for local runs. |
| `secrets.py` | `SecretResolver` protocol + `DotenvSecretResolver` (reads a project-root `.env`) and `DatabricksSecretResolver` (reads `dbutils` secret scope or widget). The only env seam `notebook_init` does not inject — currently just the FRED API key. |
| `validation.py` | Pure pre-promote checks over a completed scratch file: non-empty, size-match (truncation guard), CSV prefix-header match — plus `sha256_of`. A failure raises `ValidationError` (permanent, not retried). |

### Providers (`databricks_code/libs/data_fetch/providers/`)

| File | Purpose |
|---|---|
| `base.py` | The `Provider` Strategy protocol (`fetch_to`, `probe`, `canonical_url`) and its return types `ProviderFetch` / `ProbeResult`. |
| `__init__.py` | The `PROVIDERS` registry (string key → provider class) and the `make_provider` factory. **Register a new provider class here.** |
| `http_file.py` | `HttpFileProvider` — plain HTTP file pull with browser UA, streamed to disk, optional Range resume. Serves Zillow, FHFA, Realtor, and the NOAA tarball. |
| `fred_api.py` | `FredApiProvider` — FRED JSON API; pulls full series history and writes the canonical 4-column CSV. Uses the injected secret resolver for the API key (never logged). |
| `arcgis_feature_service.py` | `ArcGisFeatureServiceProvider` — pages an ArcGIS Feature Service `query` endpoint and assembles one CSV. Serves FEMA NRI. Deterministic row order so the sha256 is stable across runs. |
| `retrying.py` | `RetryingProvider` — the Decorator that adds retry-with-backoff. Retries only transient failures (connection/timeout, mid-stream drop, HTTP 5xx, 429 honoring `Retry-After`); permanent failures (other 4xx, `ValueError`) propagate immediately. Exposes `last_attempts`. |
| `errors.py` | `ProviderHttpError` (carries `status_code`, key-free `url`, `retry_after`) and `parse_retry_after`. Lets `RetryingProvider` classify retry eligibility without parsing strings. |

---

## 4. Calling it from code

### 4.1 On Databricks (the real composition root)

This is what `bronze/download_sources.ipynb` does. `notebook_init` has already injected
`CATALOG`, `AUDIT`, `RAW_FILES`, `PIPELINE_RUN_ID`, `STATUS_*`, `spark`, `dbutils`, and
the `StepLog` recorder.

```python
import tempfile
from functools import partial
from datetime import datetime, timezone

from data_fetch import (
    run_all, SOURCES, RunContext, VolumeFileWriter, DownloadJournal,
    DatabricksSecretResolver,
)
from pipeline_logging import download_log_insert, download_log_last_sha256

ctx = RunContext(
    catalog=CATALOG,
    pipeline_run_id=str(PIPELINE_RUN_ID),
    step_log_id=step.step_log_id,        # FK to the pipeline_step_log row
    audit_schema=AUDIT,
    scratch_dir=tempfile.gettempdir(),   # serverless-safe; never /local_disk0
    now=lambda: datetime.now(timezone.utc),
)

summary = run_all(
    SOURCES, ctx,
    writer=VolumeFileWriter(RAW_FILES),                       # /Volumes/<catalog>/raw/
    journal=DownloadJournal(
        record=partial(download_log_insert, spark, AUDIT),
        last_sha256=partial(download_log_last_sha256, spark, AUDIT),
    ),
    secrets=DatabricksSecretResolver(dbutils, scope="marketpulse"),
)
print(summary.describe())
# download run: 3 succeeded, 13 skipped, 0 failed (16 files total)
```

### 4.2 Locally (one-line, no Databricks)

The package ships a local composition root, so a local run needs no wiring:

```bash
# download every source into ./localraw
uv run --python 3.12 -m data_fetch --root ./localraw

# probe every source URL without landing anything
uv run --python 3.12 -m data_fetch --healthcheck
```

For day-to-day local development against the live URLs, prefer the
`scripts/download_local.py` harness — see §5.

### 4.3 Public entry points

The framework offers two layers of entry point. Most callers use the **module-level
functions**; the `DownloadRunner` class underneath is available when you need to inject a
custom provider factory (chiefly tests).

| Entry point | Signature (abridged) | What it does |
|---|---|---|
| `run_all(sources, ctx, *, writer, journal, secrets, provider_for=None)` | → `RunSummary` | The main entry. Runs the full lifecycle for every file in `sources`. **Abort-on-first**: raises on the first failed file (after logging its `failed` row). Returns a `RunSummary` of `FileOutcome`s on success. `provider_for` defaults to the real provider factory wrapped in `RetryingProvider`; pass your own to inject fakes. |
| `healthcheck(sources, ctx, *, secrets, provider_for=None)` | → `list[HealthCheckResult]` | Probes every source URL (cheap reachability check) and lands **nothing**. Use to verify sources are reachable before a real run. |
| `main(argv=None)` | → `int` (exit code) | The local/CI CLI behind `python -m data_fetch`. Builds a `LocalFileWriter`, a **no-op journal** (a missing audit table must never fail a local run), and a `DotenvSecretResolver`. Supports `--root`, `--scratch`, `--healthcheck`. |
| `local_run_context(scratch_dir=None)` | → `RunContext` | Builds the dummy local `RunContext` (`localdev` catalog, `LOCALDEV` run id, fresh `step_log_id`, UTC clock, temp scratch dir). Shared by `main` and `scripts/download_local.py` so local wiring lives in one place. |
| `DownloadRunner(ctx, *, provider_for, writer=None, journal=None)` | class | The Template-Method engine. `run_all` / `healthcheck` are thin wrappers over it. Instantiate directly only when you need to supply a custom `provider_for` (e.g. tests injecting fake providers). |

**Result objects** (all frozen dataclasses):

- `RunSummary` — wraps the `FileOutcome` tuple. `.describe()` gives the one-line
  succeeded/skipped/failed summary; `.by_status(STATUS_*)` filters.
- `FileOutcome` — per-file result: `source_system`, `landed_filename`, `status`,
  `canonical_url`, `landed_file_path`, `bytes_downloaded`, `sha256`, `attempts`, `error`.
- `HealthCheckResult` — per-file probe result: `ok`, `http_status`, `content_length`,
  `detail`.

---

## 5. Local download harness — `scripts/download_local.py`

`scripts/download_local.py` (at the **repo root**, not in this package) is the recommended
way to run the framework end-to-end on your machine against the live source URLs. It runs
the **real** framework — providers, validation, sha256, retry, `LocalFileWriter` — with a
no-op journal, landing files under `<repo>/_local_downloads/<source>/`. No Databricks, no
Spark. FRED needs `FRED_API_KEY` in `<repo>/.env`.

Run from the project root:

```bash
uv run --python 3.12 scripts/download_local.py dl_all      # every monthly source (abort-on-first)
uv run --python 3.12 scripts/download_local.py dl_zillow   # one source at a time
uv run --python 3.12 scripts/download_local.py dl_fhfa
uv run --python 3.12 scripts/download_local.py dl_realtor
uv run --python 3.12 scripts/download_local.py dl_fred     # needs FRED_API_KEY in .env
uv run --python 3.12 scripts/download_local.py dl_weather  # annual FEMA NRI + NOAA Climate Normals
```

It prints the `RunSummary` plus a per-file line (status, bytes, landed path). Use it to
smoke-test a newly added source against the real endpoint before deploying, or to debug a
provider without a Databricks round-trip.

---

## 6. Adding a new source (the common task)

1. **Same transport as an existing source?** (a plain HTTP file, a FRED series, an ArcGIS
   layer) → add **one** `SourceFile`/`SourceSpec` to `SOURCES` (or `WEATHER_SOURCES`) in
   `manifest.py`. Nothing else changes. Provision the matching Volume
   `catalog.raw.<name>` in the catalog DDL — `name` is both the `source_system` and the
   Volume segment.
2. **A genuinely new transport?** → add a provider class implementing the `Provider`
   protocol (`fetch_to`, `probe`, `canonical_url`), register it in
   `providers/__init__.py`'s `PROVIDERS` dict, then add the manifest entry as in step 1.
3. Smoke-test with `scripts/download_local.py` against the live URL before deploying.
