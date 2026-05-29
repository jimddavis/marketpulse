# Data Acquisition Framework — Design

**Status:** Draft for review · **Scope:** design only (no implementation) ·
**Target package:** `databricks_code/libs/data_fetch/`

A production-grade, extensible framework that downloads raw files from external
real-estate / economic data sources and lands them in the correct Unity Catalog
Volume. Local-first (developed and unit-tested with local Python before bundle
deployment). Adding a new source — including the planned Weather source — is a
manifest entry, not a core code change.

> **Reading order for `/sc:implement`:** §16 (Implementation Contract) is the
> normative checklist. Everything before it is rationale. If §1–§15 and §16 ever
> disagree, **§16 wins** — raise the conflict, do not silently pick one.

---

## 1. The load-bearing boundary: download is plain Python, not PySpark

The single most important architectural decision, stated up front because every
other decision follows from it:

> **The download stage is plain Python (stdlib + `requests`). It fetches bytes
> over HTTP / S3 / a JSON API and lands an opaque file in a Volume. PySpark is
> used only *downstream* — to read the landed file and normalize it (e.g. the
> `wide_to_long` unpivot for Zillow).**

Rationale:

- Fetching arbitrary URLs, following an S3 path, looping a registration-gated
  JSON API, honoring HTTP `Range`, retrying on a 429 — these are driver-side
  I/O concerns. Spark has no role in them and cannot read an arbitrary HTTPS/API
  endpoint as a source.
- This keeps the fetch layer **dependency-light and fast to unit-test locally**
  with no `SparkSession`. The project rule "datasets must be PySpark"
  (`.claude/CLAUDE.md` §13) applies to the *transform* stage, which this
  framework deliberately does not touch.

**Consequence for file formats:** the framework treats every landed file as
**opaque bytes**. It does not parse XLSX, does not interpret CSV columns beyond a
cheap text-level header check (§7). FHFA's `.xlsx` files (including the banner-row
quirk) are downloaded as-is; the banner / sheet parsing is a Bronze concern, not
a download concern. This is what keeps `openpyxl`/`pandas` out of the fetch layer.

### What is in scope vs out

| In scope (this design) | Out of scope (noted as boundaries) |
|---|---|
| Fetch bytes from the 4 sources | The `wide_to_long` normalization (reuse the existing module downstream; not yet vendored into marketpulse — §13) |
| Landing into a Volume / local dir (local-scratch → promote) | The Bronze/Silver/Gold notebooks that read landed files |
| Per-download logging to a new `download_log` audit table | The full audit-table DDL (we *specify* `download_log`; adding it to `AUDIT_DDL.py` is one step in the plan, §12) |
| Healthcheck / URL-drift probe mode | Job scheduling / orchestration wiring (Free Edition; deferred) |
| Local pytest with injected fakes | XLSX/CSV column parsing & schema casting (Bronze) |
| Reusing `notebook_init` constants on the Databricks entry | Generating `PIPELINE_RUN_ID` (notebook_init owns it; this phase assumes it exists) |

---

## 2. Source inventory — two download families

| Source | Family | Auth | Files | Format | History floor |
|---|---|---|---|---|---|
| **Zillow** | A — HTTP file | none (browser UA) | 3 (ZHVI, ZORI, Inventory; metro) | wide CSV | ZHVI 2000 / ZORI 2015 / Inv 2018 |
| **FHFA** | A — HTTP file | none (browser UA) | 3 (master CSV long, PO xlsx, AT xlsx) | CSV + XLSX | 1975 |
| **Realtor.com** | A — HTTP file (S3) | none (browser UA) | 2 (snapshot, history ~32 MB) | CSV | 2016-07 |
| **FRED** | B — JSON API | `FRED_API_KEY` (`.env` locally) | ~10 series → 1 CSV each | JSON → CSV | per series, all ≤ 2010 |

All available ranges predate the 2010 floor, so **"since 2010 / 2000 where
available" is a floor, not a filter**. We pull full history and let downstream
filter. **Every windowing mechanism in the research code is discarded** —
FRED's `window_start()`, Zillow's `--months`, Realtor's manual slice, FHFA's
windowed re-save. Nothing in this framework limits the date range.

The two families differ only in *how bytes are produced*: Family A streams an
HTTP body; Family B loops a series, calls two JSON endpoints, and synthesizes a
CSV. That single axis of variation is what the `Provider` Strategy captures (§5).

---

## 3. Architecture at a glance

```
                       SOURCES registry (manifest.py)
                                  │  SourceSpec / SourceFile
                                  ▼
        ┌──────────────────  DownloadRunner  ───────────────────┐
        │   Template Method, ABORT-ON-FIRST across files:        │
        │   for f in source.files:                               │
        │     healthcheck? → fetch(retry) → validate → promote   │
        │                  → journal.record()  (raise on failure)│
        └───────┬───────────────┬─────────────┬────────────┬─────┘
                │               │             │            │
          Provider         (Decorator)    FileWriter   DownloadJournal
        (Strategy)        RetryingProvider             (2 injected callables
        ┌────┴────┐                     ┌────┴──────┐    over pipeline_logging)
   HttpFileProvider              LocalFileWriter      record() · last_sha256()
   FredApiProvider               VolumeFileWriter      local: no-ops
        │  (FRED key via         (base path from       Databricks: bound
        │   SecretResolver)       notebook_init         pipeline_logging fns
                                  RAW_FILES)
```

- **Runner** owns the lifecycle that is identical for every source; **aborts on
  the first failed file** (§16).
- **Provider** is the only thing that varies per source family (Strategy).
- **FileWriter** isolates *where/how* a file is promoted (local vs Volume); the
  Volume base path comes from notebook_init's `RAW_FILES`.
- **DownloadJournal** = two injected callables (`record`, `last_sha256`) that, on
  Databricks, are bound `pipeline_logging` functions; locally they are no-ops.
- **RetryingProvider** is an optional Decorator adding backoff orthogonally.

---

## 4. Design question 1 — the manifest: **Python dataclass registry** (recommended)

**Decision: a typed Python registry module (`manifest.py`) holding `SourceSpec`
literals. Not YAML, not a Delta table — for now.**

| Option | Pros | Cons |
|---|---|---|
| **Python dataclass registry** ✅ | Type-safe; validated at import; zero new deps; IDE/refactor support; **matches existing repo pattern** (`wide_to_long/formats.py` `REGISTRY` tuple, `fetch_fred_samples.py` `SERIES` list) | Edited by developers, not ops |
| YAML file | Editable by non-developers; comments for "why this URL" | Needs `pyyaml`; runtime parse + type coercion; Realtor's wide header is ugly in YAML; errors surface at runtime not import |
| Delta table | Centralized, queryable | **Bootstrap paradox** — needs Spark + a live catalog to *decide how to download*; defeats local-first; tables are for *logging*, config is for *declaring* |

**Why this is genuinely "config-only" for new sources:** adding Weather means
appending one `SourceSpec(...)` to the registry — no change to providers, runner,
writer, journal. The registry is *data expressed as code*, consistent with how
this codebase already declares closed registries (`.claude/CLAUDE.md` §5).

**Forward-compatible escape hatch:** the runner consumes a *sequence of
`SourceSpec` objects*; it does not care where they come from. A future
`load_yaml() -> tuple[SourceSpec, ...]` loader producing the same objects would
not touch the core.

---

## 5. Design question 2 — DI + Provider Strategy

The package is **pure Python**: it imports neither `notebook_init`, `dbutils`,
nor a live `SparkSession` at module load. Everything environment-specific is
**injected** — provider, file writer, journal, secret resolver, and a run
context. This is what makes it unit-testable with fakes (§11) and is why the
Databricks-vs-local difference lives entirely in the entry point (§8.1).

### Core data types

```python
# context.py
@dataclass(frozen=True)
class RunContext:
    catalog: str                     # from notebook_init CATALOG (Databricks) / dummy (local)
    pipeline_run_id: str             # from notebook_init PIPELINE_RUN_ID (assumed present) / dummy
    step_log_id: str                 # minted once per run (uuid4) by the entry
    audit_schema: str                # = f"{catalog}.audit"  (notebook_init AUDIT)
    scratch_dir: str                 # tempfile.gettempdir() — NEVER hardcode /local_disk0 (§16)
    now: Callable[[], datetime]      # injected clock → deterministic tests

# manifest.py
@dataclass(frozen=True)
class SourceFile:
    landed_filename: str                       # friendly name, e.g. "zhvi_home_values_metro_monthly.csv"
    url: str | None = None                     # Family A
    series_id: str | None = None               # Family B (FRED)
    fmt: str = "csv"                            # "csv" | "xlsx" | "json"
    expected_header: tuple[str, ...] | None = None   # PREFIX-matched, CSV only; None → skip (§7.5)
    note: str | None = None

@dataclass(frozen=True)
class SourceSpec:
    name: str                                  # source_system: "zillow"|"fhfa"|"realtor"|"fred"
    provider: str                              # "http_file" | "fred_api"  → factory key
    volume: str                                # raw Volume name; joined onto RAW_FILES base
    files: tuple[SourceFile, ...]
    user_agent: str | None = None              # Family A
    api_key_env: str | None = None             # Family B, e.g. "FRED_API_KEY"

# providers/base.py
@dataclass(frozen=True)
class ProviderFetch:
    bytes_written: int
    http_status: int | None          # None for the FRED JSON path
    canonical_url: str               # KEY-FREE url for logging + no-op keying (§16)
```

### The Provider protocol (Strategy)

```python
# providers/base.py
class Provider(Protocol):
    def fetch_to(self, scratch_path: str, spec: SourceSpec, f: SourceFile,
                 *, resume_from: int, ctx: RunContext) -> ProviderFetch:
        """Write the file's raw bytes to `scratch_path` on LOCAL disk.
        `resume_from` > 0 requests an HTTP Range continuation appended to the
        existing local partial (Family A); providers that cannot resume ignore
        it and restart. Returns bytes written, http_status, and a KEY-FREE
        canonical_url."""

    def probe(self, spec: SourceSpec, f: SourceFile) -> ProbeResult:
        """Cheap reachability check for healthcheck mode — no full download."""
```

- **`HttpFileProvider`** (Zillow, FHFA, Realtor): `GET` with the spec's
  User-Agent; supports `Range: bytes=<resume_from>-`; `canonical_url` = the URL
  itself; `probe()` issues a ranged `bytes=0-0` GET (more reliable than `HEAD` on
  CDNs/S3) and checks for `200`/`206`.
- **`FredApiProvider`** (FRED): obtains the key via the injected `SecretResolver`
  (keyed by `spec.api_key_env`) — never `os.environ` directly; per `SourceFile`,
  calls `/series` (metadata) then `/series/observations` with **no
  `observation_start`** (full history), writes the 4-column CSV
  (`date,value,realtime_start,realtime_end`); `probe()` calls `/series` only.
  **`canonical_url` is the observations endpoint with `series_id` only — the
  `api_key` query param is stripped** so it never reaches the audit table (§16).
  *(FRED's `observations` default `limit` is 100000; all in-scope series are
  < 3000 rows so a single call returns full history — no pagination needed.)*

### Factory + Registry

```python
# providers/__init__.py
PROVIDERS: dict[str, type[Provider]] = {
    "http_file": HttpFileProvider,
    "fred_api":  FredApiProvider,
}
def make_provider(spec: SourceSpec, *, secrets: SecretResolver,
                  session=...) -> Provider: ...   # secrets/session threaded in for FRED
```

The Weather source will be either `http_file` or a new `"weather_api"` key → one
new provider class + one registry entry, core untouched.

---

## 6. Design question 3 — GoF patterns that earn their place (and those that don't)

| Pattern | Used? | Where / why |
|---|---|---|
| **Strategy** | ✅ | `Provider` — the one real axis of variation (HTTP vs API). |
| **Registry + Factory** | ✅ | `SOURCES` manifest + `PROVIDERS` map → config-only source addition. Plain factory (not Abstract Factory — single product family). |
| **Template Method** | ✅ | `DownloadRunner` — the lifecycle is identical for all sources; only `fetch` varies. |
| **Adapter** | ✅ | `FileWriter` (local FS vs `/Volumes`) and `SecretResolver` (`.env` vs Databricks-side) each adapt an environment behind one interface. |
| **Decorator** | ✅ (optional) | `RetryingProvider` wraps any `Provider` to add backoff/attempt-counting orthogonally. |
| Command | ❌ | No queue / undo / deferred-execution need at 4 sources × ~10 files. |
| Observer | ❌ | Logging is one injected seam, not a multi-subscriber bus. YAGNI. |
| Abstract Factory | ❌ | One product family. Plain factory suffices. |
| Singleton | ❌ | Inject dependencies instead (testability). |

**Anti-over-engineering note:** Free Edition + a learning project. The five chosen
patterns map 1:1 to a real, named force. Note the logging seam is deliberately
*not* a class hierarchy — it conforms to the project's **functional**
`pipeline_logging` convention (§9), exposed to the core as two injected callables.

---

## 7. Design question 4 — resilience

Per file, inside `DownloadRunner.run_file()`. **Batch policy: abort on the first
failed file** (§16) — a raised failure stops the run; the failed file's
`download_log` row is `STATUS_FAILED`; remaining files are not attempted.

1. **Healthcheck (optional, separate mode).** `runner.healthcheck()` calls
   `provider.probe()` for every file, asserts `200`/`206` + non-zero
   `Content-Length`, and reports drift **without landing anything**. Early warning
   for publisher URL changes. Run pre-flight or scheduled.

2. **Landing (local scratch → promote).** The provider downloads to a file in the
   **scratch dir** (`ctx.scratch_dir`, default `tempfile.gettempdir()` — never the
   Volume, which rejects append/random writes; never a hardcoded `/local_disk0`).
   After validation, the `FileWriter` **promotes** it: `os.replace` locally
   (atomic, same FS); `shutil.copy` to the Volume on Databricks (cross-FS — the
   documented local-then-copy pattern). A crashed download leaves only a scratch
   orphan, cleaned up next run; the Volume only ever receives a completed,
   validated file.

3. **Retry with exponential backoff (Decorator).** `RetryingProvider` retries only
   *transient* failures — connection errors, timeouts, HTTP `5xx`, and `429`
   (FRED, honoring `Retry-After`). Backoff is exponential with jitter; attempt cap
   is a named constant. Permanent failures (`404`, `403`, header mismatch) **do
   not retry**. `download_attempts` is recorded.

4. **HTTP `Range` resume (Family A).** Resume operates entirely on the **local
   scratch file** — never the Volume. On a retry where a local partial exists,
   `HttpFileProvider` sends `Range: bytes=<local_size>-` and appends; it verifies
   `206` + a consistent `Content-Range`, else restarts from zero. *(Verified this
   session: Zillow CDN and Realtor S3 both honor `Range`; files are ~4–32 MB, so
   resume is hardening, not mandatory — §14.)*

5. **Post-download validation (before promote).** On the scratch file:
   - **non-empty**; and when the response carried `Content-Length`, **byte-count
     match** (catches truncation);
   - **expected-header check — CSV only, PREFIX match.** Read the first line as
     text; assert its first `len(expected_header)` columns equal
     `SourceFile.expected_header`. **Prefix (not exact)** because Zillow's wide
     files carry a long date-column tail after the 5 ID columns; FRED/FHFA-master
     headers happen to equal their full width, so prefix subsumes exact. **XLSX /
     JSON land as opaque bytes** — structural validation deferred to Bronze.
   - Validation failure → **no promote**, `STATUS_FAILED`, journaled, raised.

6. **`sha256` + idempotent no-op.** Compute the digest of the scratch file. Call
   `journal.last_sha256(canonical_url)`; if it equals the new digest, **skip the
   promote** (publisher re-served identical bytes), mark `STATUS_SKIPPED`, journal
   it. Lets a re-run be a cheap no-op and lets a downstream Bronze MERGE answer "is
   this actually new data?" Locally `last_sha256` returns `None`, so local runs
   always download — acceptable.

7. **Journal** (always, success or failure) one `download_log` row (§9).

**Idempotency summary:** same bytes upstream → no-op (sha match); different bytes
→ new landed file + new `download_log` row; the file path is stable per
`SourceFile.landed_filename`, so re-runs overwrite-via-promote deterministically.

---

## 8. Design question 5 — local ↔ Volume: an injected **`FileWriter`** (verified)

A single injected root string is **insufficient**: the *promote mechanism*
differs by environment, not just the path prefix. Verified against the Databricks
docs this session:

- Standard Python file APIs (`os`, `open`, `shutil.copyfile`) **do** work on
  `/Volumes/...` paths.
- The FUSE mount **does not support append or random writes**.
- The docs prescribe the local-then-copy pattern. *(The doc example named
  `/local_disk0/tmp`, a **classic-cluster** path. This design does NOT hardcode
  it — it uses `tempfile.gettempdir()`, which resolves correctly on serverless
  too; §16, §14.)*

So the provider downloads (and resumes, §7.4) into the **scratch dir**, where
append works; only the completed, validated file is promoted. The `FileWriter`
owns that final hop:

| `FileWriter` | Environment | `promote()` mechanism | Confidence |
|---|---|---|---|
| **`LocalFileWriter(root)`** | local dev / pytest | `os.replace(scratch → <root>/<src>/<name>)` — atomic, same FS | **Verified** (stdlib) |
| **`VolumeFileWriter(raw_base)`** | **on a Databricks notebook job** | `shutil.copy(scratch → <raw_base>/<vol>/<name>)`, where `raw_base` = notebook_init's `RAW_FILES` (`/Volumes/<cat>/raw/`); cross-FS (`os.replace` would raise `EXDEV`) | **Verified** (Databricks docs, this session) |
| **`SdkUploadFileWriter`** *(future)* | local machine → remote Volume | `WorkspaceClient.files.upload(...)` (verify signature if built) | **Projected** — not needed for local-first → deploy |

```python
# file_writer.py
class FileWriter(Protocol):
    def promote(self, local_tmp_path: str, source_system: str, final_name: str) -> str:
        """Place a completed, validated LOCAL temp file at its final destination.
        Returns the final path/URI."""
    def final_size(self, source_system: str, final_name: str) -> int:
        """Bytes of an existing final file; 0 if absent. For no-op / diagnostics."""
```

**The Volume base path is owned by `notebook_init` (`RAW_FILES` / `RAW_ZILLOW…`),
not reconstructed in the package** (`.claude/CLAUDE.md` §6). The notebook entry
passes `RAW_FILES` into `VolumeFileWriter`; the writer only joins
`<volume>/<filename>`.

**Atomicity footnote.** `shutil.copy` to a Volume is not atomic, but downloads are
a discrete step that completes before any Bronze read — no concurrent reader — so
copy-to-final is acceptable. Copy-to-`.part`-then-rename-within-the-Volume is
optional hardening.

## 8.1 Environment wiring — `notebook_init` is the bootstrap; the notebook is the composition root

The framework does **not** detect its environment (fragile, especially on
serverless, which uses auto-upgraded *environment versions*, not a readable
runtime version — Verified via docs). It follows the DI rule: **the composition
root is environment-specific; the core is environment-agnostic.**

**On Databricks the composition root is a thin notebook** whose first cell is
`%run "../../libs/notebook_init"`. notebook_init injects everything the entry
needs, so the entry is ~5 lines:

```python
# bronze/download_sources.ipynb  (cell 1)
%run "../../libs/notebook_init"
# → injects CATALOG, AUDIT, RAW_FILES, RAW_ZILLOW…, STATUS_*, PIPELINE_RUN_ID,
#   pipeline_step_log_upsert, F, datetime, spark, dbutils, …

# (cell 2)
import uuid
from functools import partial
from data_fetch import run_all, SOURCES, RunContext, VolumeFileWriter, \
    DownloadJournal, DatabricksSecretResolver
from pipeline_logging import download_log_insert, download_log_last_sha256

ctx = RunContext(
    catalog=CATALOG, pipeline_run_id=PIPELINE_RUN_ID, step_log_id=str(uuid.uuid4()),
    audit_schema=AUDIT, scratch_dir=__import__("tempfile").gettempdir(),
    now=lambda: datetime.now(timezone.utc),
)
run_all(
    SOURCES, ctx,
    writer  = VolumeFileWriter(RAW_FILES),                       # base path from notebook_init
    journal = DownloadJournal(
        record      = partial(download_log_insert, spark, AUDIT),
        last_sha256 = partial(download_log_last_sha256, spark, AUDIT),
    ),
    secrets = DatabricksSecretResolver(dbutils),                 # FRED key (§14 open)
)
```

`PIPELINE_RUN_ID` is **assumed present** (notebook_init resolves widget → init-task
taskValue → `LOCAL_PIPELINE_ID`); this phase does not generate it. `init_pipeline_run_log`
(a `spark_python_task`) is the *pre-bootstrap exception* that mints it before
notebook_init can read it — it is **not** the template for normal tasks.

**Local the composition root is `main()` / pytest** with dummy values:

```python
run_all(
    SOURCES,
    RunContext(catalog="localdev", pipeline_run_id="LOCALDEV",
               step_log_id=str(uuid.uuid4()), audit_schema="localdev.audit",
               scratch_dir=tempfile.gettempdir(), now=lambda: datetime.now(timezone.utc)),
    writer  = LocalFileWriter(local_root),
    journal = DownloadJournal(record=lambda row: None, last_sha256=lambda url: None),  # no-ops
    secrets = DotenvSecretResolver(),                            # reads project-root .env
)
```

### The one remaining environment seam — `SecretResolver`

notebook_init does **not** inject `FRED_API_KEY`. Resolution is environment-specific:

```python
class SecretResolver(Protocol):
    def get(self, key: str) -> str: ...          # key == spec.api_key_env

class DotenvSecretResolver:      # local: reads the project-root .env (resolve by walk-up; §16)
class DatabricksSecretResolver:  # Databricks: dbutils widget or dbutils.secrets.get — OPEN (§14)
```

`FredApiProvider` calls `secrets.get(spec.api_key_env)` — never `os.environ`
directly — so tests inject a `FakeSecretResolver`.

## 8.2 Entry points & invocation — the framework is modules; entries are thin

The framework is **pure Python modules** under `libs/data_fetch/` — no notebooks
*in the package*. It exposes a small, invocation-agnostic API:

```python
def run_all(sources, ctx: RunContext, *, writer, journal, secrets) -> RunSummary: ...
def main(argv: list[str]) -> int: ...   # parse --writer/--root/… → build ctx + collaborators → run_all
```

| Caller | Composition root | Status |
|---|---|---|
| **Local / CI** | `python -m data_fetch …` → `main()` (or pytest calls `run_all` directly) | primary dev loop |
| **Deployed Databricks job** | thin `bronze/download_sources.ipynb` under a **`notebook_task`**, cell 1 `%run notebook_init` (§8.1) | **the deployed entry** — matches `catalog_setup` + the §10 cell-order convention |

**Why `notebook_task`, not `spark_python_task`:** the established bootstrap
(`notebook_init`) is consumed via `%run`, which only works in a notebook. A
notebook entry gets `CATALOG`, `RAW_FILES`, `PIPELINE_RUN_ID`, `AUDIT`, `STATUS_*`,
the logging helpers, `spark`, and `dbutils` for one line of cost. The
`spark_python_task` precedent (`init_pipeline_run_log`) exists only because that
task must run *before* notebook_init is usable — it is the exception. (`main(argv)`
still exists for local/CI and keeps a future python-file task a zero-core change.)

---

## 9. Logging seam — conforms to the functional `pipeline_logging` convention

The project's logging is **functional**: module-level functions in
`pipeline_logging.py` (`pipeline_step_log_upsert`, `ingestion_log_insert`, …),
injected into notebooks by notebook_init. The download framework conforms — it
does **not** introduce a logger class hierarchy. Two new functions are added to
`pipeline_logging.py`:

```python
def download_log_insert(spark, audit_schema, *, download_id, pipeline_run_id,
                        step_log_id, source_system, source_url, landed_file_path,
                        status, http_status_code=None, bytes_downloaded=None,
                        file_sha256=None, download_attempts=None,
                        download_started_ts=None, download_ended_ts=None,
                        error_message=None) -> dict: ...
def download_log_last_sha256(spark, audit_schema, source_url) -> str | None: ...
```

The core sees them only as two injected callables bundled in a `DownloadJournal`
(record + last_sha256). Local = no-ops (a missing audit table must never fail a
local run — explicit requirement). On Databricks they are `partial`-bound to
`spark` + `AUDIT`. Per `pipeline_logging` conventions (`.claude/CLAUDE.md` §11.4 /
§12): `spark` is a parameter; **non-fatal logging errors are swallowed** so a
logging hiccup never rolls back a successful download. `status` values are the
notebook_init `STATUS_*` literals.

### Proposed DDL (added to `AUDIT_DDL.py` as an implementation step — §13)

```sql
CREATE TABLE IF NOT EXISTS {audit_schema}.download_log (
    download_id          STRING      NOT NULL,   -- uuid4, natural key
    pipeline_run_id      STRING      NOT NULL,
    step_log_id          STRING      NOT NULL,
    source_system        STRING      NOT NULL,   -- 'fred' | 'zillow' | 'fhfa' | 'realtor'
    source_url           STRING      NOT NULL,   -- canonical, KEY-FREE url / endpoint
    landed_file_path     STRING      NOT NULL,   -- joins to ingestion_log.source_file_path
    status               STRING      NOT NULL,   -- STATUS_SUCCEEDED | _FAILED | _SKIPPED
    http_status_code     INT,                    -- null for FRED JSON path / no-op
    bytes_downloaded     BIGINT,
    file_sha256          STRING,
    download_attempts    INT,
    download_started_ts  TIMESTAMP   NOT NULL,
    download_ended_ts    TIMESTAMP,
    duration_seconds     DOUBLE,
    error_message        STRING
)
```

The download→ingest gap is a join, not a shared row:
`download_log.landed_file_path = ingestion_log.source_file_path`, then
`ingested_timestamp − download_ended_ts`.

**Integration note (not fixed here):** `AUDIT_DDL.py` calls `_run_ddl`, defined in
`catalog_setup.py`, so it is not standalone — adding `create_download_log` must
import `_run_ddl` or be invoked from the setup notebook that has it in scope.
**Timestamps:** write via the `pipeline_logging` convention; mind the parent
guide's offset-naive/aware gotcha (`F.lit(dt).cast("timestamp")`).

---

## 10. The manifest, fully expressed (all four sources)

`manifest.py` `SOURCES` (URLs/headers per the source READMEs; headers abbreviated
here, exact in code; `BROWSER_UA` is one shared constant — verified sufficient for
all three hosts this session):

```python
SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="zillow", provider="http_file", volume="zillow", user_agent=BROWSER_UA,
        files=(
            SourceFile("zhvi_home_values_metro_monthly.csv",
                url="https://files.zillowstatic.com/research/public_csvs/zhvi/"
                    "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
                fmt="csv",
                expected_header=("RegionID","SizeRank","RegionName","RegionType","StateName"),  # prefix; date tail follows
                note="wide; ZHVI back to 2000; needs wide_to_long downstream"),
            SourceFile("zori_asking_rents_metro_monthly.csv",
                url="https://files.zillowstatic.com/research/public_csvs/zori/"
                    "Metro_zori_uc_sfrcondomfr_sm_sa_month.csv", fmt="csv",
                expected_header=("RegionID","SizeRank","RegionName","RegionType","StateName")),
            SourceFile("inventory_for_sale_metro_monthly.csv",
                url="https://files.zillowstatic.com/research/public_csvs/invt_fs/"
                    "Metro_invt_fs_uc_sfrcondo_sm_month.csv", fmt="csv",
                expected_header=("RegionID","SizeRank","RegionName","RegionType","StateName")),
        ),
    ),
    SourceSpec(
        name="fhfa", provider="http_file", volume="fhfa", user_agent=BROWSER_UA,
        files=(
            SourceFile("hpi_master_all_geographies.csv",
                url="https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv",
                fmt="csv",
                expected_header=("hpi_type","hpi_flavor","frequency","level","place_name",
                                 "place_id","yr","period","index_nsa","index_sa")),
            SourceFile("hpi_purchase_only_metro_quarterly.xlsx",
                url="https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_po_metro.xlsx",
                fmt="xlsx", note="opaque bytes; banner/sheet parsing is a Bronze concern"),
            SourceFile("hpi_all_transactions_metro_quarterly.xlsx",
                url="https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.xlsx",
                fmt="xlsx", note="2-row banner; header handled in Bronze, not here"),
        ),
    ),
    SourceSpec(
        name="realtor", provider="http_file", volume="realtor", user_agent=BROWSER_UA,
        files=(
            SourceFile("inventory_core_metrics_metro_snapshot.csv",
                url="https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
                    "RDC_Inventory_Core_Metrics_Metro.csv", fmt="csv"),
            SourceFile("inventory_core_metrics_metro_history.csv",
                url="https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
                    "RDC_Inventory_Core_Metrics_Metro_History.csv", fmt="csv",
                note="full history ~32 MB; Range-resume capable"),
        ),
    ),
    SourceSpec(
        name="fred", provider="fred_api", volume="fred", api_key_env="FRED_API_KEY",
        files=tuple(
            SourceFile(friendly, series_id=sid, fmt="csv",
                       expected_header=("date","value","realtime_start","realtime_end"))
            for sid, friendly in (
                ("MORTGAGE30US",  "mortgage_rate_30yr_fixed_weekly.csv"),
                ("MORTGAGE15US",  "mortgage_rate_15yr_fixed_weekly.csv"),
                ("FIXHAI",        "housing_affordability_index_monthly.csv"),
                ("MSPUS",         "median_sales_price_us_quarterly.csv"),
                ("UNRATE",        "unemployment_rate_national_monthly.csv"),
                ("MEHOINUSA672N", "real_median_household_income_annual.csv"),
                ("ACTLISCOUUS",   "realtor_active_listing_count_us_monthly.csv"),
                ("CSUSHPISA",     "case_shiller_us_national_sa_monthly.csv"),
                ("CSUSHPINSA",    "case_shiller_us_national_nsa_monthly.csv"),
                ("CPIAUCSL",      "cpi_all_urban_sa_monthly.csv"),   # README-recommended addition
            )
        ),
    ),
)
```

The Volumes (`{catalog}.raw.zillow|fhfa|realtor|fred`) are provisioned by the
existing `catalog_setup.create_volumes()`; `spec.volume` feeds its
`volume_definitions` and is joined onto notebook_init's `RAW_FILES` base at
promote time.

---

## 11. Local test strategy (pytest, no network, no Spark)

- **Inject fakes:** `FakeProvider` (canned bytes / raises on command),
  `LocalFileWriter` over `tmp_path`, a no-op `DownloadJournal`, `FakeSecretResolver`,
  a fixed clock, dummy `RunContext`. No `SparkSession`, no network.
- **Runner lifecycle:** success; validation failure → *no* promote (assert no
  final file) + raise; **abort-on-first** (a failed file stops the batch; later
  files not attempted); retry-then-succeed; retry exhaustion → `STATUS_FAILED`;
  sha no-op → `STATUS_SKIPPED`, no re-promote; **prefix** header match passes for
  Zillow wide, fails on a reordered/renamed leading column.
- **`HttpFileProvider`:** local HTTP server fixture (`pytest-httpserver`) — UA
  header, `Range`/`206` resume, truncated body, `429` backoff. No real CDN hit.
- **`FredApiProvider`:** fake transport with recorded `/series` +
  `/series/observations` JSON; assert synthesized CSV shape, full-history request
  (no `observation_start`), and **`canonical_url` carries no `api_key`**.
- **`LocalFileWriter`:** `tmp_path`; atomic `os.replace` + orphan cleanup.
- **`DotenvSecretResolver`:** finds `.env` by walk-up from a temp project tree.
- **Not unit-tested locally:** `VolumeFileWriter`, `DatabricksSecretResolver`, the
  Spark-bound journal — need a real Volume + catalog; covered by the on-Databricks
  integration test (§12 WS-I). `wide_to_long` has its own tests in the source
  project; out of scope.

**Tooling:** `uv run --python 3.12 -m pytest`. Tests live at the **project root**
(`marketpulse/tests/data_fetch/`), *outside* `databricks_code/` (the bundle root),
so they are inherently outside the bundle sync — see §14 Q5. `pyproject.toml` puts
`databricks_code/libs` on `sys.path`.

---

## 12. Phased, parallelizable implementation plan

```
WS0  Foundations (BLOCKS everything)
     context.py (RunContext), manifest dataclasses, Provider/FileWriter/SecretResolver
     Protocols, ProviderFetch / DownloadLogRow / DownloadJournal types, PROVIDERS
     factory skeleton, module-top constants (BROWSER_UA, retry caps, timeouts).
     Small, must land first.

── after WS0, in PARALLEL ─────────────────────────────────────────────────────
WS-A  HttpFileProvider        — GET+UA, Range resume, probe(), canonical_url
WS-B  FredApiProvider         — series loop, JSON→CSV, full history, probe(),
                                 key via SecretResolver, KEY-FREE canonical_url
WS-C  FileWriters + secrets   — LocalFileWriter, VolumeFileWriter(raw_base),
                                 DotenvSecretResolver
WS-D  Journal + DDL           — download_log_insert / download_log_last_sha256 in
                                 pipeline_logging.py; add create_download_log to AUDIT_DDL.py
WS-E  RetryingProvider        — backoff/jitter/attempt-count Decorator
WS-F  validation.py           — non-empty, Content-Length, CSV prefix-header, sha256
WS-H  Test harness + fakes    — starts on WS0 stubs; fills as A–F land (throughout)

── integration ────────────────────────────────────────────────────────────────
WS-G  DownloadRunner (abort-on-first) + healthcheck mode + run_all/main +
      the download notebook (cell 1 %run notebook_init) + the 4 SOURCES entries
      (depends on A,B,C,D,E,F)

── Databricks-only, LAST (gated on §14) ────────────────────────────────────────
WS-I  On-cluster integration: VolumeFileWriter + Spark-bound journal +
      DatabricksSecretResolver + real download_log write; bundle wiring of the
      download notebook_task with job parameters catalog / shared_lib_path;
      confirm `requests` is available in the serverless environment (§14)
```

**Dependency order:** `WS0 → {A,B,C,D,E,F} ∥ → G → I`; `H` parallels throughout.
The A–F band is six independent workstreams behind frozen WS0 interfaces.

---

## 13. Boundaries (designed-around, not designed)

- **`wide_to_long`** — reused downstream; currently only in
  `re_project_research/src/`. Vendoring into marketpulse is a **separate task**.
- **Audit-table DDL** — we *specify* `download_log` (§9); editing `AUDIT_DDL.py` is
  WS-D.
- **`pipeline_logging.py` reconciliation** — the present file is a stub and
  `init_pipeline_run_log.py` imports names it doesn't yet define
  (`pipeline_log_upsert`, `configure`, `STATUS_RUNNING`), with a leftover
  `vinoworld` default. **Parked** (vinoworld drift, not download-framework work).
  WS-D adds only the two `download_log_*` functions.
- **Job scheduling / orchestration** — Free Edition; deferred.
- **`PIPELINE_RUN_ID` generation** — notebook_init owns it; assumed present.
- **Bronze/Silver column parsing, XLSX banner handling, casting** — Bronze.

---

## 14. Open questions — verify before implementing

Graded per `.claude/CLAUDE.md` §4.

| # | Question | Grade | Probe / resolution |
|---|---|---|---|
| 1 | **Landing a file in a Volume.** Drives `VolumeFileWriter`. | **Verified** (docs) | Standard Python APIs on `/Volumes/...`; FUSE rejects append/random writes; local-disk-then-`copyfile`. Atomic rename not relied upon. |
| 2 | **Zillow CDN / Realtor S3 honor `Range`?** | **Verified** (probed) | Both `206` + `Accept-Ranges`; resume viable. |
| 3 | **FRED rate limit.** | **Projected** (~120/min per README) | Courtesy backoff + honor `429`/`Retry-After`; ~10 series is far under any limit. |
| 4 | **`download_log` ↔ `_run_ddl` location.** | **Verified** (read both) | Add `create_download_log`, import `_run_ddl` or invoke from the setup notebook (WS-D). |
| 5 | **Are root-level tests synced by the bundle?** | **Verified** (memory: bundle root is `databricks_code/`) | Tests at `marketpulse/tests/` are outside the bundle root → not synced. No exclusion needed; just confirm clean import via `pyproject.toml`. |
| 6 | **Realtor full-history size.** | **Verified** (probed) | `Content-Length` ≈ 32 MB (the README figure was already the full file). Zillow ZHVI ≈ 4.4 MB. Range-resume optional. |
| 7 | **FRED key on Databricks** — secret scope vs widget vs job param. Drives `DatabricksSecretResolver`. | **Projected** | Try `databricks secrets`; if unavailable on Free Edition, pass `FRED_API_KEY` as a job/widget param (like `catalog`) read in the entry notebook. |
| 8 | **Is `requests` (and the synced package) importable on serverless?** A synced `.py` is not pip-installed; `requests` must be in the serverless base env or declared as a job dependency. | **Projected** | On the first WS-I run, `import requests` in the entry notebook; if absent, declare it via the job's serverless `environments`/`dependencies`. Confirm `sys.path` reaches `files/libs` (notebook_init already extends it). |

---

## 15. Confidence summary

- **Verified:** the two-family split, source URLs/auth/formats, `download_log` vs
  `ingestion_log` modeling, discard-all-windowing, the Python-registry pattern
  match; **Volumes accept standard Python file APIs with local-disk-then-copy** (no
  append/random writes); **serverless uses environment versions, not a readable
  runtime version** (so wiring is composition-root, not sniffed); the
  `notebook_task` + `%run notebook_init` entry pattern; reuse of notebook_init's
  `RAW_FILES`/`STATUS_*`/`AUDIT`/`PIPELINE_RUN_ID`; the functional `pipeline_logging`
  convention; and (probed) Zillow CDN + Realtor S3 honor `Range` with modest file
  sizes (~4.4 / ~32 MB).
- **Projected:** FRED rate limit; FRED key delivery on Databricks (Q7); `requests`/
  package availability on serverless (Q8) — all in §14 with resolutions.
- **Guessing:** none shipped. The earlier `/local_disk0/tmp` assumption was caught
  in review and removed in favor of `tempfile.gettempdir()`.

---

## 16. Implementation Contract — guardrails for `/sc:implement`

Normative. These are the load-bearing rules; violating one is a defect even if the
code "works." **If any conflict with §1–§15, this section wins — raise it.**

1. **Pure package.** `databricks_code/libs/data_fetch/` imports neither
   `notebook_init`, `dbutils`, nor a live `SparkSession` at module load. `spark`/
   `dbutils` only ever arrive as arguments (via the journal/secret callables built
   in the entry). The package must import and unit-test with no Databricks present.
2. **Fetch deps.** Download layer uses **stdlib + `requests` only**. No `pandas`,
   `openpyxl`, or `pyspark` in the fetch path. Files land as **opaque bytes**.
3. **Abort on first failure.** `run_all` stops at the first file that fails
   (validation, exhausted retries, or write). The failed file gets a
   `STATUS_FAILED` `download_log` row; **remaining files are not attempted**;
   `run_all` raises. No continue-and-collect.
4. **One journal row per attempted file**, status ∈ {`STATUS_SUCCEEDED`,
   `STATUS_FAILED`, `STATUS_SKIPPED`} using the notebook_init `STATUS_*` literals
   (do not invent strings). `STATUS_SKIPPED` ⇔ sha matched `last_sha256(canonical_url)`.
5. **Never log the API key.** `source_url` written to `download_log` is the
   **key-free `canonical_url`** from `ProviderFetch`. For FRED that is the
   observations endpoint with `series_id` only — strip `api_key`.
6. **Header validation = PREFIX match, CSV only.** First `len(expected_header)`
   columns must equal `expected_header`. `xlsx`/`json` are not header-validated
   (opaque). `expected_header=None` skips the check.
7. **Destination path comes from notebook_init.** On Databricks, the entry passes
   `RAW_FILES` into `VolumeFileWriter`; the writer joins `<volume>/<filename>`.
   **Do not reconstruct `/Volumes/...` inside the package.** Local writer joins a
   `local_root`.
8. **Scratch dir = `ctx.scratch_dir`, default `tempfile.gettempdir()`.** Never
   hardcode `/local_disk0`. Range-resume and all partial writes happen in scratch,
   never on the Volume.
9. **`PIPELINE_RUN_ID` is assumed present** (from notebook_init; dummy
   `"LOCALDEV"` locally). The package never mints it. **`step_log_id`** is minted
   once per run (`uuid4`) by the entry and stamped on every `download_log` row.
10. **Logging is functional.** Audit writes go through `pipeline_logging.
    download_log_insert` / `download_log_last_sha256`; the core sees two injected
    callables (`DownloadJournal`). **No logger class hierarchy.** Non-fatal logging
    errors are swallowed — a logging failure never rolls back a successful download.
11. **Constants centralized** at module top, `UPPER_SNAKE_CASE`: `BROWSER_UA`,
    retry attempt cap, backoff base/jitter, HTTP timeouts. No magic literals in two
    places (`.claude/CLAUDE.md` §6).
12. **Sequential** downloads this phase (no concurrency).
13. **Tests:** no network, no `SparkSession`; inject fakes; live at
    `marketpulse/tests/data_fetch/` (outside the bundle root).
14. **Safety Protocol.** `/sc:implement` produces a numbered plan and **stops for
    approval before writing code** (`.claude/CLAUDE.md` §3). Build WS0 first, then
    the A–F band.

**Next step:** `/sc:implement` WS0 against §16, then fan out across WS-A…F.
```
