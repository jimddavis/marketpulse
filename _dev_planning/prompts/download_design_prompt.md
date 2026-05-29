 /sc:design Production-grade, extensible data-acquisition framework for the marketpulse Databricks medallion project.

  GOAL
  Design (not yet implement) a framework that downloads raw files from multiple external real-estate/economic data sources and lands them in their correct Unity Catalog Volume. It
  must be local-first (developed and unit-tested with local Python + PySpark before bundle deployment) and make adding a new source a config-only change. A Weather source will be
  added later — the design must absorb it without code changes to the core.

  AUTHORITATIVE INPUTS (read these first)
  - Source specs (URLs, auth, formats, schemas, available ranges, gotchas) — read all four:
    _dev_planning/datasource_descriptions/{fred,zillow,fhfa,realtor}_README.md
  - Existing download example (FRED, stdlib only): /home/dev/work/AI/databricks/re_project_research/scratch/fetch_fred_samples.py (NOTE: its per-cadence windowing logic is to be
  DISCARDED — see scope below)
  - Reusable PySpark wide→long normalizer (Zillow needs it; it is a DOWNSTREAM transform, not part of download): /home/dev/work/AI/databricks/re_project_research/src/wide_to_long/
  - Reusable provisioning (creates catalog.raw.<name> volumes + archive subfolders): databricks_code/libs/catalog_setup.py
  - Logging seam (stubbed signatures; download logging will plug in here once audit DDL exists): databricks_code/libs/pipeline_logging.py
  - Bundle/target/catalog conventions: databricks_code/databricks.yml
  - Project rules you MUST obey: .claude/CLAUDE.md (Safety Protocol, confidence grading, match-existing-patterns, centralize load-bearing values, three-part table names, Volumes
  not /dbfs, uv + python3.12 locally)

  THE FOUR SOURCES (two download families)
  - Family A (HTTP file pull, no auth, browser User-Agent): Zillow (3 wide CSVs via files.zillowstatic.com CDN), FHFA (master CSV long + 2 quarterly XLSX, AT XLSX has a 2-row
  banner), Realtor.com (snapshot + ~32MB+ history CSV via econdata S3 bucket).
  - Family B (API, FRED_API_KEY free/registration-gated): FRED, ~10 series (the 9 in the README + recommended CPIAUCSL), per-series cadence, JSON→CSV.  FRED_API_KEY is in the .env file.

  HARD REQUIREMENTS
  - Pull ALL available history (floor: since 2010; go back to 2000+ where the source offers it). NO date-range windowing anywhere — strip every windowing mechanism from the
  research code.
  - Download stage is plain Python (stdlib/requests). PySpark is used only DOWNSTREAM to read the landed file and normalize (e.g. wide_to_long for Zillow). State this boundary
  explicitly.
  - Every download attempt is logged (status, bytes, duration, error). Logging goes through the pipeline_logging seam; the audit-table DDL is defined in file AUDIT_DDL.py, which is code extracted from a prior project that used these tables.

  Prior research recommended the following column additions were  `ingestion_log`, which are NOT in AUDIT_DDL.py

| Column | Type | Why |
|---|---|---|
| `source_url` | STRING | Canonical URL or API endpoint fetched. Required for replay + "where did this row come from" diagnostics. |
| `bytes_downloaded` | BIGINT | Sanity check vs prior runs. Catches truncated downloads and silent publisher schema changes (1KB where 30MB expected). |
| `file_sha256` | STRING | Detects publishers silently restating the same URL with different bytes (Zillow monthly, FHFA quarterly). Lets idempotent Bronze MERGE answer "is this really new data?" before re-ingesting. |
| `http_status_code` | INT | Nullable. 200 for normal HTTP; null for FRED JSON-stream path or cached no-op. |
| `download_attempts` | INT | Retry-with-backoff visibility. `1` for clean fetches; >1 surfaces transient-error patterns. |
| `download_started_ts` | TIMESTAMP | Separates "download took 90s" from "ingest took 2s" — two distinct failure modes. |
| `download_ended_ts` | TIMESTAMP | Pairs with the existing `ingested_timestamp` to make the download↔ingest gap visible. |


For local execution, a no-op can be substituted for actual logging.  Do not fail locally due to missing logging tables.


  - Land raw files into Volumes in production (/Volumes/<catalog>/raw/<volume>/...) and a local mirror directory in dev/test. Treat the destination as an injected Sink/root.
  - Adding a source = adding a manifest entry, not editing core code.

  ANSWER THESE DESIGN QUESTIONS EXPLICITLY (with rationale + tradeoffs)
  1. Metadata-driven manifest: YAML vs Python dataclass registry vs Delta table. Recommend one; justify. (Config declares sources; tables are for logging.)
  2. Dependency injection + provider Strategy: define the Provider protocol and the HttpFileProvider / FredApiProvider implementations; what gets injected (provider, Sink, logger,
  clock).
  3. Which GoF patterns earn their place (Strategy, Registry/Factory, Template Method lifecycle, Adapter for Sink + XLSX/CSV, optional Decorator for retry) — and which to
  deliberately NOT use at this scope, with reasons. Avoid over-engineering; this is Free Edition + a learning project.
  4. Resilience: atomic temp-then-rename landing; retry w/ exponential backoff; HTTP Range resume for large files; post-download validation (Content-Length, non-empty,
  expected-header check à la the research's per-file header validation); a healthcheck/probe mode for URL drift; idempotent re-runs.
  5. Local↔Volume path strategy: single injected root vs full Sink abstraction. Address the on-Databricks-job (direct /Volumes write) vs local-dev-push-to-remote-Volume (SDK
  files.upload) difference.

  DELIVERABLES
  A. An architecture design doc under __dev_planning/design_docs (proposed module/package layout, the Provider/Sink/Logger interfaces with signatures, the manifest schema with all four
  sources expressed in it, the resilience strategy, the local↔Volume strategy, the logging seam contract, and a local pytest strategy with injected fakes — no network in unit
  tests).
  B. A phased, PARALLELIZABLE implementation plan (the user wants this multi-tasked): identify independent workstreams (e.g. core protocol+registry, HttpFileProvider,
  FredApiProvider, Sink/local+Volume, resilience/retry, manifest+config, test harness) and their dependency order.
  C. An "open questions — verify before implementing" section grading each item Verified/Projected/Guessing, covering at minimum: how a Databricks job lands a file into a Volume,
  whether the Zillow CDN / Realtor S3 honor HTTP Range, FRED's actual rate limit. Offer a cheap probe for each.

  CONSTRAINTS
  - Follow the Safety Protocol: produce the numbered plan and STOP for approval before writing any file.
  - Grade every Databricks-specific claim (Verified/Projected/Guessing).
  - Match existing repo patterns (catalog_setup style, pipeline_logging signatures, bundle variable/catalog conventions). Do not normalize minority patterns silently.
  - Out of scope: the actual wide_to_long normalization (reuse the existing module downstream), the audit-table DDL, job scheduling. Note them as boundaries, don't design them.
