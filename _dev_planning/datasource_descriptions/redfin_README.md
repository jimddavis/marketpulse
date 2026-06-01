# Redfin Data Center — sample data

Reference data from [Redfin Data Center](https://www.redfin.com/news/data-center/).
Pulled directly from Redfin's **public S3 bucket** (us-west-2),
no auth required.

Generated **2026-05-20** via the `re-data-acquisition` skill workflow.
Phase A4 in the catalog.

## Sample collection status — Phases 1, 2c complete

All 9 representative files pulled and windowed to last 12 months.
Covers all major Redfin product families (housing market tracker,
RHPI, investor purchases, luxury, balance of power, price drops,
contract cancellations, delistings/relistings). Smaller sub-products
(EHS by region, investor by category) intentionally skipped.

## What's here

| Local file | Product | Geo | Cadence | Rows | Window |
|---|---|---|---|---|---|
| `housing_market_tracker_top50_metros_monthly.csv` | Housing Market Tracker | Top-50 metros | Monthly | 550 | 2025-06 → 2026-04 |
| `housing_market_tracker_all_metros_weekly.csv` | Housing Market Tracker | All metros (~380) | Weekly (4-week rolling) | 2,350 | 2025-05-26 → 2026-04-13 |
| `rhpi_all_metros_monthly.csv` | **Redfin Home Price Index (RHPI)** | All metros | Monthly | 550 | 2025-06 → 2026-04 |
| `investor_purchases_all_metros.csv` | Investor Home Purchases | Metros (39) | **Quarterly** | 78 | 2025-Q3 → 2025-Q4 |
| `luxury_market_all_metros_monthly.csv` | Luxury Market | All metros | Monthly | 400 | 2025-06 → 2026-01 |
| `balance_of_power_top50_metros_monthly.csv` | Balance of Power (buyers vs sellers) | Top-50 metros | Monthly | 2,167 | 2025-06 → 2026-04 |
| `price_drops_top50_metros_monthly.csv` | Price Drops | Top-50 metros | Monthly | 550 | 2025-06 → 2026-04 |
| `contract_cancellations_top50_metros_monthly.csv` | Contract Cancellations | Top-50 metros | Monthly | 550 | 2025-06 → 2026-04 |
| `delistings_relistings_top50_metros_monthly.csv` | Delistings & Relistings | Top-50 metros | Monthly | 550 | 2025-06 → 2026-04 |

Total: ~1.1 MB across 9 files. **Quarterly Investor file is thin in
the 12-month window (2 quarters only — 78 rows total). Widen the
script's window to ≥24 months for richer Investor history.**

## How to re-fetch

```
python3.12 scratch/fetch_redfin_samples.py
```

Stdlib only; no auth. Idempotent (overwrites with latest data).
Script downloads each file in full from the S3 bucket, then
client-side windows to the last 12 months by `PERIOD BEGIN`.

## Phase 1 — API discovery (Verified 2026-05-20)

- **Publisher portal:** https://www.redfin.com/news/data-center/
  (HTML, reachable to `curl` with a real browser User-Agent.)
- **Downloads page:** https://www.redfin.com/news/data-center/downloads/
  (HTML, contains a JavaScript `CARDS` array listing every available
  file path — the most reliable inventory source.)
- **Bulk file CDN (Verified):** `https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/`
- **Auth:** None. Plain HTTP `GET`. No referrer, cookie, or signed
  URL needed. **A non-default `User-Agent` header IS required** —
  S3 returns the file regardless, but Redfin's HTML pages 403 the
  default Python `urllib` UA. Always send `User-Agent: Mozilla/5.0`
  or similar.

### S3 bucket layout

```
redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/
  housing_market/
    monthly/        { country, all_states, all_metros, top_50_metros,
                      all_counties, counties_in_top_50_metros,
                      all_cities, top_50_cities, all_zips,
                      zips_in_top_50_metros, all_neighborhoods,
                      nbhds_in_top_50_metros }.csv
    weekly/         { country, all_metros }.csv
  buyers_and_sellers/monthly/ { country, all_census_regions, top_50_metros }.csv
  rhpi/monthly/               { country, all_metros }.csv
  investors/by_metro/         { country, all_metros }.csv
  investors/by_category/      { price_tier, property_type }.csv
  luxury/{luxury,non_luxury,both}/  { country, state, all_metros }.csv
  price_drops/monthly/        ~12 geo variants (same as housing_market)
  price_drops/weekly/         { country, all_metros }.csv
  contract_cancellations/monthly/  ~12 geo variants
  contract_cancellations/weekly/   { country, all_metros }.csv
  delistings_relistings/monthly/   ~12 geo variants
  delistings_relistings/weekly/    { country, all_metros }.csv
  ehs/monthly/                { country, all_census_regions }.csv
```

~80 file paths total across products × cadences × geographies.

### Column-meaning channels

| Channel | Format | Reached this session? |
|---|---|---|
| **JS file inventory** in `downloads/` HTML page (`const CARDS = [...]`) | JavaScript object literal | Yes — parsed for path discovery + per-product `keyColumns` |
| **Per-product methodology blurbs** on individual product pages (e.g., `redfin.com/news/redfin-home-price-index`) | HTML | Partial — methodology blurbs on the downloads page are short paragraphs per `CARDS[].desc` |
| **CSV column headers** | embedded in each file | Yes — descriptive, e.g. `MEDIAN SALE PRICE ($)`, `INVESTOR MARKET SHARE (%)` |

**Auto-discoverable?** **Partial.** File inventory + product
descriptions + key columns are all in the downloads page's JS, which
parses cleanly. Methodology *depth* requires reading the linked
product pages. Column names are self-descriptive in the CSV but no
separate per-column data dictionary exists.

## Phase 2 — Date range probing AND windowing

### Phase 2a — Available range

| Product | Available start (per JS metadata) | Available end (this batch) |
|---|---|---|
| Housing Market Tracker — monthly | 2012 | 2026-04-01 |
| Housing Market Tracker — weekly (4-week) | 2016 | 2026-04-13 |
| RHPI | varies | 2026-04-01 |
| Investor Home Purchases | quarterly history back ~10 yrs | 2025-Q4 |
| Luxury Market | recent | 2026-01-01 |
| Buyers & Sellers (BoP) | recent | 2026-04-01 |
| Price Drops / Contract Cancellations / Delistings / Relistings | varies | 2026-04-01 |

### Phase 2b — Target window

**12 months** — skill default. For the quarterly **Investor** file
this gives only 2 quarters. Widen to 24+ months if the investor
cohort is needed for analysis. Other files fit comfortably.

### Phase 2c — Windowing (Verified)

**Client-side**, by `PERIOD BEGIN` column, after full download.
Redfin's S3 bucket doesn't offer server-side date-range parameters
(S3 is a flat object store; date filtering requires reading the
file). The full files are small enough (<4 MB) that this is fine.

## Phase 3 — Detail enumeration

- **Geographic granularities offered:** national, census region,
  state, metro, county, city, ZIP, neighborhood. Coverage varies
  by product (`investors`, `luxury`, `rhpi` are metro-and-above
  only).
- **Cadence:** weekly (4-week rolling), monthly, quarterly. Weekly
  is metros-only; quarterly is the investor-purchases series only.
- **Methodology source:** Redfin compiles from **MLS feeds it
  participates in**. Coverage is national but not exhaustive — Redfin
  excludes markets where it lacks MLS membership.
- **RHPI methodology:** repeat-sales index (like FHFA + Case-Shiller),
  but using Redfin's MLS-direct dataset rather than GSE financing
  records (FHFA) or Case-Shiller's 20-city panel. Provides a **4th
  methodology lens** for question family #5.
- **Distinctive products** (rationale for inclusion in MVP):
  - **Investor Home Purchases by metro** — quarterly metro
    breakdown of investor-buyer share. No other free source has
    this cohort breakout. Supports question family #4.
  - **Balance of Power** — monthly buyer-vs-seller index. SA, metro
    grain. Unique to Redfin.
  - **Luxury Market** — top-5% home-price cohort separated from
    bottom-95%. Affordability-distribution angle.

## Phase 4 — Column documentation (Verified 2026-05-20)

Columns vary by product. Three universal patterns:

### Shared identifier columns (every file)

| # | Column | Type | What it means | Sample | Gotchas |
|---|---|---|---|---|---|
| 1 | `LAST UPDATED` | string (`YYYY-MM-DD`) | When Redfin last refreshed the row. | `2026-05-03` | Publication date, not observation date. |
| 2 | `FREQUENCY` | string (enum) | Cadence: `Monthly` / `Weekly` / `Quarterly`. | `Monthly` | Per-row, not per-file — useful when a file mixes cadences (rare). |
| 3 | `PERIOD BEGIN` | string (`YYYY-MM-DD`) | First day of the observation period. **Canonical date for filtering / joining.** | `2026-04-01` | For weekly files, the start of a 4-week rolling window. |
| 4 | `PERIOD END` | string (`YYYY-MM-DD`) | Last day of the observation period. | `2026-04-30` | `(PERIOD_END - PERIOD_BEGIN)` is constant within a file. |
| 5 | `REGION TYPE` | string (enum) | `Country` / `State` / `Metro` / `County` / `City` / `ZIP` / `Neighborhood`. | `Metro` | Filename gives the broadest type; row-level can specialize. |
| 6 | `REGION NAME` | string | Human-readable geography name. CBSA-style for metros, e.g. `'Anaheim, CA metro area'`. | `'Anaheim, CA metro area'` | **Embedded comma + quoted.** Use a real CSV parser, not str-split. **Not a join key.** |

### Metric columns — by product

#### `housing_market_tracker_*` (30 columns total)

Base metrics: `HOMES SOLD`, `MEDIAN SALE PRICE ($)`, `MEDIAN DAYS ON
MARKET (DAYS)`, `NEW LISTINGS`, `ACTIVE LISTINGS`, `PENDING SALES`,
`OFF-MARKET IN 2 WEEKS (%)`, `OFF-MARKET IN 1 WEEK (%)`, `% HOMES
SOLD ABOVE LIST`, `AVERAGE SALE-TO-LIST RATIO (%)`, `MONTHS OF
SUPPLY`. Each base has `MOM (%)` and `YOY (%)` companions →
deterministic from base + lag.

#### `rhpi_all_metros_monthly.csv`

Redfin Home Price Index. Columns: `RHPI`, `RHPI MOM (%)`, `RHPI YOY
(%)`, plus seasonality flags. **Index is rebased per-metro; base
period documented per series on the Redfin product page.**

#### `investor_purchases_all_metros.csv` (9 columns)

`INVESTOR HOME PURCHASES` (count), `INVESTOR HOME PURCHASES YOY (%)`,
`INVESTOR MARKET SHARE (%)`. **39 metros × 2 quarters in this
windowed batch** — coverage is sparse.

#### `luxury_market_all_metros_monthly.csv`

Same shape as housing_market but filtered to the **top 5% by price**
within each metro (the "luxury" subset). Companion file `luxury/
non_luxury/` (NOT pulled in this batch) covers the bottom 95%.

#### `balance_of_power_top50_metros_monthly.csv`

`BUYERS`, `SELLERS`, `BUYER-SELLER RATIO`, `SELLER-BUYER %
DIFFERENCE`. **SA monthly index** — Redfin's proprietary measure of
whether market conditions favor buyers or sellers. >0 favors buyers;
<0 favors sellers.

#### `price_drops_*`, `contract_cancellations_*`, `delistings_relistings_*`

Each follows the same `<METRIC>`, `<METRIC> MOM (%)`, `<METRIC> YOY
(%)` family pattern. Self-descriptive column names.

### `_mm` / `_yy` (or equivalent MoM / YoY) derived columns

Every numeric base metric has matching `MOM (%)` and `YOY (%)`
companion columns — percentage values (NOT decimal fractions; this
differs from Realtor.com's `_mm` / `_yy` which use decimals). Multiply
by 0.01 to align with Realtor.com convention if doing cross-source
arithmetic.

## Phase 4b — Practical interpretation

### Reading `MEDIAN SALE PRICE ($)`

Closed-sale median. **Closed sale, NOT listing** — distinguishes
from Realtor.com's `median_listing_price`. Use for analyses that need
*transacted* price; use Realtor.com for what's currently *on the
market*.

### Reading `BALANCE OF POWER`

Index centered around 0:
- `>+20`: strong buyers' market (lots of choice, slow sales)
- `0 to +20`: weak buyers' market
- `-20 to 0`: weak sellers' market
- `<-20`: strong sellers' market

Useful for **categorizing market states**; pair with `MONTHS OF
SUPPLY` from the Housing Market Tracker for cross-validation.

### Reading `INVESTOR MARKET SHARE (%)`

Percent of all home purchases in the metro made by investors (LLCs,
LPs, REITs). Values **>20%** are notable — that's roughly where the
post-2021 investor-buying wave peaked. Anaheim 25.76% in 2025-Q4 is
high; SF was historically much lower.

## Phase 4c — Cross-source correlation notes

### Geography join

Redfin's `REGION NAME` is a string like `'Anaheim, CA metro area'`.
**No CBSA code column.** Joining to FHFA / Census / Realtor.com
requires name-matching, which is fragile. Build a one-time crosswalk
table from REGION NAME to CBSA code; cache it.

### Redfin RHPI ↔ Case-Shiller ↔ FHFA HPI ↔ Zillow ZHVI

Four "home price" methodologies, four different things:

| Source | Methodology | Source data | Coverage |
|---|---|---|---|
| RHPI | Repeat-sales, MLS-direct | Redfin's MLS feeds | All metros where Redfin has MLS |
| Case-Shiller | Repeat-sales, value-weighted | County recorders | 20 specific MSAs only |
| FHFA HPI | Repeat-sales, unit-weighted | GSE-conforming loans + appraisals | 400+ MSAs |
| Zillow ZHVI | AVM (proprietary ML) | Zillow listing pipeline | 895 metros |

For question family #5 (cross-source disagreement), **rebase all four
to a common base period** (e.g., 2020-01 = 100) before plotting.

### Redfin Housing Market Tracker ↔ Realtor.com

Both compile from MLS. Different MLS-membership coverage → metric
divergence per metro. Use Realtor.com for **listing-side** metrics
(asking price, DOM); use Redfin for **transaction-side** metrics
(median sale price, sale-to-list ratio).

## Known gotchas

1. **Real browser User-Agent required** for the HTML pages (NOT for
   the S3 bucket — that returns 200 to any UA).
2. **CSV uses quoted fields with embedded commas** in REGION NAME.
   Use `csv.reader` / `csv.DictReader`, never str-split.
3. **No CBSA codes** — geography join is by name match only. Build a
   crosswalk.
4. **`MOM (%)` and `YOY (%)` are PERCENTAGES, not decimals.** Realtor.com
   uses decimals; if combining, scale.
5. **Investor data is quarterly only** — thin in a 12-month window
   (2 quarters). Widen for richer investor history.
6. **Luxury file is "top 5% only"** — pair with `luxury/non_luxury/`
   for the bottom-95% comparison (not pulled in this batch).
7. **Brand display** — files are produced by Redfin Corporation;
   coverage exists only where Redfin participates in the local MLS.
   Markets without Redfin presence (some Texas / Florida sub-metros)
   may be sparsely populated.

## Terms of use

Redfin's data-center publication is intended for "free use with
attribution + link back to redfin.com/news/data-center." Verify
exact terms on the data-center page before redistribution.
**Non-commercial / research use is unambiguously allowed.**

## Confidence

- **Verified 2026-05-20**: S3 bucket URL, full file inventory via JS
  parsing, 9 representative files downloaded and parsed, column
  shape per product family confirmed.
- **Projected**: full per-product methodology details (the linked
  product pages contain prose explanations; not all read this
  session). CBSA crosswalk strategy (not yet built).
- **Outstanding**: build a `redfin_region_name → cbsa_code` crosswalk
  before cross-source join work. Per-column data dictionary for
  RHPI and Balance-of-Power (Redfin does not publish one — fields
  are self-descriptive but exact methodology lives only in HTML
  product pages).
