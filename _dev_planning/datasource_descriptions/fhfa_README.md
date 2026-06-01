# FHFA House Price Index — sample data

Sample files from the [FHFA House Price Index datasets page](https://www.fhfa.gov/data/hpi/datasets).
Used in Phase 1 (dataset evaluation) of this project.

Generated **2026-05-16** via the `re-data-acquisition` skill workflow
(clean-slate run, post-4b/4c adoption). Prior generations preserved
at `data/samples/_archive/2026-05-16/fhfa/`.

**Raw files are gitignored.** This README is the reproduction recipe,
the per-column data dictionary, and the operational interpretation
guide.

## Sample window

**The files in this directory are windowed to the last 12 months
equivalent** (last 12 monthly rows + last 4 quarterly rows per
geography). Publisher ships ~50 years of history. Re-download +
re-window with `--months <N>` for wider history.

## Phase 1 — API discovery

- **Publisher portal:** https://www.fhfa.gov/data/hpi/datasets
  (Reachable via `WebFetch` and `curl`; no anti-bot blocking.)
- **Direct bulk file URLs (Verified HTTP 200):**
  - `https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv`
  - `https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_po_metro.xlsx`
  - `https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.xlsx`
- **Auth:** None. Federal-agency public-domain data.

### Column-meaning channels consulted (per skill Phase 1, step 5)

| Channel | Format | Reached this session? |
|---|---|---|
| FHFA HPI Datasets page (HTML) | HTML | Yes — references the dictionary file but does not link to a direct URL |
| HPI_dictionary.xlsx (canonical data dictionary) | XLSX | **No** — URL guesses 404'd. Browser lookup follow-up. |
| FHFA HPI Technical Documentation PDF | PDF | **No** — known URLs 404'd this session |
| XLSX banner row (rows 0–1 of the PO and AT XLSX files) | in-file metadata | **Yes** — read programmatically |
| Pass-1 research file | local markdown | Yes |

**Auto-discoverable?** **Partial.** XLSX banner is machine-readable;
the canonical dictionary is referenced by the portal but the URL
isn't discoverable from scraping — needs a browser session.

### XLSX banner content (verified this session)

| File | Banner row 0 | Banner row 1 (reference period) |
|---|---|---|
| PO XLSX | `Purchase-Only FHFA HPI® for Metropolitan Areas` | `1991Q1=100, Seasonally and Not Seasonally Adjusted` |
| AT XLSX | `All-Transactions FHFA HPI® for Metropolitan Areas` | `1995Q1=100, Not Seasonally Adjusted (NSA)` |

These reference quarters are load-bearing — they are NOT carried as
a column in the master CSV, so cross-flavor comparison requires
looking them up here.

## What's here

| Local file | What the data is | Upstream filename |
|---|---|---|
| `hpi_master_all_geographies.csv` | **Master HPI** — long format. Combines monthly + quarterly, all geographies, all three methodology variants. | `hpi_master.csv` |
| `hpi_purchase_only_metro_quarterly.xlsx` | Quarterly Purchase-Only Index, MSA grain. Clean XLSX (header at row 0). **Reference: 1991-Q1 = 100.** | `hpi_po_metro.xlsx` |
| `hpi_all_transactions_metro_quarterly.xlsx` | Quarterly All-Transactions Index, MSA grain. Report-shaped XLSX with banner on rows 0–1. **Reference: 1995-Q1 = 100.** | `hpi_at_metro.xlsx` |

## How to re-fetch (full history)

```bash
mkdir -p data/samples/fhfa
cd data/samples/fhfa
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

curl -sSL -A "$UA" -o hpi_master_all_geographies.csv \
  https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv
curl -sSL -A "$UA" -o hpi_purchase_only_metro_quarterly.xlsx \
  https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_po_metro.xlsx
curl -sSL -A "$UA" -o hpi_all_transactions_metro_quarterly.xlsx \
  https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.xlsx
```

Window. **AT XLSX needs `--header-row 2`** (banner rows 0–1):

```bash
SKILL=.claude/skills/re-data-acquisition/scripts/window_file.py
uv run --python 3.12 $SKILL data/samples/fhfa/hpi_master_all_geographies.csv --months 12 --in-place
uv run --python 3.12 $SKILL data/samples/fhfa/hpi_purchase_only_metro_quarterly.xlsx --months 12 --in-place
uv run --python 3.12 $SKILL data/samples/fhfa/hpi_all_transactions_metro_quarterly.xlsx --months 12 --in-place --header-row 2
```

## Phase 2 — Date range probing AND windowing

### Phase 2a — Available range

| File | Rows | Available range | Periods |
|---|---|---|---|
| Master CSV | 133,226 | 1975-Q1 / 1991-01 → 2025-Q4 / 2026-02 | 486 mixed |
| PO XLSX | 14,000 | 1991-Q1 → 2025-Q4 | 140 |
| AT XLSX | 83,640 (after `--header-row 2`) | 1975-Q1 → 2025-Q4 | n/a (probe can't infer shape on banner XLSX) |

### Phase 2c — Windowed range

| File | Rows kept | Notes |
|---|---|---|
| Master CSV | 3,352 | window_file.py auto-detected `frequency`; per-frequency kept last 12 months (monthly) and last 4 quarters (quarterly). |
| PO XLSX | 400 | 100 MSAs × 4 quarters. |
| AT XLSX | 1,640 | 410 MSAs × 4 quarters. |

## Phase 3 — Detail enumeration

- **Maximum granularity:** USA, 9 Census Divisions, 50 States + DC,
  400+ MSAs, Puerto Rico. **No county or sub-MSA.**
- **Methodology variants** (`hpi_flavor`): Purchase-Only,
  All-Transactions, Expanded-Data.
- **Housing-stock subsets** (`hpi_type`): `traditional`, `non-metro`,
  `distress-free`, `developmental`, `manufactured`.
- **Cadence:** Monthly **only** at USA + Census Division grain.
  Quarterly for everything sub-division.
- **Rebasing differs per series.** Reference period NOT in the
  master CSV.

## Phase 4 — Column documentation (schema table — ETL/ingestion layer)

### `hpi_master_all_geographies.csv` — 10 columns

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `hpi_type` | string (enum) | **Which housing-stock subset this row's index covers.** Five values: `traditional` — broad market, ~94% of full-file rows; `non-metro` — outside any Metropolitan Statistical Area (MSA); `distress-free` — excludes foreclosure and short-sale transactions; `developmental` — experimental annual series; `manufactured` — manufactured-housing only. | `traditional` | Filter to `traditional` unless the question targets a subset. |
| 2 | `hpi_flavor` | string (enum) | **Which FHFA repeat-sales methodology variant produced this index.** Three values: `purchase-only` (PO) — only GSE-financed sale transactions, cleanest signal, from 1991; `all-transactions` (AT) — PO sales + appraisals from GSE refinancings, larger pool, longer history back to 1975, but appraisal noise; `expanded-data` (ED) — GSE sales + FHA-insured + sub-conforming sales captured from county-recorder data, broadest coverage. | `purchase-only` | Picking which variant is itself a methodology decision. Three variants disagree most when GSE conforming-loan limits change. |
| 3 | `frequency` | string (enum) | **How often the index is published for this geography.** Combined with `period`, identifies the time point. Two values: `monthly` (`period` ∈ [1..12]); `quarterly` (`period` ∈ [1..4]). | `monthly` | **Monthly is ONLY at USA + Census Division grain.** No monthly State or MSA rows. **Always carry `frequency` with `period`** — `period=4` is April for monthly rows and Q4 for quarterly. |
| 4 | `level` | string (enum) | **The kind of geography this row represents.** Determines format of `place_id` and `place_name`. Four values: `USA or Census Division`; `State`; `MSA` (Metropolitan Statistical Area); `Puerto Rico`. | `USA or Census Division` | Dispatch on this when handling `place_id` — ID format varies. |
| 5 | `place_name` | string | **Human-readable display name** of the geography. For MSAs, the Office of Management and Budget (OMB) metro definition string. | `'East North Central Division'`, `'New York-Jersey City-White Plains, NY-NJ (MSAD)'` | **Display only — never join on.** Naming differs across publishers. |
| 6 | `place_id` | string | **Canonical identifier** for the geography. **Format depends on `level`:** MSAs use 5-digit Census Core-Based Statistical Area (CBSA) codes (e.g., `10180` = Abilene, TX); States use 2-letter postal codes (`NY`); Census Divisions use `DV_*` prefix (`DV_ENC`); national row uses `US`; Puerto Rico uses `PR`. | `DV_ENC`, `10580`, `NY`, `PR` | CBSA codes match Census/BLS/FFIEC/HUD identifiers. **Does NOT match Zillow's internal `RegionID`** — manual crosswalk required. |
| 7 | `yr` | int64 | **Calendar year.** | `2025` | Full-file range 1975–2026 (varies by `hpi_flavor`). Windowed sample 2025–2026. |
| 8 | `period` | int64 | **Period number within the calendar year.** For `monthly` rows, 1=January through 12=December. For `quarterly` rows, 1=Q1 (Jan–Mar) through 4=Q4 (Oct–Dec). | `3` | **Always carry alongside `frequency`.** `period=4` means April or Q4 depending on row's frequency. |
| 9 | `index_nsa` | float64 | **Not-Seasonally-Adjusted (NSA) index value.** Unitless — a ratio × 100 expressing the typical home value relative to the series' reference quarter set to 100.0. | `366.38` | **Reference quarter is NOT in this file.** Varies per (`hpi_flavor`, `level`). 1991-Q1=100 for PO MSA; 1995-Q1=100 for AT MSA. |
| 10 | `index_sa` | float64 | **Seasonally-Adjusted (SA) index value.** Same unit as NSA, with FHFA's seasonal-pattern factor removed. | `364.35` | **100% null for `hpi_flavor='all-transactions'` + `frequency='quarterly'`** — FHFA doesn't publish an SA variant. ~62% null overall in windowed sample. |

### `hpi_purchase_only_metro_quarterly.xlsx` — 6 columns

Clean XLSX (sheet 0, header at row 0). **Reference: 1991-Q1 = 100.**

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `cbsa` | int64 | **Census Core-Based Statistical Area (CBSA) code** — 5-digit. Canonical US-metro identifier used by Census/BLS/FFIEC/HUD. | `10580` (Albany-Schenectady-Troy, NY) | Same as `place_id` in the master CSV when `level='MSA'`. Joins to all Census-family sources. **Does NOT join to Zillow.** |
| 2 | `metro_name` | string | **OMB metro definition string.** | `'Albany-Schenectady-Troy, NY'` | **Display only — never join on.** |
| 3 | `yr` | int64 | **Calendar year.** | `2025` | Full-file range 1991–2025. |
| 4 | `qtr` | int64 | **Calendar quarter (1–4).** Q1=Jan–Mar, Q2=Apr–Jun, Q3=Jul–Sep, Q4=Oct–Dec. | `1` | Quarterly-only — no `frequency` column needed. |
| 5 | `index_nsa` | float64 | **NSA index.** Unitless × 100. **Base: 1991-Q1 = 100** (per banner). | `316.42` | Use for same-quarter-vs-same-quarter YoY. |
| 6 | `index_sa` | float64 | **SA index.** Same base. | `315.10` | ~0.4% null in early periods in the full file. |

### `hpi_all_transactions_metro_quarterly.xlsx` — 6 columns

**Read via `--header-row 2`** — banner occupies rows 0–1
(`All-Transactions FHFA HPI® for Metropolitan Areas` / `1995Q1=100, Not Seasonally Adjusted (NSA)`). **Reference: 1995-Q1 = 100. No SA variant.**

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `Area Name` | string | **OMB metro definition string.** | `'Abilene, TX'` | Different name from PO file's `metro_name` — load-bearing when scripting both. **Display only.** |
| 2 | `CBSACode` | int64 | **Census CBSA code.** | `10180` | Same role as PO's `cbsa`. **Different capitalization** — normalize before joining the two files. |
| 3 | `Year` | int64 | **Calendar year.** | `2025` | Full-file 1975–2025. |
| 4 | `Quarter` | int64 | **Calendar quarter (1–4).** | `1` | |
| 5 | `Index (NSA)` | float OR string `'-'` | **NSA index.** Unitless × 100. **Base: 1995-Q1 = 100.** | `108.09` for real; `'-'` for missing | **Mixed-type column:** numeric where present, sentinel `'-'` where missing. Coerce with `errors='coerce'` or replace `'-'` → `NaN` before reading. **No SA variant.** |
| 6 | `Standard Error` | string (numeric content) | **Statistical Standard Error (SE)** of the NSA index estimate, in index points. ~95% CI = `index ± 1.96 × SE`. | `'( 2.56)'` for real; `'-'` for missing | **Parenthesized + leading space.** Strip → cast → float. A naive `pd.to_numeric` fails on every row. PO file does NOT have this column. |

## Phase 4b — Practical interpretation (BI / analyst layer)

This section is **additive** to the schema table above. The schema
table tells the ingestion code how to handle the bytes; this section
tells the analyst what the values *mean* in practice.

### `index_nsa` and `index_sa` — "rebased index of home prices"

**How to read it.** Think of `100.0` as **"home prices in the
reference quarter."** A value of `300.0` means home prices are **3×
their reference-quarter level** — i.e., 200% cumulative appreciation
since the reference quarter. A value of `108.09` means an 8.09%
gain since reference.

The reference quarter is set by `(hpi_flavor, level)`:
- Purchase-Only MSA: **1991-Q1 = 100.**
  Index `316.42` at 2025-Q1 → typical home is 3.16× its 1991 value
  (216% cumulative gain over 34 years).
- All-Transactions MSA: **1995-Q1 = 100.**
  Index `293.16` at 2025-Q1 → typical home is 2.93× its 1995 value
  (193% cumulative gain over 30 years).
- Other (flavor, level) pairs: see XLSX banners.



  What "rebased" means

  An FHFA HPI value isn't a price. It's a ratio to a reference quarter, multiplied by 100. The reference quarter is defined to equal 100. Every other value says "prices were X% of
  the reference quarter."

  index = (price level this quarter / price level in reference quarter) × 100

  So 293 doesn't mean $293, or $293k, or anything in dollars. It means prices are 2.93× what they were in the reference quarter (1995-Q1 here).

  Why that's "hard to read in isolation"

  "In isolation" means: looking at one number, for one metro, at one point in time, with nothing to compare it against. Three concrete problems:

  1. The number has no inherent unit. If a colleague says "Austin's HPI is 293," you've learned nothing concrete. Not the price of a house. Not how fast prices are rising. Just
  "2.93× a baseline quarter you have to go look up." The number only becomes meaningful relative to another index value — either the same metro at a different time, or a known
  reference. A single value alone is inert.

  2. You can't compare two metros' levels directly — even though it looks like you can. This is the trap. Austin = 293 and Phoenix = 310 does not mean Phoenix homes are more
  expensive than Austin's. Each metro is rebased to its own 1995-Q1 price level. Phoenix's 310 means "Phoenix prices are 3.10× Phoenix-in-1995"; Austin's 293 means "2.93×
  Austin-in-1995." Those are two different baselines in dollars. The index measures growth since the base quarter, not price level — so cross-metro level comparisons are
  meaningless. (Cross-metro growth-rate comparisons are valid — that's what the index is for.)

  3. The base quarter is arbitrary and invisible in the value. 100 corresponds to 1995-Q1 only because someone chose that anchor. Rebase to 2000-Q1 and every number changes, while
  the actual housing market is identical. So the raw level carries an arbitrary convention baked in that a reader can't see from the number itself.

  What IS readable without context

  Differences and ratios between index values, within one metro:

  - Ratio of two quarters = total growth. 293 / 100 = 2.93 → prices up 193% since base. 293 / 265 (a year earlier) = 1.106 → up 10.6% year-over-year. That number — 10.6% — is
  meaningful in isolation. Anyone understands "Austin home prices rose 10.6% last year." Nobody intuits "Austin's HPI is 293."



**Common analysis recipes.**

```
# Year-over-year price growth (%) — use NSA, same-quarter comparison
yoy_pct = 100 * (idx_nsa_this_q / idx_nsa_same_q_prior_year - 1)

# Cumulative growth since reference (%) — direct from value
cumulative_growth_since_base_pct = idx_nsa - 100

# Rebase to your own reference period (e.g., 2020-Q1 = 100)
rebased = 100 * (idx_nsa / idx_nsa_at_2020_q1)

# Quarter-over-quarter — use SA (NOT NSA) to remove seasonality
qoq_pct = 100 * (idx_sa_this_q / idx_sa_prior_q - 1)

# Confidence interval (AT XLSX only — uses Standard Error column)
upper_95 = idx_nsa + 1.96 * standard_error
lower_95 = idx_nsa - 1.96 * standard_error
```

**What this number is NOT.**
- **NOT a dollar value.** You cannot derive "the typical home price
  in Abilene in 2025-Q1" from `316.42` alone. You'd need the actual
  median dollar price at the reference quarter (1991-Q1 for PO) from
  a separate source (e.g., NAR EHS).
- **NOT comparable across `hpi_flavor` values directly.** PO and AT
  use different reference quarters AND different transaction pools.
  Cross-flavor comparison requires rebasing to a common reference
  period first.
- **NOT comparable across `level` values** at face value — different
  geographies start at different real price levels in their
  respective reference quarters.

**When to use NSA vs SA.**
- **NSA:** YoY comparisons (March vs prior March), cumulative-growth
  calculations, headline reporting. The "natural" series.
- **SA:** Consecutive-period analyses (Q2 vs Q1 of same year),
  momentum/acceleration detection, turning-point identification.
  Removes spring-buying-season distortion.

### `place_id` (master CSV) — "the tagged-union join key"

**How to read it.** The value's *format* tells you what kind of
geography you're looking at — but you must check `level` first to
know which format applies.

**Recipe — Python dispatch:**

```python
def join_key(row):
    if row['level'] == 'MSA':
        return ('cbsa', row['place_id'])           # '10180' → joins to Census, FHFA AT/PO, etc.
    elif row['level'] == 'State':
        return ('state_postal', row['place_id'])   # 'NY'
    elif row['level'] == 'Puerto Rico':
        return ('pr', 'PR')
    else:  # 'USA or Census Division'
        return ('division', row['place_id'])       # 'DV_ENC' or 'US'
```

**Recipe — SQL filter for MSA-only:**

```sql
SELECT * FROM fhfa_hpi WHERE level = 'MSA'
-- place_id is now a 5-digit CBSA code; joinable to other Census-family sources
```

### `period` + `frequency` — "the period bomb"

**The trap.** A query like `WHERE period = 4` matches BOTH April
(if `frequency='monthly'`) AND Q4 (if `frequency='quarterly'`).
Without `frequency` in the filter, you silently mix two
incompatible meanings.

**Recipe — every filter on `period` must carry `frequency`:**

```sql
-- Wrong (silently mixes April monthly with Q4 quarterly):
WHERE period = 4

-- Right:
WHERE frequency = 'monthly' AND period = 4    -- April only
-- or
WHERE frequency = 'quarterly' AND period = 4  -- Q4 only
```

**Recipe — synthesize a real date column on ingest:**

```python
def to_date(row):
    if row['frequency'] == 'monthly':
        return f"{row['yr']:04d}-{row['period']:02d}-01"  # YYYY-MM-01
    else:  # quarterly
        month = row['period'] * 3   # Q1→3, Q2→6, Q3→9, Q4→12
        return f"{row['yr']:04d}-{month:02d}-01"
```

This belongs in the silver layer; don't make every downstream query
re-derive it.

### Sentinel `'-'` and parenthesized SE (AT XLSX only)

**How to read it.** The AT XLSX represents missing as the literal
string `'-'` (not blank, not `NaN`). The Standard Error column wraps
its number in parentheses with a leading space: `'( 2.56)'`.

**Recipe — ingest cleanly:**

```python
import pandas as pd

# 1) Replace '-' sentinel with NaN; coerce Index (NSA) to float
df['Index (NSA)'] = pd.to_numeric(df['Index (NSA)'].replace('-', None), errors='coerce')

# 2) Standard Error: strip parens + whitespace, then numeric
df['Standard Error'] = (
    df['Standard Error'].astype(str)
       .str.replace(r'[()\s]', '', regex=True)
       .replace('-', None)
       .pipe(pd.to_numeric, errors='coerce')
)
```

These transforms belong in the **bronze → silver** boundary; bronze
keeps the publisher's strings, silver carries clean numerics.

## Phase 4c — Cross-source correlation notes

For analyses that combine FHFA with other sources in this project's
catalog.

### Geography join key — FHFA's `place_id`/`cbsa` is canonical

For MSAs, FHFA's `place_id` (master CSV) and `cbsa` / `CBSACode`
(XLSX files) are **5-digit Census CBSA codes** — the canonical US-
metro identifier shared by Census ACS, BLS LAUS, FFIEC HMDA, HUD CHAS,
HUD FMR, Census Building Permits.

| Source | Metro identifier | Joinable to FHFA `cbsa`? |
|---|---|---|
| FHFA | `place_id` (MSAs) / `cbsa` / `CBSACode` (XLSX) | (this source) |
| Census ACS | 5-digit CBSA | **Yes — direct equality** |
| BLS LAUS | 5-digit CBSA | **Yes — direct equality** |
| FFIEC / HMDA | 5-digit CBSA | **Yes — direct equality** |
| HUD CHAS / FMR | 5-digit CBSA | **Yes — direct equality** |
| Census Building Permits | 5-digit CBSA | **Yes — direct equality** |
| Realtor.com (Projected) | CBSA | **Yes** (Projected — verify) |
| Apartment List (Projected) | CBSA | **Yes** (Projected) |
| Redfin (Projected) | CBSA | **Yes** (Projected) |
| **Zillow** | `RegionID` (Zillow internal) | **No — crosswalk required** |

**The Zillow side is the only crosswalk needed.** Everything else
in the catalog already speaks CBSA. Build a `zillow_region_id ↔
cbsa_code` crosswalk in the silver geography dimension; every other
join is direct equality on CBSA.

### FHFA HPI ↔ Case-Shiller ↔ ZHVI — three "home price" signals

All three measure metro-level home prices but use different
methodologies and produce different numbers. Differences are
themselves analytical signal (project question family #5).

| Source | What it measures | Methodology | Units | Coverage |
|---|---|---|---|---|
| **FHFA HPI** (this) | Price changes from repeat sales of the same property | Repeat-sales, weighted by transaction count | **Rebased index** (100 = base period; varies per series) | 400+ MSAs |
| **Case-Shiller** | Same idea, but value-weighted | Repeat-sales, value-weighted (movements in expensive homes dominate) | **Rebased index** (100 = base period; series-specific) | 20 specific MSAs only |
| **Zillow ZHVI** | Estimated value of the typical mid-tier home | Proprietary AVM (ML model) | **Level USD** (not an index) | 895 metros |

**Why they disagree:**
- FHFA PO excludes jumbo loans (cap = GSE conforming limit) and
  cash sales → systematically understates appreciation at the high
  end. AT and ED partially address this.
- Case-Shiller value-weights → runs hotter than FHFA in markets
  with rapid high-end appreciation (Bay Area, Seattle).
- ZHVI is AVM-based → can react faster than repeat-sales methods
  (which need the same property to sell twice), but is model output
  not market truth.

**Cross-source rebase recipe:**

```python
# To put FHFA, Case-Shiller, and ZHVI on the same chart, rebase all
# three to a common reference period (e.g., 2020-Q1 / 2020-01).
fhfa_rebased = 100 * (fhfa_nsa / fhfa_nsa_at_2020_q1)
cs_rebased   = 100 * (cs_value / cs_value_at_2020_q1)
zhvi_rebased = 100 * (zhvi_value / zhvi_value_at_2020_q1)
# All three now: 100 = 2020-Q1, units aligned, plottable together.
```

### FHFA flavors disagree with each other

This is a within-FHFA correlation gotcha — not even cross-source.

| Comparison | Why they differ |
|---|---|
| **PO vs AT** for the same MSA + quarter | AT includes appraisals from refinancings (not just sales). In rising markets, appraisals lag transaction prices → AT understates appreciation vs PO. In falling markets, appraisers may stick to outdated comps → AT lags PO. |
| **PO vs ED** | ED adds FHA-insured + sub-conforming sales. ED has broader coverage of lower-income neighborhoods → can diverge from PO when those neighborhoods move differently than the GSE-financed market. |
| **Different reference quarters** | PO MSA: 1991-Q1=100. AT MSA: 1995-Q1=100. ED varies. Two raw index numbers can't be compared without rebasing. |

**For chart-side comparison:** rebase all flavors to the same
reference period first (use the recipe above).

### Period-grain alignment

| Source | Cadence available | Date semantics |
|---|---|---|
| FHFA master (monthly rows) | Monthly — **USA + Census Division only** | `yr` + `period` (1–12) + `frequency='monthly'` |
| FHFA master (quarterly rows) | Quarterly — everything else | `yr` + `period` (1–4) + `frequency='quarterly'` |
| FHFA PO XLSX | Quarterly only | `yr` + `qtr` (1–4) |
| FHFA AT XLSX | Quarterly only | `Year` + `Quarter` (1–4) |
| Zillow | Monthly | Month-end `YYYY-MM-DD` |
| Case-Shiller via FRED | Monthly | Month-end |
| Census ACS | Annual | Year |
| FRED Mortgage Rates | Weekly | Week-end Thursday |

**Joining FHFA quarterly to a monthly source** requires either:
- *Forward-filling FHFA quarterly to monthly* (each quarter's value
  applies to its 3 months) — appropriate for slow-moving series like
  HPI.
- *Aggregating the monthly source to quarterly* (e.g., quarter-mean
  of monthly mortgage rates) — appropriate when the monthly series
  is the more volatile one.

**FHFA monthly is restricted to USA + Census Division.** Any
cross-source design that wants FHFA monthly at MSA grain is
impossible — fall back to FHFA quarterly OR use a non-FHFA source
for the monthly metric.

### Coverage diffs to plan for

- FHFA covers Puerto Rico; Zillow does not.
- FHFA AT covers more MSAs (~410) than FHFA PO (~100) — the
  difference is GSE penetration; PO requires GSE-financed sales which
  some smaller metros have too few of.
- FHFA covers 400+ MSAs; Case-Shiller covers 20. The intersection
  is the 20 Case-Shiller metros.
- Inner-joining FHFA × Zillow × Case-Shiller drops to those 20 metros
  for any analysis that needs all three.

## Known gotchas (summary)

1. Monthly only at USA + Census Division grain.
2. `place_id` format varies by `level`.
3. `period` semantics differ by `frequency`.
4. `index_sa` 100% null for quarterly all-transactions.
5. PO XLSX clean; AT XLSX banner-shaped — pass `--header-row 2`.
6. Rebasing differs per series — base period not in master CSV.
7. CBSA matches Census family but NOT Zillow `RegionID`.
8. Windowed sample is recent-only.

## Terms of use

Federal-government public-domain data. Free for public use; attribution recommended.

## Confidence

- **Verified**: URL patterns + file sizes + schema confirmed via
  scripts; XLSX banner content read directly.
- **Projected**: precise weighting formulas, standard-error
  computation, exact rebasing rules for non-MSA series — canonical
  HPI_dictionary.xlsx and Technical Documentation PDF not reachable
  to `WebFetch` this session. Follow-up: locate dictionary URL in
  browser, update `references/sources.md`.
