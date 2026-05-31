# Bronze → Silver pipeline overview

**Status:** Draft — explanatory design, not implementation guidance
**Author:** generated 2026-05-21 via `/sc:design`
**Approved:** _Not yet approved_ — purely pedagogical at this stage. When this doc transitions from "help me understand" to "build to this spec," update this line with a date.

---

## Goal of this document

A shared mental model of how the 4 chosen data sources move from publisher → Bronze → Silver. **No DDL, no PySpark, no notebook code** — those belong to the future implementation project. This is the picture you can sketch on a napkin to explain the system to someone else.

## Scope

- **In scope:** Zillow, Realtor.com, FHFA HPI, FRED (the macro keep-list: `MORTGAGE30US`, `MEHOINUSA672N`, optionally `UNRATE`).
- **Out of scope:** Case-Shiller, Redfin, Census BPS, HUD CHAS — those are samples on disk but not committed to MVP.
- **Out of scope:** Gold layer. Gold is where source-blended facts live; this doc stops at the Silver boundary so the integration story is clear.

---

## The four sources at a glance

| Source | Native shape | How you get it | Grain | Cadence |
|---|---|---|---|---|
| Zillow | Wide CSV (date columns) | HTTPS GET from CDN — 3 files | Metro × month | Monthly |
| Realtor.com | Long CSV (47 cols) | HTTPS GET from S3 — 2 files | Metro × month | Monthly + weekly |
| FHFA HPI | 1 long CSV (master) + 2 XLSX (PO/AT) | HTTPS GET — 3 files | Metro × quarter | Quarterly (MSA); monthly (USA/division) |
| FRED | JSON observations | HTTPS GET — 1 call per series (3 series) | National × varies | Per-series (W/M/A) |

The shapes are deliberately heterogeneous — exposure to that heterogeneity is the learning value of the project. Bronze preserves the heterogeneity; Silver reconciles it.

---

## The end-to-end picture

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                       PUBLISHERS                            │
                  │                                                             │
   ┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐      │
   │ Zillow   │   │ Realtor.com  │   │   FHFA       │   │   FRED API   │      │
   │ CDN      │   │   S3         │   │  bulk URLs   │   │              │      │
   └────┬─────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘      │
        │                │                  │                  │              │
        │  HTTPS GET     │  HTTPS GET       │  HTTPS GET       │  HTTPS GET   │
        │  → 3 CSVs      │  → 2 CSVs        │  → 1 CSV + 2 XLSX│  → N JSONs   │
        │                │                  │                  │              │
        ▼                ▼                  ▼                  ▼              │
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  Volume: /Volumes/<catalog>/<schema>/raw/{zillow,realtor,fhfa,fred}/    │
   │  (landing zone — files-as-fetched, no transformation)                   │
   └────┬───────────────┬──────────────────┬──────────────────┬──────────────┘
        │               │                  │                  │
        │  read         │  read            │  read            │  read
        │  + cast       │  + cast          │  + cast          │  + flatten
        │  to string    │  to string       │  to string       │  JSON to rows
        ▼               ▼                  ▼                  ▼
   ┌────────────┐  ┌────────────┐    ┌────────────┐    ┌────────────┐
   │ bronze.    │  │ bronze.    │    │ bronze.    │    │ bronze.    │
   │ zillow_    │  │ realtor_   │    │ fhfa_      │    │ fred_      │
   │ metro_     │  │ metro_     │    │ hpi_*      │    │ series_    │
   │ wide       │  │ monthly    │    │            │    │ observa-   │
   │            │  │            │    │            │    │ tions      │
   └─────┬──────┘  └─────┬──────┘    └─────┬──────┘    └─────┬──────┘
         │ unpivot       │ cast            │ cast            │ cast
         │ wide → long   │ + standardize   │ + standardize   │ + standardize
         │ + cast        │ names           │ names           │ names
         ▼               ▼                 ▼                 ▼
   ┌────────────┐  ┌────────────┐    ┌────────────┐    ┌────────────┐
   │ silver.    │  │ silver.    │    │ silver.    │    │ silver.    │
   │ fact_      │  │ fact_      │    │ fact_      │    │ fact_      │
   │ zillow_    │  │ realtor_   │    │ fhfa_      │    │ fred_      │
   │ metro_     │  │ metro_     │    │ metro_     │    │ macro_     │
   │ monthly    │  │ monthly    │    │ quarterly  │    │ monthly    │
   └────────────┘  └────────────┘    └────────────┘    └────────────┘
         │               │                 │                 │
         │   all 4 facts join via dim_geo + dim_date         │
         │   (the integration plumbing in silver schema)     │
         └───────────────┴─────────────────┴─────────────────┘
                         │
                         │  ── future Gold work, out of scope here ──
                         ▼
                  ( source-blended facts at Gold )
```

The **shape of Silver** is the load-bearing decision in this doc. Read on.

---

## Bronze layer — "what arrived, faithfully"

### Principles

1. **One Bronze table per source-file-pattern.** If a source produces three files with different schemas (e.g., FHFA master CSV vs PO XLSX vs AT XLSX), that's three Bronze tables. Don't pre-merge at Bronze — you'll lose the ability to audit a single file's contents.
2. **All columns typed as STRING.** No casting at Bronze. If the source publishes `value="6.36"`, that's a string. If FHFA's AT XLSX has `'-'` as a null sentinel and `'(2.56)'` as a parenthesized standard error, those go through as-is.
3. **Always preserve `source_file_path` as a column.** Every Bronze row knows which file it came from. This is what makes reprocessing tractable.
4. **Audit columns are mandatory.** Per the [parent CLAUDE.md] (which the implementation project will follow): `inserted_ts`, `run_id`, `source_file_path`, plus a `row_hash` if MERGE-based idempotency is needed.
5. **Idempotent writes.** Re-running the pipeline on the same input must produce the same Bronze table. Choice of strategy depends on the source — see per-source notes below.

### Conceptual Bronze tables

(Columns shown conceptually — not actual DDL. Authoritative DDL now lives in
`databricks_code/libs/ddl/bronze_ddl.py`.)

> **REVISED 2026-05-30 — 6 Bronze tables, not the original 8.** Three points below
> were superseded after this section was first written; the three confirmed decisions
> are reflected inline:
> 1. **Zillow is now LONG at Bronze, not wide.** The `wide_to_long` transpose step was
>    built and verified, landing typed long Parquet at `raw/zillow/_long/`. Bronze reads
>    that Parquet — the "keep it wide, unpivot at Silver" rationale is retired.
> 2. **FHFA = 1 table, not 3.** The two quarterly xlsx (PO, AT) are verified subsets of
>    `hpi_master.csv` and are commented out of the manifest. Only `fhfa_hpi_master` remains.
> 3. **FRED and Realtor stay consolidated** (one table each, by schema-shape) — confirmed
>    against a "table per file" alternative, which was rejected.

#### `bronze.zillow_zhvi`, `bronze.zillow_zori`, `bronze.zillow_inventory` — Zillow long

```
+ region_id                  STRING
+ size_rank                  STRING
+ region_name                STRING
+ region_type                STRING
+ state_name                 STRING
+ period_date                DATE     ← typed (wide_to_long period_end); NOT all-STRING
+ value                      DOUBLE   ← typed; nullable (Zillow legitimately omits values)
+ source_file_path           STRING   ← logical CSV name, injected from ZILLOW_FEEDS
+ inserted_ts                TIMESTAMP
+ run_id                     BIGINT
```

Three tables, one per feed, read from the `raw/zillow/_long/<stem>_long/` Parquet datasets
produced by the wide→long transpose step (NOT the wide CSVs). `period_date`/`value` are the
**documented exception** to bronze-all-STRING (CLAUDE.md §11.1) — the Parquet is already
typed. The Parquet keeps source CamelCase id names (`RegionID`, …); the loader aliases them
to the snake_case columns above. The `_long` Parquet carries no original-CSV provenance, so
the loader injects `source_file_path` as the logical CSV name from `ZILLOW_FEEDS`.

Idempotency strategy: **MERGE on `(region_id, period_date)`**. Single `value` payload →
`UPDATE SET *` on match, so no `row_hash` is needed. A refreshed snapshot with revised values
updates in place; re-running the same snapshot is a no-op.

#### `bronze.realtor_metro_monthly`

```
+ <47 publisher columns, all STRING>
   month_date_yyyymm, cbsa_code, cbsa_title, HouseholdRank,
   median_listing_price, median_listing_price_mm, median_listing_price_yy,
   active_listing_count, ... etc.
+ source_file_path           STRING
+ inserted_ts                TIMESTAMP
+ run_id                     BIGINT
```

Realtor publishes one snapshot file + one history file with the same schema. **Both feed the same Bronze table** because the schema matches. The history file is the long backfill; the snapshot file is what arrives monthly.

Idempotency: **MERGE on `(cbsa_code, month_date_yyyymm)`** with `row_hash` over the metric columns. The same metro-month from snapshot vs history collapse to one row.

#### `bronze.fhfa_hpi_master`

One Bronze table — master CSV only. The two quarterly xlsx (PO, AT) were dropped: they are
verified subsets of `hpi_master.csv` and are commented out of the manifest. The master file
actually has **12** columns (`rstderr`, `note` follow `index_sa`), all preserved as STRING.

```
bronze.fhfa_hpi_master
+ hpi_type, hpi_flavor, frequency, level, place_name, place_id,
  yr, period, index_nsa, index_sa, rstderr, note     (all STRING)
+ source_file_path, inserted_ts, run_id
```

Idempotency: **MERGE on `(hpi_type, hpi_flavor, frequency, level, place_id, yr, period)`** —
the full grain. The master file mixes monthly + quarterly frequencies and multiple
`hpi_type`/`hpi_flavor` variants per place, so the shorter `(place_id, yr, period)` key would
collapse distinct rows. Verified against the downloaded file. Re-publishes on every release.

#### `bronze.fred_series_observations`

```
+ series_id                  STRING   ← MORTGAGE30US, MEHOINUSA672N, UNRATE — injected from the manifest (not in the file)
+ observation_date           STRING   ← source col 'date', renamed off the reserved word; 'YYYY-MM-DD'
+ value                      STRING   ← '6.36' or '.' for missing
+ realtime_start             STRING
+ realtime_end               STRING
+ source_file_path           STRING   ← effectively the API URL, e.g. 'fred://MORTGAGE30US?observation_start=2025-05-21'
+ inserted_ts                TIMESTAMP
+ run_id                     BIGINT
```

Unlike the bulk-CSV sources, FRED is an API. The 10 series go into a single Bronze table with `series_id` as the discriminator — `series_id` is injected by the loader from the manifest, since the CSV itself carries only `date,value,realtime_start,realtime_end`. The "file path" is conceptually the API call.

Idempotency: **MERGE on `(series_id, observation_date, realtime_start)`** — the `realtime_start` is essential because FRED publishes vintages; the same `(series, date)` can have multiple revisions over time. For non-vintage queries (current values only), `realtime_start` equals the API call date and effectively de-duplicates by source-call.

### Per-source download mechanics — already documented

The download mechanics live in the per-source READMEs at `data/samples/<source>/README.md`. The Bronze pipeline literally **runs the same fetch script** that produced the sample, just against the full date range instead of the windowed slice. That's the value of the README-as-handoff-doc work already done — the Bronze code is the windowless cousin of the existing `fetch_<source>_samples.py` scripts.

---

## Silver layer — "the same metro, the same month, in shared vocabulary"

### Two big decisions

Two decisions determine the entire Silver shape. Lock these first; the rest follows.

#### Decision 1 — One Silver fact per source, or one unified fact?

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **A — Per-source fact tables** (`silver.fact_zillow_metro_monthly`, `silver.fact_realtor_metro_monthly`, etc.) | Each source independently debuggable. Schema drift on one source doesn't break another. Easy to add a new source. | Need to join 4 facts in Gold to ask cross-source questions. | **A** — this is the canonical medallion pattern. Source fidelity at Silver; blending at Gold. |
| **B — Unified `silver.fact_metro_monthly`** | One stop shop for downstream queries. Fewer joins. | Schema change in one source forces a Silver-wide migration. Sources with different cadences (FHFA quarterly vs Zillow monthly) need pre-broadcast at Silver, which contaminates Silver with Gold-shaped logic. | Skip. |

**Pick A.** Per-source Silver fact tables. Cross-source blending lives at Gold.

#### Decision 2 — Where does the geography crosswalk live?

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **A — Inside `silver.dim_geo`** as enrichment columns (`zillow_region_id`, `cbsa_code`, ...) on one geo dimension. | Single conformed geography. Every fact joins through the same dim. Crosswalk reviewed once. | `dim_geo` carries nullable `zillow_region_id` for the ~5% of CBSAs Zillow doesn't cover. | **A** — conformed dimension is the whole point of the medallion. |
| **B — Separate `silver.xref_zillow_to_cbsa` table** as a standalone crosswalk. | Crosswalk is a first-class artifact. | Every fact-to-fact join walks through `dim_geo` AND xref — extra join, more error-prone. | Skip. |

**Pick A.** The crosswalk is a column on `dim_geo`, not a separate table.

### Conceptual Silver model

```
silver schema:

  dim_geo                    ← THE integration point
    geo_key (surrogate)
    cbsa_code                ← canonical metro identifier
    cbsa_title
    zillow_region_id         ← nullable for metros Zillow doesn't cover
    primary_state_postal
    state_list               ← 'NY-NJ-PA-CT' for multistate
    household_rank
    population_rank
    is_top_50
    cbsa_vintage             ← 'OMB 2023' or similar
    inserted_ts, updated_ts

  dim_date
    date_key (surrogate)
    full_date
    year
    month
    quarter
    month_start
    quarter_start

  fact_zillow_metro_monthly
    geo_key (FK → dim_geo)
    date_key (FK → dim_date)
    typical_home_value       ← DOUBLE, ZHVI: smoothed mid-tier home value USD
    typical_rent             ← DOUBLE, ZORI: observed asking rent USD/month
    inventory_active         ← BIGINT
    source_file_path
    inserted_ts, updated_ts

  fact_realtor_metro_monthly
    geo_key, date_key
    median_listing_price     ← DOUBLE
    active_listing_count     ← BIGINT
    median_days_on_market    ← DOUBLE
    new_listing_count        ← BIGINT
    price_reduced_share      ← DOUBLE (decimal fraction)
    pending_ratio            ← DOUBLE
    ... (14 base metrics + their _mm/_yy companions, OR drop the _mm/_yy if Gold recomputes them)
    source_file_path
    inserted_ts, updated_ts

  fact_fhfa_metro_quarterly
    geo_key, date_key (quarter-start)
    flavor                   ← 'PO' / 'AT' / 'ED'  (which methodology variant)
    index_nsa                ← DOUBLE
    index_sa                 ← DOUBLE (nullable; AT is always null)
    standard_error           ← DOUBLE (AT only)
    source_file_path
    inserted_ts, updated_ts

  fact_fred_macro_monthly
    date_key (national — no geo_key, or geo_key points to a "USA" row)
    mortgage_30yr_avg        ← DOUBLE, monthly mean of weekly observations
    unemployment_rate        ← DOUBLE
    real_median_income       ← DOUBLE, annual forward-filled
    income_basis_year        ← INT (the actual annual year carried forward)
    source_file_path
    inserted_ts, updated_ts
```

### What Silver does per source

| Transform | Why |
|---|---|
| **Cast STRING → typed** (BIGINT, DOUBLE, DATE, TIMESTAMP) | Bronze is faithful; Silver is usable. |
| **Standardize column names** to `snake_case` | `CBSACode` → `cbsa_code`, `Area Name` → `area_name`, etc. |
| **Unpivot Zillow wide → long** | Zillow's date-columns become rows of `(date, value)`. |
| **Filter to metro grain** | FHFA master is mixed-grain; Silver fact is metro-only. State/division rollups become their own dim/fact pair if needed (out of scope here). |
| **Lookup geo_key** | Every fact row gets `geo_key` from `dim_geo`. The Zillow → CBSA crosswalk happens HERE. |
| **Handle null sentinels** | FHFA AT's `'-'` → NaN; FRED's `'.'` → NaN; etc. |
| **Quarantine bad rows** | Rows that fail type-cast or geo lookup go to `silver.quarantine_<source>` with a reason column, **not** silently dropped. |
| **Resolve revisions** | For FRED, the canonical row is the latest `realtime_end='9999-12-31'`. Older vintages are still in Bronze; Silver picks the current-vintage view. |

### What Silver does NOT do

| Don't | Why |
|---|---|
| Blend metrics across sources into one fact row | That's Gold. Mixing breaks single-source debugging. |
| Compute affordability ratios | Derived metrics are Gold. Silver carries inputs. |
| Broadcast FHFA quarterly to monthly | Decision belongs to Gold (broadcast vs interpolate vs leave-as-is) since it depends on the analysis. |
| Apply business-rule joins (e.g., "drop metros with <1000 listings") | Business rules belong to Gold or to BI. Silver is conformed but unfiltered. |
| Pivot wide for reporting convenience | Long format ages better. Pivot at the consumer layer. |

---

## The crosswalk seeding sequence

Because the Zillow → CBSA crosswalk is the load-bearing piece of `dim_geo`, it's worth being explicit about how it gets built:

```
Step 1 (in this scoping project, before implementation)
  scratch/build_zillow_cbsa_crosswalk.py
   ├ Read Zillow's RegionID / RegionName / StateName (from existing sample)
   ├ Read CBSA codes + titles (from Realtor or FHFA sample)
   ├ Programmatic fuzzy match by city + state
   ├ Output: data/crosswalks/zillow_to_cbsa.csv
   └ Top-50 manual verification pass

Step 2 (in the future implementation project)
   The committed crosswalk CSV becomes the seed for dim_geo
   ├ Loaded once during catalog setup (setup/seed_dim_geo notebook)
   ├ Re-seeded only when Zillow adds new metros or OMB redefines CBSAs
   └ Treated as reference data, not pipeline output
```

The crosswalk artifact's lifecycle is **longer** than any single pipeline run — that's why it deserves to be a committed file, not regenerated from scratch each run.

---

## Cadence-mismatch handling (preview of a Gold concern)

Silver leaves cadence native to the source: Zillow/Realtor/FRED monthly, FHFA quarterly. The cadence reconciliation question — "do you broadcast FHFA quarterly to monthly, or interpolate, or leave it sparse?" — is a Gold-layer concern, NOT a Silver concern. Mention it in `scope_decisions.md` when it gets written; defer the choice until Gold is being built.

The reason to keep this out of Silver: different analyses want different choices. A YoY comparison at the quarter grain doesn't want broadcast — it wants native quarters. A monthly affordability ratio chart wants broadcast. Locking the choice at Silver loses one of those.

---

## Quality gates between layers

| Gate | What it checks |
|---|---|
| **Bronze write** | Row count read from source = row count written to Bronze. No silent drops. |
| **Bronze → Silver** | Every Bronze row either lands in Silver or in `quarantine_<source>` with a reason. Zero silent drops. |
| **Silver geo lookup** | Every Silver fact row has a non-null `geo_key`. Failures → quarantine with reason `'unmatched_geography'`. |
| **Silver type cast** | Every typed column passes the cast (no `errors='coerce'` swallowing failures silently). Failures → quarantine with reason `'cast_failed: <column>'`. |

These are the checks that catch a crosswalk gap, an upstream schema change, or a publisher's surprise sentinel value. They're the test suite of the pipeline.

---

## What this doc does NOT cover (intentionally)

- **DDL.** No `CREATE TABLE` statements. The implementation project owns those.
- **PySpark code.** No DataFrame transformations. The implementation project owns those.
- **Notebook layout.** Bronze notebook structure, orchestrator structure — implementation project owns those, governed by the parent `CLAUDE.md`.
- **Gold model.** Out of scope here. Mentioned only at the boundaries.
- **Streaming, Auto Loader, DLT.** Free-Edition constraint per project rules — batch only, run on demand.

---

## Open questions to settle before implementation

1. **Do you carry FHFA flavors as separate rows or separate columns?** Three flavors (PO / AT / ED) × N quarters could be 3 rows per metro-quarter OR 3 columns per metro-quarter. Long format (rows) is more flexible but harder to chart. Recommendation defaults to long but worth deciding consciously.
2. **Do you keep Realtor's pre-computed `_mm` / `_yy` columns at Silver?** They're deterministic from base + lag. Keeping them: zero compute downstream, slight schema bloat. Dropping them: ~33 fewer columns per Silver row, but every analysis recomputes. **Recommend dropping** — derive at Gold.
3. **Does `dim_geo` include only the ~50 MVP metros, or all CBSAs?** Smaller dim = simpler dev; larger dim = future-proof. **Recommend "all CBSAs with data in any source"** — start broad, filter at Gold.
4. **National rows in `dim_geo`?** FRED is national; needs a `geo_key`. Either a special "USA" row in `dim_geo` or a separate national dim. **Recommend the USA row** — keeps the model uniform.

---

## Sequence of work this implies

(Not approved — for discussion.)

1. Build Zillow → CBSA crosswalk under `scratch/` → save to `data/crosswalks/zillow_to_cbsa.csv`. *Still inside this scoping project.*
2. Write `dimensional_model_sketch.md` (Phase 4) — formalize the model above.
3. Write `scope_decisions.md` (Phase 2) — capture the four open questions as committed decisions.
4. Hand off to implementation project. Implementation project builds Bronze → Silver per this doc, with the crosswalk CSV as seed data for `dim_geo`.

Step 1 is cheap (~1.5 hours) and the highest-information action. Step 2 is the official Phase 4 deliverable. Step 3 may be folded into Phase 2 or kept separate.
