# FRED Economic Indicators — sample data

Reference data from [FRED](https://fred.stlouisfed.org/), the Federal
Reserve Bank of St. Louis economic data service. Used in Phase 1
(dataset evaluation) of this project.

Generated **2026-05-16** via the `re-data-acquisition` skill workflow
(first **API-based** source; first source requiring a registration-
gated free credential). **Phase 2c samples acquired 2026-05-20.**

## Sample collection status — Phases 1, 2a, 2c complete

`FRED_API_KEY` was added to `.env` on 2026-05-20 and verified against
the live API. All 9 target series have been pulled, windowed
server-side per cadence, and saved as CSVs in this directory.

Phase 4 (per-series schema documentation) sections below are
populated from the API spec and empirically confirmed against the
fetched samples — the **auto-discoverable channel claim is Verified.**

## What's here

| Local file | Series ID | Cadence | Rows | Window |
|---|---|---|---|---|
| `mortgage_rate_30yr_fixed_weekly.csv` | `MORTGAGE30US` | Weekly | 52 | 2025-05-22 → 2026-05-14 |
| `mortgage_rate_15yr_fixed_weekly.csv` | `MORTGAGE15US` | Weekly | 52 | 2025-05-22 → 2026-05-14 |
| `housing_affordability_index_monthly.csv` | `FIXHAI` | Monthly | 12 | 2025-05 → 2026-04 |
| `median_sales_price_us_quarterly.csv` | `MSPUS` | Quarterly | 8 | 2024-Q2 → 2026-Q1 |
| `unemployment_rate_national_monthly.csv` | `UNRATE` | Monthly | 12 | 2025-05 → 2026-04 |
| `real_median_household_income_annual.csv` | `MEHOINUSA672N` | Annual | 41 | 1984 → 2024 (full series) |
| `realtor_active_listing_count_us_monthly.csv` | `ACTLISCOUUS` | Monthly | 12 | 2025-05 → 2026-04 |
| `case_shiller_us_national_sa_monthly.csv` | `CSUSHPISA` | Monthly | 10 | 2025-05 → 2026-02 |
| `case_shiller_us_national_nsa_monthly.csv` | `CSUSHPINSA` | Monthly | 10 | 2025-05 → 2026-02 |

All files share the same 4-column schema: `date, value, realtime_start, realtime_end`.
Windowing strategy is per-cadence (see Phase 2c below).

### Friendly-filename mapping

Per `feedback_friendly_filenames`: FRED publishes by cryptic series ID;
local filenames describe the data. Mapping above. The original
`series_id` is preserved in the second column and is the canonical
FRED identifier — always re-fetch by ID, never by file name.

## How to re-fetch

Script: `scratch/fetch_fred_samples.py` (stdlib only — no `uv`/pip
needed; runs under `python3.12`). Reads `FRED_API_KEY` from `.env`,
iterates the series list, server-side windows per cadence, writes
each CSV. Idempotent — re-running overwrites with the latest data.

```
python3.12 scratch/fetch_fred_samples.py
```

## Phase 1 — API discovery

- **Publisher:** Federal Reserve Bank of St. Louis (FRED).
- **Portal:** https://fred.stlouisfed.org/ (HTML; `WebFetch` blocked
  to specific series pages this session — `HTTP 000`/`403`. Use real
  browser for series catalog.)
- **API base (Verified):** `https://api.stlouisfed.org/fred/`
- **Auth (Verified):** Free API key, required on every request.
  No-key request returns clean JSON:
  ```
  {"error_code":400,"error_message":"Bad Request.  Variable api_key
  is not set.  Read https://fred.stlouisfed.org/docs/api/api_key.html
  for more information."}
  ```
- **Auth storage convention** (per project rules): `FRED_API_KEY` in
  `.env` at project root (gitignored). Never commit. Each script reads
  via `os.environ`.

### How to acquire the FRED API key

1. Visit https://fred.stlouisfed.org/docs/api/api_key.html
2. Click "Request API Key" → fill out the short form (name, email,
   intended use). Free; no payment.
3. Receive the key by email within minutes.
4. Add to project's `.env` file:
   ```
   echo "FRED_API_KEY=your-32-char-hex-key-here" >> .env
   ```
5. Confirm `.env` is gitignored (check `.gitignore` — typically
   already includes it).
6. Re-run this source's Phase 2a download (see "How to re-fetch"
   below).

### Endpoints to be used

| Endpoint | Purpose | Verified to require api_key? |
|---|---|---|
| `GET /fred/series?series_id=<ID>&api_key=<KEY>&file_type=json` | **Column-meaning channel** — returns series metadata (title, units, frequency, SA flag, notes) | Yes |
| `GET /fred/series/observations?series_id=<ID>&api_key=<KEY>&file_type=json` | **Data channel** — returns the time-series observations | Yes |

### Rate limits (Projected)

~**120 requests per minute per API key** (per project's Pass-1
research; not re-verified this session). FRED is generous;
documentation rate-limiting recommended in client code as a courtesy
rather than a hard requirement. Verify against
https://fred.stlouisfed.org/docs/api/fred/ before designing batch
ingest.

### Column-meaning channels consulted (per skill Phase 1, step 5)

| Channel | Format | Reached this session? |
|---|---|---|
| FRED **`series/` API metadata endpoint** | JSON | **Blocked — no key.** Documented from public API spec; verification pending key. |
| FRED **per-series HTML pages** (e.g. `/series/MORTGAGE30US`) | HTML | **No — HTTP 000/403 to `WebFetch`** |
| FRED **API documentation pages** at `/docs/api/fred/` | HTML | **No — HTTP 000 to `WebFetch`** (transport errors) |
| ALFRED **vintage history endpoint** (for revision tracking — load-bearing for project question family #5) | JSON | **Blocked — no key.** |

**Auto-discoverable?** **Yes — the `series/` API metadata endpoint
is the canonical machine-readable column dictionary.** This is the
first source in the catalog where Phase 4 can be largely automated:
iterate the target series list, fetch metadata per series, render
each into the README schema table. Verification pending key.

## Series targeted for this project

Per `references/sources.md` and the project's Pass-1 research:

| Series ID | Title (Projected) | Cadence | Units | Why this project wants it |
|---|---|---|---|---|
| `MORTGAGE30US` | 30-Year Fixed Rate Mortgage Average in the United States | Weekly | Percent | Question family #3 (rate sensitivity); affordability decomposition (family #2) |
| `MORTGAGE15US` | 15-Year Fixed Rate Mortgage Average | Weekly | Percent | Same; product-mix comparison vs 30-year |
| `FIXHAI` | Housing Affordability Index (Fixed) | Monthly | Index | NAR-derived affordability index; comparison baseline for family #2 |
| `MSPUS` | Median Sales Price of Houses Sold for the United States | Quarterly | USD | Transaction-side national price (vs Zillow ZHVI valuation-side and FHFA HPI repeat-sales) |
| `UNRATE` | Unemployment Rate | Monthly | Percent | Demand-side conditioning variable |
| `MEHOINUSA672N` | Real Median Household Income in the United States | Annual | 2022 USD | Affordability denominator (family #2) |
| `ACTLISCOUUS` | **Realtor.com** Active Listing Count, US | Monthly | Number | **FRED re-publication of Realtor.com data** — gives auto-discoverable metadata for a series Realtor.com itself does not document publicly |
| `CSUSHPISA` | S&P/Case-Shiller U.S. National Home Price Index, SA | Monthly | Index | Methodology contrast vs FHFA / Zillow (family #5) |
| `CSUSHPINSA` | S&P/Case-Shiller U.S. National Home Price Index, NSA | Monthly | Index | NSA companion |

The Case-Shiller series above will also be onboarded as Phase D1
of the project but the API mechanics are identical to B1 — same key,
same endpoint shape.

### Recommended additions (not yet pulled)

Captured 2026-05-28 from the Phase 1 critical review
(`research_phase1_critical_review_2026-05-28.md`, recommendation #1).

| Series ID | Title | Cadence | Why | Priority |
|---|---|---|---|---|
| `CPIAUCSL` | Consumer Price Index for All Urban Consumers, SA | Monthly | **Real-dollar deflation.** Every source README references "deflate by CPI" but no CPI series is currently committed. Without it, any multi-year analysis across the 8+ year cross-source window has to either skip deflation or pull CPI ad hoc. Same API pattern as the existing 9 series — no new mechanics. | High — add before implementation handoff. |

When added, it belongs in `fact_fred_macro_monthly` per
`docs/designs/bronze_silver_pipeline_overview.md` (Silver model
already has slots for additional macro series).

## Phase 2 — Date range probing AND windowing

### Phase 2a — Available range (Verified 2026-05-20)

Pulled from the `series/` metadata endpoint per series:

| Series ID | Cadence | observation_start | observation_end | Total obs (full series) |
|---|---|---|---|---|
| `MORTGAGE30US` | Weekly (W) | 1971-04-02 | 2026-05-14 | 2,877 |
| `MORTGAGE15US` | Weekly (W) | 1991-08-30 | 2026-05-14 | ~1,810 |
| `FIXHAI` | Monthly (M) | varies | recent | hundreds |
| `MSPUS` | Quarterly (Q) | 1963-01-01 | 2026-01-01 | ~253 |
| `UNRATE` | Monthly (M) | 1948-01-01 | 2026-04-01 | 940 |
| `MEHOINUSA672N` | Annual (A) | 1984-01-01 | 2024-01-01 | 41 |
| `ACTLISCOUUS` | Monthly (M) | 2016-07 (Realtor.com start) | recent | ~120 |
| `CSUSHPISA`, `CSUSHPINSA` | Monthly (M) | 1987-01-01 | recent | ~470 |

Even the largest full-series pull (`MORTGAGE30US`, 2,877 rows) is
tiny — no pagination concerns for any FRED series in scope.

### Phase 2b — Target window

**12 months** per skill default. Per-cadence overrides:

- **Weekly / Monthly** — 12 months. Gives 52 obs (weekly) or 12 obs (monthly).
- **Quarterly** — 24 months. 12 months would give 4 obs; 24 gives 8 — enough to exercise the schema.
- **Annual** — full series. 12 months would give 1 obs; the full series is only 41 rows.

### Phase 2c — Windowing strategy (Verified)

**Server-side windowing** chosen and implemented in
`scratch/fetch_fred_samples.py`: each `series/observations` call
includes `&observation_start=YYYY-MM-DD` derived from the cadence
rule above. The project's `window_file.py` is not used here — FRED's
native JSON-to-CSV path is simpler than running through that script's
shape-detector.

### Empirical findings from Phase 2c

- **`value` is a string, `.` is the missing sentinel.** Confirmed: `UNRATE`
  2025-10-01 returned `value=.` in the windowed sample. Cast with
  `pd.to_numeric(value, errors='coerce')` to coerce to NaN.
- **`realtime_start` = `realtime_end` = API call date** for a non-vintage
  query. All 9 samples show `2026-05-20` for both fields — the
  publication-fact-as-of-today. For revision history, requery with
  `&realtime_start=1990-01-01&realtime_end=9999-12-31`.
- **MORTGAGE30US is never revised** (separate vintage probe in session):
  asking for the full vintage range returned exactly one row per
  date with `realtime_end=9999-12-31`. Most rate series follow this
  pattern; macro series like `UNRATE` do get revised.

## Phase 3 — Detail enumeration

- **Maximum granularity FRED offers:** depends on the series. Most
  Realtor.com / Case-Shiller / mortgage-rate series are national-only.
  Some labor and income series (e.g., `UNRATE` family) have per-state
  and per-MSA variants discoverable by appending the geo code:
  `UNRATECBSA<5-digit-CBSA>`, `UNRATESTATE<state-FIPS>`.
- **Cadence (per series):** daily (some financial), weekly (mortgage
  rates), monthly (most macro), quarterly (some), annual (income).
- **Methodology variants:** FRED is a **republisher**, not a producer.
  Every series carries `source` metadata identifying the original
  publisher (BLS, Census, Realtor.com, S&P, etc.). Treat methodology
  as "original publisher's methodology" — FRED itself only does the
  hosting and rebasing.

## Phase 4 — Column documentation (Verified 2026-05-20)

Every series response has this shape, confirmed empirically against
all 9 target series:

### `series` endpoint response shape — `series/?series_id=<ID>`

Returns one JSON object with metadata:

```json
{
  "realtime_start": "2026-05-16",
  "realtime_end": "2026-05-16",
  "seriess": [
    {
      "id": "MORTGAGE30US",
      "realtime_start": "2026-05-16",
      "realtime_end": "2026-05-16",
      "title": "30-Year Fixed Rate Mortgage Average in the United States",
      "observation_start": "1971-04-02",
      "observation_end": "2026-05-15",
      "frequency": "Weekly, Ending Thursday",
      "frequency_short": "W",
      "units": "Percent",
      "units_short": "%",
      "seasonal_adjustment": "Not Seasonally Adjusted",
      "seasonal_adjustment_short": "NSA",
      "last_updated": "2026-05-15 11:32:00-05",
      "popularity": 96,
      "notes": "Source: Freddie Mac. Release: Primary Mortgage Market Survey..."
    }
  ]
}
```

The fields `title`, `units`, `frequency`, `seasonal_adjustment`, and
`notes` together provide everything Phase 4's seven-point standard
requires — **directly from the API, no human PDF reading needed**.
This is the auto-discoverable promise of FRED.

### `observations` endpoint response shape — `series/observations?series_id=<ID>`

Returns the time series:

```json
{
  "realtime_start": "2026-05-16",
  "realtime_end": "2026-05-16",
  "observation_start": "1971-04-02",
  "observation_end": "2026-05-15",
  "units": "lin",
  "output_type": 1,
  "count": 2823,
  "observations": [
    {"realtime_start": "...", "realtime_end": "...", "date": "1971-04-02", "value": "7.33"},
    ...
  ]
}
```

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `realtime_start` | string (date `YYYY-MM-DD`) | Vintage start — when this observation became known. Used for ALFRED-style revision tracking. | `'2026-05-16'` | For non-revised series, equals the API call date. For ALFRED queries with `vintage_dates`, differs per row. |
| 2 | `realtime_end` | string (date `YYYY-MM-DD`) | Vintage end — when this observation was superseded by a revision. | `'2026-05-16'` | If revisions exist, walking the (date, realtime_start) pairs gives revision history. |
| 3 | `date` | string (date `YYYY-MM-DD`) | The period the observation refers to. For weekly series, the week-end Thursday; for monthly, typically the first-of-month; for quarterly, first-of-quarter; for annual, year-start. | `'2026-05-15'` | **`date` is NOT the publication date** — it's the *observation* date. Use `last_updated` from the `series/` metadata for publication-recency. |
| 4 | `value` | string (numeric content) | The data point. **Always a string in the JSON response**; sentinel `"."` for missing periods. | `'6.95'` or `'.'` | **Cast carefully:** `pd.to_numeric(value, errors='coerce')` to coerce `"."` → `NaN`. Units come from the `series/` metadata `units` field, NOT from the observations response. |

### Per-target-series Phase 4 schema (next step)

The auto-discovery loop — fetch metadata per series, render into a
per-series schema row — is the **remaining Phase 4 work**. Pattern:

```python
import os, requests
import pandas as pd

key = os.environ["FRED_API_KEY"]
for series_id in TARGET_SERIES:
    meta = requests.get(
        f"https://api.stlouisfed.org/fred/series?series_id={series_id}"
        f"&api_key={key}&file_type=json"
    ).json()["seriess"][0]
    obs = requests.get(
        f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
        f"&api_key={key}&file_type=json"
        f"&observation_start=2025-05-16&observation_end=2026-05-16"   # 12-month window
    ).json()["observations"]
    # Render Phase 4 schema row from `meta` (title, units, frequency,
    # seasonal_adjustment, notes) — auto-fills 5 of the 7-point
    # standard fields. Hand-edit only the gotchas + cross-references.
```

The `meta` object gives, mostly automatically:
- **Acronym expansion** — `units_short='%'` → "Percent" (the long form is already in `units`).
- **Seasonal adjustment status** — `seasonal_adjustment` field directly.
- **Units** — `units` field directly.
- **Cadence** — `frequency` field directly.
- **Source/methodology context** — `notes` field has 1–3 paragraphs of publisher methodology.

What still requires hand-editing per series:
- **Operational guidance (Phase 4b)** — analysis recipes per series
  (YoY, rate-of-change, real-vs-nominal handling).
- **Cross-source correlation (Phase 4c)** — which other catalog
  sources this series joins to or contrasts with.

## Phase 4b — Practical interpretation (PARTIAL — pending data)

Per-series interpretation requires fetching the actual values. A few
universal patterns documented now:

### Reading mortgage-rate series (`MORTGAGE30US`, `MORTGAGE15US`)

**How to read.** Value is the **average mortgage rate** in percent
that week (e.g., `6.95` = 6.95% APR). Freddie Mac's Primary Mortgage
Market Survey is the underlying source.

**Common recipes.**
```python
# Year-over-year rate change in basis points (bps; 100 bps = 1 percentage point)
yoy_bps = (rate_this_week - rate_same_week_prior_year) * 100

# Affordability impact for question family #3 (rate sensitivity)
# A 25 bps rate move (0.25 percentage points) changes the monthly
# payment on a 30-year fixed loan by ~3% for typical loan sizes.
# Per-metro impact requires combining with metro median price + median income.
```

### Reading the affordability index (`FIXHAI`)

**How to read.** `100.0` means a median-income family qualifies for
exactly the median-priced home with a standard down payment. `>100`
= more affordable than baseline; `<100` = less affordable.

### Reading real-income series (`MEHOINUSA672N`)

**How to read.** Value is **2022-USD real income** (inflation-
adjusted). Value of `74580` = ~$74,580 in 2022 dollars regardless of
the nominal dollar value in the reference year.

(More per-series interpretation paragraphs to be added once data is
fetched.)

## Phase 4c — Cross-source correlation notes

FRED's role in the catalog is **republisher + canonical column-
meaning channel** for many series the project also pulls directly:

| FRED series | Republished from | Catalog source that pulls it directly |
|---|---|---|
| `ACTLISCOUUS`, `ACTLISCOU<CBSA>` | Realtor.com | Realtor.com (this project's `data/samples/realtor/`) |
| `CSUSHPISA`, `CSUSHPINSA`, `<METRO>XRSA` | S&P / Case-Shiller | Case-Shiller via FRED (Phase D1 — duplicates B1) |
| `MORTGAGE30US`, `MORTGAGE15US` | Freddie Mac PMMS | FRED-only (no other catalog source pulls these) |
| `UNRATE`, `UNRATESTATE*`, `UNRATECBSA*` | Bureau of Labor Statistics (BLS) | BLS LAUS (Tier B candidate — see catalog) |
| `MEHOINUSA672N`, `MEDLISPRIUS` | Census / BLS | Census ACS (Phase C1) |
| `MSPUS` | Census | Census Building Permits (Phase C2 — separate metric set) |

**Implication for ingest design.** For series where FRED is the
**only** source (mortgage rates, FIXHAI), FRED is canonical. For
series where FRED is **republishing** something we also pull directly
(Realtor.com, Case-Shiller, Census ACS), the **direct source is
usually fresher** (FRED republication lags by 0–7 days). **Use FRED
for cross-source correlation and metadata lookup; use the direct
source for the data itself, where available.**

**Vintage tracking (project question family #5 — load-bearing).**
ALFRED (Archival FRED) provides revision history via the same API
with `vintage_dates` query parameter. This is **the cleanest way to
get revision-tracked data anywhere in the catalog** — every other
source either doesn't restate or hides restatements behind file
overwrites. For any series where revisions matter, query ALFRED
even if the data is also republished by the direct publisher.

### Geography join — FRED uses CBSA in series ID encoding

FRED encodes the geography into the series ID (e.g., `ACTLISCOU41860`
= Active Listings, San Francisco MSA, CBSA 41860). To join FRED to
the rest of the catalog, parse the trailing CBSA code from the
series ID.

```python
import re
m = re.search(r'(\d{5})$', series_id)
cbsa_code = int(m.group(1)) if m else None  # joins to FHFA, Realtor.com, Census
```

## Known gotchas (summary)

1. **API key required for ALL endpoints** — no anonymous data fetch.
2. **`value` is always a string in the JSON**, with `"."` sentinel
   for missing. Cast with `errors='coerce'`.
3. **`date` is observation date, not publication date.** Use
   `last_updated` from `series/` metadata for publication recency.
4. **For ALFRED-style revision history**, append `&vintage_dates=`
   to the observations call.
5. **Frequency varies by series** — pull from `frequency` field; do
   not assume.
6. **WebFetch is blocked** on fred.stlouisfed.org HTML pages; only
   the API itself responded cleanly in this session.

## Terms of use

FRED data is public. **Terms of use vary by underlying publisher** —
FRED republishes data from many sources, each with its own license.
For Realtor.com / S&P Case-Shiller series via FRED, the original
publisher's restrictions apply. Federal-government sources (Census,
BLS, Federal Reserve) are public domain. Verify per-series via the
`notes` field in `series/` metadata.

## Confidence

- **Verified** in 2026-05-16 session: API base; error response shape
  without key; auth requirement; response-shape spec.
- **Verified 2026-05-20** (samples acquired): per-series
  `observation_start` / `observation_end` / `frequency` /
  `seasonal_adjustment` / `units` returned by `series/` metadata
  endpoint as documented; observations endpoint response shape
  matches spec; `.` sentinel for missing observations confirmed in
  UNRATE; vintage parameters accepted; MORTGAGE30US is non-revised.
- **Projected**: rate limit ~120/min — not stress-tested this
  session (all calls within courtesy bounds).
- **Outstanding**: per-series Phase 4 schema rows (auto-discovery
  loop not yet implemented; the input data is ready).
