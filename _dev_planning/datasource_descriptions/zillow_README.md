# Zillow Research — sample data

Sample CSVs from [Zillow Research](https://www.zillow.com/research/data/),
used in Phase 1 (dataset evaluation) of this project.

Generated **2026-05-16** via the `re-data-acquisition` skill workflow
(clean-slate run, post-4b/4c adoption). Prior generations preserved
at `data/samples/_archive/2026-05-16/zillow/`.

**Raw CSVs are gitignored.** This README is the reproduction recipe,
the per-column data dictionary, and the operational interpretation
guide.

## Sample window

**The files in this directory are windowed to the last 12 months
(2025-05-31 → 2026-04-30).** Publisher ships full history (ZHVI back
to 2000, ZORI back to 2015, inventory back to 2018) in one file;
Phase 2c windowing keeps only the last 12 months. Re-download +
re-window with `--months <N>` for wider history.

## Phase 1 — API discovery

- **Publisher portal:** https://www.zillow.com/research/data/
  Returns **HTTP 403** to `WebFetch` / `curl` without a realistic
  browser User-Agent. Use a real browser to discover new file URLs.
- **Bulk file CDN:** `https://files.zillowstatic.com/research/public_csvs/`
  (CDN is NOT blocked.)
- **Auth:** None. HTTP GET with browser User-Agent.

### Column-meaning channels consulted (per skill Phase 1, step 5)

| Channel | Format | Reached this session? |
|---|---|---|
| Zillow filename token decoder (project's own decoder) | filename-token grammar | Yes |
| Zillow methodology pages at zillow.com/research/*-methodology/ | HTML | **No** — HTTP 403 to `WebFetch` |
| Pass-1 research file (`research_housing_analytics_domain_2026-05-15.md`) | local markdown | Yes |

**Auto-discoverable?** **No.** Zillow's AVM is a proprietary ML model
not derivable from public material. Column meanings below assembled
from filename decoder + Pass-1 research + prior browser-read methodology.

## What's here

| Local file | What the data is | Geography | Cadence | Upstream filename |
|---|---|---|---|---|
| `zhvi_home_values_metro_monthly.csv` | Zillow Home Value Index (ZHVI) — typical home value in nominal US dollars. | Metro + US | Monthly | `Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` |
| `zori_asking_rents_metro_monthly.csv` | Zillow Observed Rent Index (ZORI) — typical asking rent in USD per month. | Metro + US | Monthly | `Metro_zori_uc_sfrcondomfr_sm_sa_month.csv` |
| `inventory_for_sale_metro_monthly.csv` | For-sale inventory — count of active for-sale listings. | Metro + US | Monthly | `Metro_invt_fs_uc_sfrcondo_sm_month.csv` |

All three are **wide format**: 5 identifier columns + 12 date-named
columns (`YYYY-MM-DD` = month-end).

### Decoding the upstream filenames

| Token | Meaning |
|---|---|
| `Metro` | Geography grain. Other Zillow files use `Country`, `State`, `County`, `City`, `Zip`, `Neighborhood`. |
| `zhvi` / `zori` / `invt_fs` | Series identifier. `invt_fs` = for-sale inventory. |
| `uc_sfrcondo` | Housing-type bundle: "used-cost" Single-Family Residential (SFR) + condo. `uc_sfrcondomfr` additionally includes multifamily (MFR). |
| `tier_0.33_0.67` | (ZHVI only) Use homes in the 33rd–67th percentile of the metro housing stock — the "mid tier." |
| `sm` | Smoothed (3-month moving-average style). |
| `sa` | Seasonally Adjusted (SA). |
| `month` | Cadence — monthly rows. |

## How to re-fetch (full history)

```bash
mkdir -p data/samples/zillow
cd data/samples/zillow

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

curl -sSL -A "$UA" -o zhvi_home_values_metro_monthly.csv \
  https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
curl -sSL -A "$UA" -o zori_asking_rents_metro_monthly.csv \
  https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_sa_month.csv
curl -sSL -A "$UA" -o inventory_for_sale_metro_monthly.csv \
  https://files.zillowstatic.com/research/public_csvs/invt_fs/Metro_invt_fs_uc_sfrcondo_sm_month.csv
```

Then window:

```bash
for f in data/samples/zillow/*.csv; do
  uv run --python 3.12 .claude/skills/re-data-acquisition/scripts/window_file.py \
    "$f" --months 12 --in-place
done
```

## Phase 2 — Date range probing AND windowing

### Phase 2a — Available range (probed before windowing)

| File | Min available | Max available | Periods |
|---|---|---|---|
| ZHVI | 2000-01-31 | 2026-04-30 | 316 |
| ZORI | 2015-01-31 | 2026-04-30 | 136 |
| Inventory | 2018-03-31 | 2026-04-30 | 98 |

Common available window across all three: **2018-03 → 2026-04**.

### Phase 2c — Windowed range (saved samples)

All three files: **2025-05-31 → 2026-04-30 (12 periods)**.

## Phase 3 — Detail enumeration

- **Maximum granularity Zillow Research offers:** national, state,
  metro, county, city, ZIP, neighborhood — via filename-token swap.
- **This sample targets the `Metro_` grain only.**
- **Methodology variants:** tier cuts (bottom / mid / top); housing-
  type bundles (`uc_sfrcondo` SFR+condo, `uc_sfrcondomfr` adds MFR);
  smoothed/raw; SA/Not-Seasonally-Adjusted (NSA).
- **Coverage by file:** Inventory (928 metros) ⊃ ZHVI (895) ⊃ ZORI (719).
- **What's NOT here:** no per-property records; no hedonic features.
  Per-bedroom-cut files exist separately for ZHVI.

## Phase 4 — Column documentation (schema table — ETL/ingestion layer)

### Shared identifier columns (columns 1–5, all three files)

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `RegionID` | int64 | Zillow's **internal numeric geography identifier**. Stable across all Zillow Research files: the same `RegionID` always refers to the same geography. **NOT a Census Core-Based Statistical Area (CBSA) code** — Zillow uses its own internal ID scheme. | `102001` (US national row) | **No published Zillow → CBSA crosswalk exists.** Cross-source joins require a manually-built name-match crosswalk. Always join *between Zillow files* on `RegionID`, never on `RegionName`. |
| 2 | `SizeRank` | int64 | Rank by metro population size. `0` is the national aggregate row; `1` is the largest metro (NYC), `2` is LA, etc. | `0` (national) | Filter `SizeRank > 0` to drop the national row when doing metro-only analysis. |
| 3 | `RegionName` | string | Human-readable display name. Format `'City, ST'` for metros; literal string `'United States'` for the national row. | `'United States'`, `'New York, NY'` | **Display only — never use as a join key.** Naming differs across publishers (Zillow `'New York, NY'`; FHFA `'New York-Jersey City-White Plains, NY-NJ (MSAD)'`). |
| 4 | `RegionType` | string (enum) | What kind of geography this row represents. In these `Metro_` files, **two values:** `'msa'` (Metropolitan Statistical Area) and `'country'` (national row). | `'msa'` | **Filter `RegionType='msa'`** for metro-only analysis. |
| 5 | `StateName` | string | Two-letter US state postal code (USPS abbreviation). | `'NY'` | **Null for the national row**; expected. For multi-state metros (NYC spans NY/NJ/PA/CT), Zillow uses the primary-state postal code only. |

### Date-value columns (columns 6–17, all three files)

Wide format — each column header is a month-end date in `YYYY-MM-DD`
format (`2025-05-31` through `2026-04-30`, 12 columns). **The value's
meaning differs per file:**

| File | Type | Units | What the value means | Sample | Gotchas |
|---|---|---|---|---|---|
| ZHVI | float64 | **Nominal US Dollars (not inflation-adjusted)** | **Zillow Home Value Index** — the typical (mid-tier, 33rd–67th pct by value) home value in the metro for that month-end. Produced by Zillow's **Automated Valuation Model (AVM)** — proprietary ML — not by aggregating sale prices. **Smoothed** (3-month moving-average style) and **Seasonally Adjusted (SA)**. **Not an index** in the rebased-to-100 sense — a level value in dollars. | `365262.67` (US national, 2025-05-31) → "the typical mid-tier US home was worth ~$365K" | AVM is a black box. Smoothing window can lag turning points 1–3 months. Nominal dollars — deflate by Consumer Price Index (CPI) for real values. Per-property attributes averaged out. |
| ZORI | float64 | **Nominal US Dollars per month (not inflation-adjusted)** | **Zillow Observed Rent Index** — typical *asking* rent across SFR + condo + multifamily. Smoothed + SA. **Asking ≠ contract rent.** | varies by metro | ZORI is a *leading* indicator vs. realized rent (BLS Owners' Equivalent Rent — OER); not interchangeable. ZORI covers 719 metros vs ZHVI's 895. ~12% recent-month cells null even in covered metros. |
| Inventory | float64 (integer-valued) | **Count of homes, unitless** | **For-sale inventory** — active for-sale listings observed in the metro that month, smoothed. SFR + condo. Stock-level snapshot-ish (what was listed *during* the month, not *newly added*). | varies by metro | Excludes pending/under-contract/off-market. Snapshot semantics approximate due to smoothing. Broadest-coverage Zillow file (928 metros). |

## Phase 4b — Practical interpretation (BI / analyst layer)

This section is **additive** to the schema table above. The schema
table is for the ingestion code; this section is for the analyst
writing a query against the gold layer who needs to know what the
number *means* in practice.

### ZHVI — "the typical home value, in dollars"

**How to read it.** `365262.67` literally means **$365,262.67**. It
is what Zillow's model thinks the *typical* mid-tier home in this
metro was worth at the end of that month. Not an index. Not
rebased. Not normalized. A dollar amount you could put on a chart
axis labeled "USD."

**Common analysis recipes.**

```
# Year-over-year price growth (%)
yoy_pct = 100 * (zhvi_this_month / zhvi_same_month_prior_year - 1)

# Real (inflation-adjusted) value at month M, using CPI series
real_zhvi = zhvi_m * (cpi_base / cpi_m)

# Affordability ratio — Price-to-Income
price_to_income = zhvi_m / median_household_income_for_metro

# Affordability ratio — Price-to-Rent
price_to_rent = zhvi_m / (zori_m * 12)   # annualize ZORI monthly
```

**What this number is NOT.**
- NOT a transaction price. No home actually sold for $365,262 on
  2025-05-31; this is a model's central estimate for "what a typical
  mid-tier home would sell for."
- NOT inflation-adjusted. Comparing ZHVI across decades without
  deflating by CPI overstates real appreciation.
- NOT comparable across publishers without rebasing — see Phase 4c.

**When to use which Zillow tier.** Mid-tier (this file) is the
default for "typical home." Bottom-tier (`tier_0.0_0.33`) and
top-tier (`tier_0.67_1.0`) are published separately and answer
"starter-home prices" vs "high-end prices."

### ZORI — "the typical asking rent, in dollars per month"

**How to read it.** A value of `3406.04` literally means **$3,406
per month** — the typical *asking* rent the metro's landlords were
posting that month. Across SFR + condo + multifamily.

**Common analysis recipes.**

```
# Year-over-year rent growth (%)
rent_yoy_pct = 100 * (zori_m / zori_same_month_prior_year - 1)

# Annualized rent (for affordability comparisons)
annual_rent = zori_m * 12

# Rent burden — what % of median income the typical rent consumes
rent_burden_pct = 100 * (zori_m * 12) / median_household_income
```

**What this number is NOT.**
- NOT contract rent. ZORI tracks what landlords *ask*; not what
  tenants actually *sign* a lease for. Asking is usually 1–5%
  above contract in normal markets, more in soft markets where
  landlords negotiate down.
- NOT comparable to BLS Owners' Equivalent Rent (OER) directly.
  OER measures contract rent of existing leases; ZORI measures
  asking rent on the spot market. Divergence between them is itself
  a signal (e.g., asking can fall before OER reflects it).
- NOT available for all 895 ZHVI metros — only 719.

### Inventory — "count of active for-sale listings"

**How to read it.** `40640.0` means "about 40,640 homes were
actively listed for sale in this metro during that month." Float
type because of smoothing, but conceptually a count.

**Common analysis recipes.**

```
# Months of supply (a standard housing-market indicator)
# inventory ÷ monthly sales count (sales data needed from another source)
months_of_supply = inventory_m / monthly_sales_count_m

# Year-over-year inventory change (%) — supply-side signal
inventory_yoy_pct = 100 * (inventory_m / inventory_same_month_prior_year - 1)

# Seasonal interpretation — even smoothed/SA series shows residual
# seasonality. Q2 normally has more inventory than Q4.
```

**What this number is NOT.**
- NOT new listings (flow). It's active stock — homes still listed.
- NOT all homes for sale — excludes pending, under contract,
  off-market.
- NOT "true peak supply" — smoothed values lag the actual peak by
  the smoothing window.

## Phase 4c — Cross-source correlation notes

For analyses that combine Zillow with other sources in this project's
catalog.

### Geography join key — Zillow ↔ everything else

**The single most important correlation gotcha.** Zillow's `RegionID`
is an **internal Zillow identifier** that does NOT match the Census
Core-Based Statistical Area (CBSA) code used by FHFA, BLS, Census,
FFIEC, HUD, etc.

| Source | Metro identifier | Joinable to Zillow's RegionID? |
|---|---|---|
| Zillow | `RegionID` (e.g., `394913` = NYC metro) | (this source) |
| FHFA | `place_id` = 5-digit CBSA code (`35620` = NYC metro) | **No — crosswalk required** |
| Census ACS | 5-digit CBSA code | **No — crosswalk required** |
| BLS LAUS | 5-digit CBSA code | **No — crosswalk required** |
| FFIEC / HMDA | 5-digit CBSA code | **No — crosswalk required** |
| HUD CHAS / FMR | 5-digit CBSA code | **No — crosswalk required** |
| Realtor.com (Projected) | CBSA code | **No — crosswalk required** |
| Apartment List (Projected) | CBSA code | **No — crosswalk required** |
| Redfin (Projected) | CBSA code | **No — crosswalk required** |

**Implication for the implementation project:** the silver layer
needs a `geography` dimension with both `cbsa_code` and
`zillow_region_id`, populated by a manual crosswalk built by name
match. This crosswalk is the single highest-leverage piece of
reference data the project will own. Recommend building it from
the Zillow `RegionName` + FHFA `place_name` matched pairs, with
manual disambiguation for the ~30–50 cases where names diverge
non-trivially.

### ZHVI ↔ FHFA HPI ↔ Case-Shiller — three different "home price" signals

All three measure metro-level home prices but use **different
methodologies and produce different numbers**. They are not
interchangeable; the differences are themselves analytical signal.

| Source | What it measures | Methodology | Units | Coverage |
|---|---|---|---|---|
| **ZHVI** | Estimated value of the typical mid-tier home | Proprietary AVM (machine learning) | Level USD | 895 metros |
| **FHFA HPI** | Price changes from repeat sales of the same property | Repeat-sales, weighted | Rebased index (100 = base period) | 400+ MSAs |
| **Case-Shiller** | Same idea as FHFA but value-weighted | Repeat-sales, value-weighted | Rebased index (100 = base period) | 20 specific MSAs only |

**To put all three on the same chart:**

```
# Rebase ZHVI to the same base period as FHFA/Case-Shiller for comparison.
# Pick a reference month (say, 2020-01-31). Then:

zhvi_rebased = 100 * (zhvi_value / zhvi_at_reference_month)
fhfa_rebased = 100 * (fhfa_index_nsa / fhfa_index_nsa_at_reference_quarter)
cs_rebased   = 100 * (cs_value / cs_value_at_reference_month)

# Now all three are unit-aligned ("index where 100 = 2020-01") and
# can be plotted on the same y-axis.
```

**Why they disagree (which is the analytical interest):**
- ZHVI uses an AVM — fast to react to current listings, but model
  output, not a transaction average.
- FHFA includes only GSE-financed homes (purchase-only flavor) —
  systematically excludes the high end (jumbo loans) and cash sales.
- Case-Shiller value-weights, so movements in expensive homes
  dominate — runs hotter than FHFA in hot markets.

This is the core of project question family #1 (methodology-aware
price reporting) and family #5 (cross-source disagreement signal).

### ZORI ↔ BLS Owners' Equivalent Rent (OER) — asking vs contract

| Source | What it measures | Lag character |
|---|---|---|
| **ZORI** | Asking rent (what landlords post) | **Leading** |
| **BLS OER** | Rent of primary residence in existing leases (CPI component) | **Lagging** |

Divergence is informative: a sharp drop in ZORI while OER stays
flat = market is softening but existing tenants haven't seen rent
reductions yet (leases not yet renewed). The two converging again
6–12 months later means OER caught up.

### Period-grain alignment

All Zillow `Metro_` files in this sample are **monthly**, month-end
dated. To join to other monthly sources, normalize on month-end
dates.

| Source | Cadence | Date semantics for joining |
|---|---|---|
| Zillow (this) | Monthly | Month-end (`YYYY-MM-DD` last day of month) |
| FHFA monthly | Monthly (USA + Division only) | `yr` + `period` (1–12) |
| FHFA quarterly | Quarterly | `yr` + `period` (1–4) — quarter, NOT month |
| FRED Mortgage Rates | Weekly | Week-end Thursday |
| Census ACS | Annual | Year |

**Joining Zillow monthly to FHFA quarterly** requires *aggregating
Zillow to the quarter* (mean of the three month-end values is the
common choice) or *taking only one Zillow month per quarter*
(typically the last month of the quarter as an end-of-period
snapshot).

### Coverage diffs to plan for

- ZORI excludes 191 metros that ZHVI covers — for any panel that
  needs both, inner-join shrinks the panel to 719 metros.
- Inventory covers 928 metros — broader than either price series.
- FHFA has Puerto Rico; Zillow does not.
- Case-Shiller has only 20 specific MSAs; everything else falls
  outside its coverage.

## Known gotchas (summary)

1. National row present in `Metro_` files — filter `RegionType='msa'`.
2. Coverage differs: Inventory (928) ⊃ ZHVI (895) ⊃ ZORI (719).
3. `RegionID` is Zillow-internal, NOT CBSA. Crosswalk required.
4. Wide → long unpivot required for any Spark/SQL ingest.
5. Publication lag ~16 days (April 30 data refreshed May 16).
6. Windowed sample is recent-only; widen `--months` for longer history.

## Terms of use

Zillow Research data — historically non-commercial + attribution.
Verify against the current Zillow Group ToU in a real browser before
public distribution. ToU pages were 403 to `WebFetch` in this session.

## Confidence

- **Verified** in this session: CDN URLs respond 200; files downloaded;
  windowing produced 12-month subsets; column types + samples
  confirmed via `document_columns.py`.
- **Projected**: methodology specifics (exact ZORI definition,
  smoothing window length, ToU language) — methodology pages 403'd
  to `WebFetch`; confirm in browser. Cross-source correlation
  formulas (Phase 4c) are standard analyst practice but not
  prescribed by the publishers themselves — the analyst should
  validate against the implementation project's own use case.
