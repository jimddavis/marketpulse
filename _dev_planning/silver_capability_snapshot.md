# Silver capability snapshot

**Purpose.** A one-page, factual inventory of what the **Silver layer can analytically support** — the
grounding input for pre-Gold research and design. It describes *what is in the data and how it
connects*, not what reports to build. Sourced from `databricks_code/libs/ddl/silver_ddl.py` (schema)
and the verified prod==dev baseline of 2026-06-01 (counts/coverage; see `deployment_status` memory).
Grade: **Verified** (schema read directly; counts queried this session).

---

## 1. The analytical surface in one sentence

Metro-level (CBSA) **housing-market time series** (prices, rents, inventory, listing dynamics) —
monthly and quarterly — set against a **national macro backdrop** (rates, CPI, unemployment,
affordability) and joined to a **static per-metro hazard & climate profile**. Three axes: **geography
(CBSA) × time (month/quarter) × source**, plus two non-time dimensions (macro = national; hazard/
climate = static).

---

## 2. Tables, grain, coverage

**Conformed dimensions**

| Table | Grain | Key | Rows | Notes |
|---|---|---|---|---|
| `dim_geo` | CBSA (metro/micro) | `geo_key` (identity) | 935 | OMB 2023 universe. Carries `cbsa_population` (935), `census_region` (925; 10 PR null), `household_rank` (925), `zillow_region_id` (859). |
| `dim_date` | day (period-end) | `date_key` yyyymmdd | 1,020 | Month-end grain; `quarter`/`year`/`is_quarter_end` for quarterly rollups. |
| `dim_fred_series` | FRED series | `series_id` | 10 | label / units / **frequency** (weekly/monthly/quarterly/annual). |

**Facts** (measures summarized; see DDL for full column comments)

| Fact | Grain | Entities | Rows | Time span | Cadence | Key measures |
|---|---|---|---|---|---|---|
| `fact_zillow_metro_monthly` | CBSA × month | 859 metros | 271,444 | 2000–2026 | monthly | `typical_home_value` (ZHVI), `typical_rent` (ZORI), `inventory_active` |
| `fact_realtor_metro_monthly` | CBSA × month | 935 metros | 109,160 | 2016–2026 | monthly | `median_listing_price`, `active_listing_count`, `median_days_on_market`, `new_listing_count`, `price_reduced_share`, `pending_ratio`, `median_listing_price_per_square_foot`, `median_square_feet`, … (15 base metrics) |
| `fact_fhfa_hpi_metro_quarterly` | CBSA × quarter | 373 metros | 63,334 | 1975-Q3–2026-Q1 | quarterly | `index_nsa` (rebased HPI), `standard_error` |
| `fact_fred_series` | series × obs date | 10 series | 7,949 | varies/series | weekly→annual | `value` (long; meaning per series) — mortgage 30/15yr, CPI, UNRATE, MSPUS, affordability, Case-Shiller SA/NSA, real median HH income, active listings |
| `fact_fema_hazard_cbsa` | CBSA (static) | 935 (10 PR null on scores) | 935 | single NRI vintage | none | `risk_score`, `sovi_score`, `resl_score`, `eal_valt` ($), `population`, + 10 per-hazard scores (hurricane, coastal/inland flood, tornado, wildfire, earthquake, hail, strong wind, heat wave, winter weather) |
| `fact_noaa_climate_cbsa` | CBSA (static) | 924 | 924 | 1991–2020 normals | none | 13 climate normals: seasonal/annual avg temp, annual high/low, precip, snow, heating/cooling degree-days (°F / inches) |

`quarantine` (~22,480 rows) is rejected-row provenance, not analytical content — entirely housing-side
geography/null rejects; weather sources contributed 0.

---

## 3. How the facts connect (the join graph)

```
                        dim_date (month/quarter)
                              │ date_key
   zillow ─┐                  │
   realtor ─┼── geo_key ── dim_geo (CBSA) ── geo_key ──┬─ fema_hazard (static)
   fhfa ───┘                                           └─ noaa_climate (static)
                              │
   fred (NATIONAL, no geo) ── joins to metro facts on DATE only ──┘
```

- **All metro facts share `dim_geo` (`geo_key`)** → directly comparable/joinable across sources *for a
  given metro*.
- **`fact_fred_series` has no geography** — it joins to metro facts on **date only**, as a national
  backdrop applied to every metro. (Its native cadence varies; the wide forward-filled monthly strip
  is a Gold serving concern.)
- **Hazard & climate are static** (one value per metro, no date) — they join on `geo_key` and broadcast
  across every time period. They *enrich* a metro, they don't trend.

**Coverage overlap (load-bearing for any cross-source report):** source breadth differs —
realtor & hazard ≈ all 935; climate 924; zillow 859; **fhfa only 373**. A metro present in one source
may be absent in another. The dependable "all-housing-sources + hazard + climate" intersection is
roughly the **fhfa 373** (the narrowest), or ~859 if FHFA is excluded. Any "compare every metro across
all sources" view must decide inner vs outer join explicitly.

---

## 4. What the data can answer (capabilities)

- **Metro housing trends over time** — price/rent/inventory/days-on-market trajectories per metro
  (monthly from Zillow/Realtor; quarterly appreciation from FHFA).
- **Market momentum & heat** — `median_days_on_market`, `pending_ratio`, `price_reduced_share`,
  inventory direction; derivable YoY/MoM growth.
- **Cross-metro ranking/comparison** — rank or percentile metros by growth, affordability proxy,
  inventory tightness, days-on-market (within a period).
- **Affordability (proxy)** — metro prices/rents vs the **national** macro strip (mortgage rates,
  income, CPI-deflated real terms, affordability index). Note: rates/income are national, not per-metro.
- **Rent vs own** — `typical_rent` vs `typical_home_value` per metro (Zillow), price-to-rent ratio
  derivable.
- **Risk-/climate-adjusted housing** *(the differentiator)* — overlay static hazard `risk_score` /
  per-hazard scores and climate normals on housing trends: e.g. "appreciating, affordable metros that
  are also low-hazard / temperate." Almost no mainstream housing dashboard carries this seam.

## 5. Boundaries (what it can NOT answer — be honest in any design)

- **No sub-metro grain in Silver.** County/station detail exists only in Bronze (FEMA/NOAA); Silver
  rolled it up to CBSA. ZIP/tract/county housing not present at all.
- **No actual per-metro sale prices.** Zillow = modeled value (ZHVI) + asking rent; Realtor = *listing*
  (asking) prices; FHFA = an *index*, not dollars. Only `MSPUS` (FRED) is an actual sale price — and
  it's **national**. "Median sale price for metro X" is not directly answerable.
- **Macro is national only.** No metro-level interest rates, income, or CPI.
- **Hazard & climate are static, single-vintage.** One NRI snapshot; 1991–2020 normals. Cannot trend
  risk or climate over time, and cannot align them to a specific housing month/quarter.
- **Non-recoverable Silver drops** (gone unless re-derived from Bronze/source): FHFA **SA** variant
  (only NSA kept); per-county/per-station granularity (rolled up); FEMA **ratings** (scores kept).
  *Recoverable* (derivable downstream, not lost): Realtor `_mm`/`_yy` MoM/YoY companions.
- **Series gaps** (per `silver_row_counts.sql` no-gap check, dev 2026-06-01): zillow/realtor fully
  contiguous; FHFA 42 metros / 132 quarters missing (93% pre-1985 — harmless post-2000); FRED
  `CPIAUCSL` + `UNRATE` each miss 2025-10 (source-side BLS release gap, should self-heal on refresh).

## 6. Derivation opportunities visible from the data (candidates only — design later)

Pure transforms of columns already present (no new ingestion): YoY/QoQ/MoM % change; rolling 3/12-mo
averages; YTD; index-to-base; price-to-rent ratio; months-of-supply proxy (`inventory_active` or
`active_listing_count` vs flow); metro rank/percentile within a period; metro-vs-national spread;
CPI-deflated real series; a composite affordability or "market-heat" score; hazard/climate banding
(e.g. risk quartiles). **Where each should live (Gold column vs BI measure) is a design decision, not
settled here.**

---

*Feeds:* the pre-Gold `/sc:research` prompt and the eventual Gold `/sc:design`. Naming/derivation
specifics live in `silver_gold_column_name_mapping.md`; this doc is the data-capability ground truth.
