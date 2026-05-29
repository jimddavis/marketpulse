# Realtor.com Research — sample data

Sample CSVs from Realtor.com's Real Estate Data Library, used in
Phase 1 (dataset evaluation) of this project.

Generated **2026-05-16** via the `re-data-acquisition` skill workflow
(first onboarding after Zillow + FHFA; first source with composite-
date columns and inline derived `_mm`/`_yy` metrics).

**Raw CSVs are gitignored.** This README is the reproduction recipe,
the per-column data dictionary, and the operational interpretation
guide.

## Sample window

**The history file is windowed to the last 12 months (2025-05 → 2026-04).**
Publisher publishes monthly; full history goes back to **2016-07** at
metro grain. The snapshot file naturally contains only the latest month
(2026-04). Re-download + re-window for wider history.

## Phase 1 — API discovery

- **Publisher portal:** https://www.realtor.com/research/data/
  **Reachable HTTP 200**, but **blocked to `WebFetch`** by Claude Code's
  fetcher (similar to Zillow). Use a real browser to inspect.
- **Bulk file S3 bucket (Verified HTTP 200):**
  `https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/`
  **NOT linked from the portal HTML directly** — discovered by probing
  the obvious S3 path that Realtor.com famously uses for their econ
  research data. The bucket itself returns 403 on a directory listing
  (S3 ListBucket denied) but specific file URLs return 200.
- **Auth:** None. Standard HTTP GET.

### Files Verified accessible at the S3 bucket

```
RDC_Inventory_Core_Metrics_Country.csv          ~1 KB   national, latest month only
RDC_Inventory_Core_Metrics_State.csv            ~17 KB  state, latest month only
RDC_Inventory_Core_Metrics_Metro.csv            ~298 KB metro, latest month only  ← saved as snapshot
RDC_Inventory_Core_Metrics_Metro_History.csv    ~32 MB  metro, full history (2016-07 →)  ← saved + windowed
RDC_Inventory_Core_Metrics_County.csv           ~894 KB county, latest month only
RDC_Inventory_Core_Metrics_Zip.csv              ~7.2 MB ZIP, latest month only
```

Equivalent `*_History.csv` files exist for Country/State/County/Zip;
this onboarding probed Metro only.

### Other Realtor.com files NOT reachable at the obvious paths

Probed and returned 403 in this session (may exist at different naming):

- `Reports/Hotness/RDC_Inventory_Hotness_Metrics_Metro.csv`
- `Reports/Weekly/RDC_Inventory_Weekly_Core_Metrics_Metro.csv`
- `Reports/Weekly/RDC_Inventory_Weekly_Country.csv`

Weekly and Hotness data series are referenced in Realtor.com's
research publications but their exact bulk-download URLs were not
discoverable in this session. Browser-side inspection of the portal
recommended for future expansion.

### Column-meaning channels consulted (per skill Phase 1, step 5)

| Channel | Format | Reached this session? |
|---|---|---|
| Realtor.com Real Estate Data Library portal | HTML | **No** — `WebFetch` blocked (portal itself returns 200; Claude Code's fetcher refuses) |
| Realtor.com methodology blog posts (e.g., "September 2022 methodology revamp") | HTML blog | **No** — `WebFetch` blocked |
| FRED per-series pages for the Realtor.com republication (e.g., https://fred.stlouisfed.org/series/ACTLISCOUUS) | HTML | **No** — also 403 to `WebFetch` |
| FRED `series/` API metadata endpoint for republished series | JSON API | **Not tried this session** (no FRED_API_KEY available); **promising auto-discoverable channel for future** |
| Column names themselves (self-describing for listing metrics) | filename + header | Yes |

**Auto-discoverable?** **No (with caveat).** Direct sources are
WebFetch-blocked. **However, every base metric in this file is also
republished on FRED**; if a future onboarding has a `FRED_API_KEY`,
the `series/` metadata endpoint provides machine-readable column
definitions for the same data. This makes Realtor.com effectively
**auto-discoverable-via-FRED** in practice.

**Follow-up:** capture the Realtor.com methodology pages in a real
browser and link the relevant ones in `references/sources.md`.

## What's here

| Local file | What the data is | Approx size | Upstream filename |
|---|---|---|---|
| `inventory_core_metrics_metro_snapshot.csv` | **Latest-month snapshot** of all Realtor.com core inventory metrics at metro grain. 936 rows (1 per CBSA-metro), 47 columns. | 298 KB | `RDC_Inventory_Core_Metrics_Metro.csv` |
| `inventory_core_metrics_metro_history.csv` | **Historical monthly series**, same 47 columns, one row per `(metro, month)`. **Windowed to last 12 months** (2025-05 → 2026-04). | 3.4 MB | `RDC_Inventory_Core_Metrics_Metro_History.csv` |

Both files use the **same schema**. The snapshot is just the latest
month of the history file (which itself is the windowed last 12).

## How to re-fetch (full history)

```bash
mkdir -p data/samples/realtor
cd data/samples/realtor
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

# Snapshot (latest month only):
curl -sSL -A "$UA" -o inventory_core_metrics_metro_snapshot.csv \
  https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Metro.csv

# History (~32 MB — full ~10 years):
curl -sSL -A "$UA" -o inventory_core_metrics_metro_history.csv \
  https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Metro_History.csv
```

**Note on windowing:** the project's `scripts/window_file.py` does
NOT yet handle composite-date columns like `month_date_yyyymm`
(it expects either `YYYY-MM-DD` headers (wide) or `yr`+`period` columns
(long)). For this source, window manually:

```python
import pandas as pd
df = pd.read_csv("inventory_core_metrics_metro_history.csv", low_memory=False)
months = sorted(df["month_date_yyyymm"].unique())
df[df["month_date_yyyymm"].isin(months[-12:])].to_csv(
    "inventory_core_metrics_metro_history.csv", index=False
)
```

This is logged as skill defect #1 in
`critique_skill_iter2_2026-05-16.md`.

## Phase 2 — Date range probing AND windowing

### Phase 2a — Available range

| File | Min available | Max available | Months | Rows | CBSAs |
|---|---|---|---|---|---|
| Snapshot | 2026-04 | 2026-04 | 1 (latest only) | 936 | 936 |
| History | 2016-07 | 2026-04 | 118 | 109,150 (full) | 925 |

### Phase 2c — Windowed range

| File | Range kept | Rows kept |
|---|---|---|
| Snapshot | 2026-04 (unchanged) | 936 |
| History | 2025-05 → 2026-04 (12 months) | 11,100 |

## Phase 3 — Detail enumeration

- **Maximum granularity Realtor.com offers (per portal):** national,
  state, metro (CBSA), county, ZIP. The History file pattern repeats
  for each grain (`RDC_Inventory_Core_Metrics_<Grain>_History.csv`).
- **This sample targets `Metro` grain only.**
- **Cadence:** Monthly (Core Metrics). Weekly series also exist
  (Weekly Core Metrics) but URLs not discoverable in this session.
- **What's NOT here:** no per-property records; no hedonic features
  beyond the median-aggregate level (e.g., `median_square_feet` is
  the metro median, not per-property). No sale prices — only **list
  prices**. Aggregated listing-side data only.
- **What's distinctive vs other catalog sources:**
  - **Listing-side metrics** (median_listing_price, active_listing_count,
    median_days_on_market) — what's *on the market*, before any sale.
    Complementary to Zillow (value estimates) and FHFA (recorded
    transactions).
  - **Inline derived columns**: every base metric carries `_mm`
    (month-over-month change as a decimal fraction, e.g. 0.0306 = +3.06%)
    and `_yy` (year-over-year change). Reduces downstream computation
    but expands schema to 47 columns.
  - **`pending_ratio`**: a unique Realtor.com-derived metric =
    pending listings / active listings; a market-velocity indicator.

## Phase 4 — Column documentation (schema table — ETL/ingestion layer)

The two files share the same 47-column schema. Documenting once for
both.

### Identifier columns (1–4)

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `month_date_yyyymm` | int64 | **Period identifier — a composite date encoded as integer `YYYYMM`** (e.g., `202604` = April 2026). Use `pd.to_datetime(str, format='%Y%m')` to convert. | `202604` | **NOT a standard date column.** The project's `probe_date_range.py` does not detect this shape (expects `YYYY-MM-DD` headers OR `yr`+`period` columns). Filter on integer comparison: `month_date_yyyymm BETWEEN 202505 AND 202604` for the windowed range. |
| 2 | `cbsa_code` | int64 | **Census Core-Based Statistical Area (CBSA) code** — 5-digit. Canonical US-metro identifier used by Census/BLS/FFIEC/HUD/FHFA. | `35620` (New York-Newark-Jersey City) | Joins directly to FHFA `place_id`/`cbsa`/`CBSACode`, Census ACS metro queries, BLS LAUS metro series. **Does NOT match Zillow `RegionID`** — name crosswalk required for Zillow joins. |
| 3 | `cbsa_title` | string | **Office of Management and Budget (OMB) metro definition string.** Same string Census/FHFA use for the same CBSA. | `'New York-Newark-Jersey City, NY-NJ'` | **Display only — never use as a join key.** Realtor.com's strings are CONSISTENT with FHFA's for the same CBSA, but verifying string equality is fragile; use `cbsa_code`. |
| 4 | `HouseholdRank` | int64 | **Rank of this metro by household count** (population-related, but specifically households, not people). `1` = largest metro by households. | `1` (NYC), `106` (Ogden, UT) | Useful for "top N metros" cuts. Differs slightly from Zillow's `SizeRank` (which uses population, not households) — close but not identical ordering. |

### Base metrics (14 columns) — schema table

Each base metric has the same shape: nullable numeric, with two
derived companion columns (`_mm` and `_yy`). The base metrics:

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 5 | `median_listing_price` | float64 | **Median asking price** (US Dollars) of all active for-sale listings in the metro during the month. **Asking price, NOT sale price.** | `772929.0` | Nominal USD. Skewed by listing mix (more mansions on market → higher median). NOT comparable to FHFA HPI (transaction-based, repeat-sales index) without methodology context. |
| 8 | `active_listing_count` | int64 | **Count of homes actively listed for sale** in the metro during the month. Excludes pending, under-contract, and off-market listings. | `33514` | Stock-level snapshot per month. Same conceptual meaning as Zillow's `inventory_for_sale_*` file but **different counting rules** (Realtor.com uses MLS-derived counts; Zillow uses its own pipeline). The two diverge by ~5–15% per metro. |
| 11 | `median_days_on_market` | float64 | **Median number of days** active listings have been on the market at month-end. Lower = hotter market. | `41.0` | Median, not mean — robust to long-tail stale listings. Methodology revamped Sept 2022 (improved duplicate-listing handling) — older history may not be directly comparable to recent. |
| 14 | `new_listing_count` | int64 | **Count of listings newly added** during the month. Flow metric (additions during the month), not a snapshot. | `18666` | Complement to `active_listing_count` (stock). `new_listing_count` rising with `active_listing_count` flat means listings sell as fast as they arrive. |
| 17 | `price_increased_count` | int64 | **Count of active listings whose price was increased** during the month. Rare-event indicator — sellers raise prices when they think the market is hot. | `316` | Numerator for `price_increased_share`. Often a small count in soft markets; the `_mm`/`_yy` companions may be **54%+ null** in those periods. |
| 20 | `price_increased_share` | float64 | **Share of active listings with a price increase**, as a decimal fraction (0.0049 = 0.49%). Complement to `price_reduced_share`. | `0.0049` | Decimal fraction (NOT percent). Multiply by 100 for "%" display. |
| 23 | `price_reduced_count` | float64 | **Count of active listings whose price was reduced** during the month. Larger numbers than `price_increased_count` in normal markets. | `5694.0` | Numerator for `price_reduced_share`. Float not int because of nullability in early history. |
| 26 | `price_reduced_share` | float64 | **Share of active listings with a price reduction**, decimal fraction. Cyclical: rises in late summer (peak-stale-listing season), falls in spring (rush of new listings). | `0.0828` | Decimal fraction. A `price_reduced_share > price_increased_share` consistently is the normal market state. Inversion is unusual. |
| 29 | `pending_listing_count` | float64 | **Count of listings under contract** at month-end (between offer-accepted and closing). Forward-indicator of upcoming closed sales. | `15920.0` | Lead time from `pending` → closed sale typically 30–60 days. |
| 32 | `median_listing_price_per_square_foot` | float64 | **Median listing price normalized by square footage** (USD per sq ft). Useful for comparing metros with very different median home sizes. | `540.0` | Computed at listing level then medianed (not `median_price ÷ median_sqft`). NYC = $540/sqft because of small high-priced units; Houston might be $180/sqft for much larger homes. |
| 35 | `median_square_feet` | float64 | **Median home size** of active listings in the metro (square feet). Captures the listing-mix shift toward smaller or larger homes. | `1411.0` | The same NYC metro showing `540` in price-per-sqft has `1411` median sqft — relatively small homes are typical there. |
| 38 | `average_listing_price` | float64 | **Mean (not median) of listing prices** in the metro. **Far more sensitive to outliers** than `median_listing_price`. | `1577835.0` | NYC average is 2× median because a few $20M+ listings pull the mean up. Use median for typical-home-price analyses; use average for total-market-value or mix-shift analyses. |
| 41 | `total_listing_count` | int64 | **Total listings**, INCLUDING pending and contingent — i.e., `active + pending + others`. Broader denominator than `active_listing_count`. | `49112` | Use `total_listing_count` for "total market depth" framing. Use `active_listing_count` for "homes a buyer could actually consider today." |
| 44 | `pending_ratio` | float64 | **Realtor.com-derived market-velocity indicator** = `pending_listing_count / active_listing_count`. Higher = faster market. | `0.475` | **Unique to Realtor.com** — not in Zillow or FHFA. Values around 0.5+ indicate strong demand; values below 0.2 indicate cooling. |
| 47 | `quality_flag` | float64 | **Data-quality indicator** — 0 = no quality issue flagged; other values indicate Realtor.com's data team has flagged the row as potentially anomalous. | `0.0` | Float type because of nullability. **Filter `quality_flag = 0`** for clean analyses; investigate non-zero rows before including. Methodology source not documented in this session — investigate. |

### Derived columns — `_mm` and `_yy` (28 columns total)

**Documented as one rolled-up row per family** per the skill's
wide-format convention (avoids 28 nearly-identical rows).

For each base metric `X` (14 base metrics in this file), two derived
companion columns are pre-computed by Realtor.com:

| Suffix | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|
| `_mm` (month-over-month) | float64 | **Decimal-fraction change** from the prior month: `(X_this_month / X_prior_month) - 1`. Example: `0.0306` for `median_listing_price_mm` = "median listing price rose 3.06% vs the prior month." | `0.0306` | Decimal fraction (NOT percent). Multiply by 100 for "%" display. Null when prior month is missing (first month in the file). For `_count` family in low-activity periods, can be **>50% null** when the count itself was zero. |
| `_yy` (year-over-year) | float64 | **Decimal-fraction change** from 12 months prior: `(X_this_month / X_12_months_ago) - 1`. Example: `-0.0209` for `median_listing_price_yy` = "median listing price fell 2.09% vs the same month a year ago." | `-0.0209` | Same decimal-fraction convention. Null for the first 12 months of any metro's history. **Preferred over `_mm`** for headline reporting because YoY removes seasonality. |

All 28 `_mm`/`_yy` columns follow this exact pattern; the meaning is
fully predictable from the base column they're derived from. **For
ingestion code, do not separately validate these 28; they are
deterministic functions of the base + lag.**

## Phase 4b — Practical interpretation (BI / analyst layer)

This section is **additive** to the schema table above.

### `median_listing_price` — "what the typical home is being asked for"

**How to read it.** A value of `772929.0` literally means **$772,929**
— the median asking price of homes currently listed for sale in this
metro. It is what sellers *want*, not what buyers *pay*.

**Common analysis recipes.**

```
# Year-over-year change in asking prices
yoy_pct = 100 * (median_listing_price / median_listing_price_12m_ago - 1)
# Or use the precomputed _yy column directly (saves a join):
yoy_pct = median_listing_price_yy * 100

# List-to-sale price gap (requires FHFA HPI or NAR EHS for sale data)
# This is the leading-vs-lagging price signal — listing prices fall
# weeks-to-months before sale prices in cooling markets.

# Real (inflation-adjusted) price — same pattern as Zillow ZHVI
real_listing_price = median_listing_price * (cpi_base / cpi_this_month)
```

**What this number is NOT.**
- NOT a sale price. Sellers' asking prices typically run **2–5%
  above** final sale prices in normal markets, more in soft markets.
- NOT an index. A level dollar value — NOT rebased.
- NOT comparable across metros at face value without size/quality
  normalization. Use `median_listing_price_per_square_foot` for
  cross-metro comparison.
- NOT directly comparable to Zillow ZHVI. ZHVI = AVM-estimated *home
  value* (model output across the housing stock). Realtor.com
  `median_listing_price` = median of *listings on the market this
  month* (selection-biased toward homes sellers chose to list).

### `active_listing_count` — "homes a buyer could actually consider this month"

**How to read it.** `33514` literally means about 33,500 homes were
actively listed for sale in this metro during the month — available
for a buyer to make an offer on. Excludes pending, contingent, and
off-market.

**Common analysis recipes.**

```
# Months of supply (canonical housing-market indicator)
months_of_supply = active_listing_count / monthly_closed_sales
# < 4 months = sellers' market; 4-6 months = balanced; > 6 = buyers'

# Sales-to-inventory pacing (proxy for absorption rate)
new_listings_to_active_ratio = new_listing_count / active_listing_count
# Rising means inventory growing faster than new listings (cooling)
# Falling means inventory drawing down (heating)
```

**What this number is NOT.**
- NOT a flow. Active listings is a *stock* — the count of "things
  still listed." For flow (newly added), use `new_listing_count`.
- NOT comparable directly to Zillow's inventory file — different
  source pipelines, different counting conventions; expect 5–15%
  divergence per metro.

### `median_days_on_market` — "how long the typical listing waits"

**How to read it.** `41.0` literally means the median active listing
has been on the market for 41 days at month-end. Lower = faster
market. **This is current cohort DOM, not historical sale DOM.**

**Common analysis recipes.**

```
# Year-over-year acceleration in market speed
dom_yoy_change_days = median_days_on_market - median_days_on_market_12m_ago
# Negative = market speeding up (lower DOM); positive = slowing
# Or in percent: dom_yy * 100

# Compare to Zillow's days-on-Zillow series (if pulled) — Realtor.com
# uses MLS-derived DOM; Zillow uses listing-portal-derived. Methodology
# differs.
```

**What this number is NOT.**
- NOT historical-sale DOM (how long sold homes took to sell). It's
  current-cohort DOM (active listings only). Closed-sale DOM is a
  different — usually lower — number (slow listings are still on the
  market; fast listings already sold and dropped out).
- NOT methodology-stable over the full history — Realtor.com
  re-derived DOM in Sept 2022; pre-2022 DOM values may not be
  directly comparable to post-2022.

### `pending_ratio` — "market-velocity gauge"

**How to read it.** `0.475` means **47.5% of active inventory is
under contract** (pending). A market-temperature indicator unique
to Realtor.com.

**Common analysis recipes.**

```
# Hot/normal/cold heuristics (approximate, calibrate per metro)
if pending_ratio > 0.6:    # Hot — listings move fast
if pending_ratio < 0.2:    # Cold — listings sit
# Mid-range 0.3-0.5 = normal

# Decompose changes — is pending up or active down?
pending_yoy = pending_listing_count_yy
active_yoy  = active_listing_count_yy
# If pending_yoy > active_yoy → demand growing faster than supply
```

**What this number is NOT.**
- NOT a probability that a given listing will sell. It's a ratio of
  two counts, not a per-listing prediction.
- NOT comparable across metros without context — different metros
  have structurally different normal pending ratios (some MLS regions
  report "pending" sooner than others in the offer process).

## Phase 4c — Cross-source correlation notes

For analyses that combine Realtor.com with other sources in this
project's catalog.

### Geography join — `cbsa_code` is canonical

Realtor.com uses 5-digit Census CBSA codes — matches FHFA, Census ACS,
BLS LAUS, FFIEC HMDA, HUD CHAS/FMR, Census Building Permits directly.

| Source | Identifier | Joinable to Realtor.com `cbsa_code`? |
|---|---|---|
| Realtor.com (this) | `cbsa_code` | (this source) |
| FHFA | `place_id` (MSAs) / `cbsa` / `CBSACode` | **Yes — direct equality** |
| Census ACS | CBSA | **Yes** |
| BLS LAUS | CBSA | **Yes** |
| FFIEC/HMDA | CBSA | **Yes** |
| HUD CHAS/FMR | CBSA | **Yes** |
| Census Building Permits | CBSA | **Yes** |
| **Zillow** | `RegionID` (Zillow internal) | **No — crosswalk required** |

Same crosswalk pattern as FHFA: Zillow is the only outlier.

### Realtor.com ↔ Zillow — listing vs. value, different counts

| Metric | Realtor.com | Zillow | Relationship |
|---|---|---|---|
| Home value | `median_listing_price` (asking) | `ZHVI` (AVM-estimated value, level USD) | Realtor.com is "what sellers ask"; Zillow is "what the model thinks it's worth." Both nominal USD but **conceptually different**. Listing prices typically **5–10% above** ZHVI in soft markets; **close to or below** ZHVI in hot markets when sellers are conservative. |
| Inventory | `active_listing_count` | `inventory_for_sale_*` | Both purport to count "for-sale homes" but use different source pipelines. Expect **5–15% divergence per metro**. Use `(realtor_count + zillow_count) / 2` as a robust composite OR pick one consistently. |
| Days on market | `median_days_on_market` | `Days on Zillow` (similar but separate file) | Methodology differs. Realtor.com from MLS; Zillow from listings on their platform. |
| Rent | (not in Realtor.com — they publish a separate rent series) | `ZORI` | Out of scope for this Realtor.com file. |

**Coverage:** Realtor.com Metro file covers ~936 CBSAs; Zillow ZHVI
covers ~895. Inner-join shrinks the panel.

### Realtor.com ↔ FHFA HPI — listing price vs. rebased price index

| Source | What it measures | Units |
|---|---|---|
| Realtor.com `median_listing_price` | **Asking price** of currently listed homes (a level) | Nominal USD |
| FHFA HPI `index_nsa` | **Repeat-sales price change** of transacted homes (an index, base = series-specific) | Unitless ratio × 100 |

**Cannot be compared directly.** To put on the same chart, rebase
Realtor.com to the same period as FHFA:

```python
listing_idx = 100 * (median_listing_price / median_listing_price_at_2020_01)
fhfa_idx    = 100 * (fhfa_nsa / fhfa_nsa_at_2020_q1)
# Both: 100 = 2020 baseline. Now comparable in shape (cumulative growth)
# but still semantically different (asking vs transacted).
```

The **gap between Realtor.com listing-price growth and FHFA HPI
transaction-price growth** is itself a signal. In cooling markets,
listing prices fall first → Realtor.com index drops below FHFA HPI →
FHFA catches up 2–4 quarters later as sales close at lower prices.

### Realtor.com ↔ FRED republication

The same Realtor.com Core Metrics series are **republished on FRED**
with stable series IDs (e.g., `ACTLISCOUUS` for US active-listing
count, `ACTLISCOU<CBSA>` per metro). FRED is the **canonical
machine-readable column-meaning channel** for these series via the
`series/` API metadata endpoint — preferred over scraping
Realtor.com's portal once FRED B1 is onboarded.

### Period-grain alignment

| Source | Cadence | Date semantics for joining |
|---|---|---|
| Realtor.com (this) | Monthly | `month_date_yyyymm` int (`YYYYMM`) |
| Zillow | Monthly | Month-end (`YYYY-MM-DD` last day of month) |
| FHFA monthly | Monthly (USA + Division only) | `yr` + `period` (1–12) |
| FHFA quarterly | Quarterly | `yr` + `period` (1–4) |
| FRED | Per-series | Various |

**Joining Realtor.com to Zillow on the month** requires converting
`202604` → `2026-04-30` (the last day of April 2026, matching Zillow's
month-end convention). Recipe:

```python
import pandas as pd
df['month_end'] = pd.to_datetime(df['month_date_yyyymm'].astype(str), format='%Y%m') + pd.offsets.MonthEnd(0)
```

This belongs in the silver layer's date dimension.

### Coverage diffs

- Realtor.com covers 936 CBSAs (broadest in the catalog so far).
- ZHVI covers 895 → 41 metros Realtor.com has that Zillow doesn't.
- ZORI covers 719 → 217 metros Realtor.com has that Zillow has no
  rent data for.
- FHFA AT covers ~410 MSAs → much smaller intersection.
- Inner-join Realtor.com × Zillow × FHFA → ~410 metros.

## Known gotchas (summary)

1. **Composite-date column** (`month_date_yyyymm` int, not standard
   date) — project's `probe_date_range.py` and `window_file.py` don't
   handle this shape. Manual workaround required.
2. **`_mm`/`_yy` columns are decimal fractions** (0.0306, not 3.06).
3. **`quality_flag != 0` rows** flagged by Realtor.com as
   potentially anomalous — filter unless investigated.
4. **Asking price ≠ sale price** — Realtor.com is listing-side, not
   transaction-side.
5. **Sept 2022 methodology revamp** — `median_days_on_market` and
   duplicate-listing handling changed. Pre-2022 vs post-2022 may not
   be directly comparable.
6. **WebFetch blocked** on realtor.com and FRED HTML pages — use
   browser for portal exploration.
7. **Windowed sample is recent-only.** Widen `--months` for longer history.

## Terms of use

Realtor.com data appears to be free for non-commercial research +
attribution use (consistent with other industry research data sources),
but **the actual Realtor.com ToU pages were not reachable to `WebFetch`
this session**. Verify in a real browser before any public redistribution.

## Confidence

- **Verified** in this session: S3 bucket URLs respond 200; file
  sizes match Content-Length; schemas captured by direct inspection;
  windowing applied; `cbsa_code` confirmed as canonical Census CBSA
  via cross-check against FHFA `place_id`.
- **Projected**: methodology details (exact `pending_ratio` formula,
  `quality_flag` value meanings, Sept 2022 methodology-revamp scope,
  ToU specifics) — all source pages 403'd to `WebFetch`. Confirm in a
  real browser before any decision that hinges on precise methodology.
- **Auto-discoverable status**: marked **No (directly)** but **Yes (via
  FRED republication)** — exact channel pending FRED API key.
