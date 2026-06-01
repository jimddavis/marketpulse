# Silver → Gold column-name mapping (pre-Gold planning)

**Goal:** at the Gold (serving) layer every column name should be **self-explanatory** — a reader
(or a Power BI author) understands it without a data dictionary. Cryptic source abbreviations
(`eal_valt`, `hrcn_risks`, `ann_tavg_normal`, `index_nsa`) get descriptive names here.

**Conventions used in the suggestions below:**
- Still `snake_case` (UC/project standard, CLAUDE.md §9) — "human-friendly" = *descriptive*, not cryptic.
- **Units encoded in the name** where it removes ambiguity: `_pct` (percent), `_usd` (dollars),
  `_f` (°Fahrenheit), `_inches`, `_score` (0–100 index), degree-days spelled out.
- **One COMMENT carries both the display label and the description.** Each row's **Gold COMMENT**
  is formatted `Display Label: description` and is **verbatim what goes into the `COMMENT '...'`
  clause of the Gold `CREATE TABLE`**. Rationale: the COMMENT is the only one of name/label/
  description that is an actual Databricks artifact — Unity Catalog columns have a name, a type, and
  a COMMENT; there is **no separate "display name" property**. Leading the COMMENT with the friendly
  label means a developer running `DESCRIBE`, and any BI tool that surfaces UC comments as a field
  description, both get the label + meaning from one owned source. A Power BI author takes the text
  **before the colon** as the display name. *(Whether the connector auto-pulls the COMMENT into the
  BI Description is connector/mode-dependent — Projected; worst case the PBI author copies it once.)*
- **Keys and audit columns are out of scope here.** `geo_key`/`date_key`/`series_id` and
  `inserted_ts`/`updated_ts` are handled by the Gold serving model (the weather profiles already
  expose `geo_level`/`geo_id`/`geo_name`); this doc covers the **measure/value** columns only.

Status per fact: **fhfa** (1 col) · **fred** (pivots to 10 cols) · **fema_hazard** (15 cols) ·
**noaa_climate** (13 cols) need names. **realtor** and **zillow** are already well-named — no change.

---

## 1. `fact_fhfa_hpi_metro_quarterly`

Meaning per `_dev_planning/datasource_descriptions/fhfa_README.md` (rebased repeat-sales index;
`100.0` = the reference quarter's price level; the silver canonical variant is **all-transactions,
NSA**, so reference = **1995-Q1 = 100**).

| Silver column | Suggested Gold column | Gold COMMENT (`Display Label: description`) |
|---|---|---|
| `index_nsa` | **`home_price_index`** | Home Price Index (1995-Q1 = 100): rebased all-transactions repeat-sales house-price index, not seasonally adjusted; 100 = the reference quarter's price level (e.g. 293 ≈ 2.93× reference-quarter prices). |
| `standard_error` *(companion — not in your list; included for completeness)* | **`home_price_index_std_error`** | Home Price Index — Std. Error: standard error of the index estimate, in index points. |

*Note:* the rebasing makes the raw index value hard to read in isolation — the value is a *ratio*
to a reference quarter (1995-Q1 = 100), not a dollar price, and two metros' levels are **not**
comparable (each is anchored to its own 1995-Q1 base). The self-contained, consumer-readable metric
is a **derived** `home_price_index_pct_change_yoy` (year-over-year % change) at Gold, alongside the
rebased level — flag for the Gold design, not a rename.

> **YoY derivation — gotchas for the Gold design (not a rename; flagged here so the work isn't lost):**
> - **Use YoY, not QoQ.** The source is **NSA** (not seasonally adjusted). Comparing a quarter to the
>   *same quarter one year prior* cancels the seasonal component without modeling it; QoQ would
>   conflate trend with the seasonal calendar. YoY on a quarterly series stays quarterly — one YoY
>   value per quarter, each looking back 4 quarters.
> - **Derive via a date-aware self-join, NOT positional `LAG(index_nsa, 4)`.** `LAG(...,4)` grabs
>   "4 rows back," which equals "4 quarters back" *only if the metro's series is contiguous*. Across a
>   gap it silently returns the wrong quarter and a plausible-but-wrong YoY. Join `cur` to `prior` on
>   `geo_key` + the *actual* prior-year quarter (resolved through `dim_date`); a missing prior-year
>   quarter then yields `NULL` (correct) instead of a wrong value.
> - **No-gap check at Gold build time.** Either derivation assumes a contiguous quarterly series per
>   metro. Add a build-time assertion that, per `geo_key`, the row count equals
>   `MAX(quarter_ordinal) − MIN(quarter_ordinal) + 1` (ordinal = `year*4 + quarter`); investigate any
>   metro where it doesn't.
> - **Measured gap profile (`dev_marketpulse.silver`, 2026-06-01):** 373 metros, span 1975-Q3→2026-Q1;
>   **42 metros (11%) have gaps, 132 missing quarters total — but 93% of those fall in 1980–1984** and
>   only **2** fall after 1990. So YoY is safe for any realistic (post-2000) reporting window; the
>   gaps are confined to early, smaller-metro history. The date-aware join is still the right pattern
>   precisely because even a handful of modern gaps would corrupt a positional `LAG`.

---

## 2. `fact_fred_series` — `value`

`value` is polymorphic (its meaning depends on `series_id`). The Gold serving form is the **wide,
forward-filled national time series** (one column per series — the "cadence reconciliation is a Gold
concern" from the overview). So `value` doesn't get one name; it **pivots to one column per series**:

| `series_id` | Suggested Gold column | Gold COMMENT (`Display Label: description`) |
|---|---|---|
| `MORTGAGE30US` | **`mortgage_rate_30yr_pct`** | 30-Yr Fixed Mortgage Rate (%): average US 30-year fixed mortgage rate (FRED MORTGAGE30US); percent, weekly. |
| `MORTGAGE15US` | **`mortgage_rate_15yr_pct`** | 15-Yr Fixed Mortgage Rate (%): average US 15-year fixed mortgage rate (FRED MORTGAGE15US); percent, weekly. |
| `FIXHAI` | **`housing_affordability_index`** | Housing Affordability Index: fixed-rate housing affordability index (FRED FIXHAI); monthly; higher = more affordable. |
| `MSPUS` | **`median_sales_price_usd`** | Median Sales Price ($US): median sales price of houses sold in the US (FRED MSPUS); quarterly. |
| `UNRATE` | **`unemployment_rate_pct`** | Unemployment Rate (%): US unemployment rate (FRED UNRATE); monthly. |
| `MEHOINUSA672N` | **`real_median_household_income_usd`** | Real Median Household Income (2022 $): inflation-adjusted US median household income (FRED MEHOINUSA672N); annual. |
| `ACTLISCOUUS` | **`active_listing_count`** | Active Listing Count: Realtor.com US active for-sale listing count (FRED ACTLISCOUUS); monthly. |
| `CSUSHPISA` | **`case_shiller_hpi_sa`** | Case-Shiller US HPI (Seasonally Adjusted): S&P/Case-Shiller US national home price index, seasonally adjusted (FRED CSUSHPISA); index, monthly. |
| `CSUSHPINSA` | **`case_shiller_hpi_nsa`** | Case-Shiller US HPI (Non Seasonally Adjusted): S&P/Case-Shiller US national home price index, raw/unadjusted (FRED CSUSHPINSA); index, monthly. |
| `CPIAUCSL` | **`cpi_all_urban_sa`** | CPI — All Urban (Seasonally Adjusted): Consumer Price Index for all urban consumers, SA (FRED CPIAUCSL); the deflator for real-dollar analysis. |

*Note:* these are **national** (no `geo_key`); the Gold table is a date-keyed national macro strip,
joined to the metro facts on date, not geography.

> **Cadence/gap profile (`dev_marketpulse.silver`, 2026-06-01) — and why forward-fill is the right Gold form:**
> Per-series cadence-aware check (day-spacing between consecutive `observation_date`s vs each series'
> modal spacing). **8 of 10 series are gap-free** (weekly mortgage series' 8–9-day maxes are holiday
> reporting shifts, not missing weeks; annual/quarterly/other monthlies contiguous). **`CPIAUCSL` and
> `UNRATE` are each missing exactly one month — both 2025-10 (Oct 2025).** Same month in two
> independent BLS series at the recent edge ⇒ a **source-side release gap** (Projected: the late-2025
> US government shutdown delayed BLS October releases, so FRED had no value when `download_sources`
> ran), **not** a load artifact (Verified: the row is simply absent for that PK). **Implication:** the
> chosen **forward-fill** wide Gold form absorbs this correctly — Sept 2025's value carries into the
> Oct slot, which is the right behavior for a genuinely-unpublished month. Unlike FHFA YoY (where a gap
> corrupts a positional `LAG`), FRED needs **no** special handling — just keep forward-fill as the
> serving rule rather than emitting nulls/zeros for unpublished months.

---

## 3. `fact_realtor_metro_monthly` — no change

Already well-named (`median_listing_price`, `active_listing_count`, `median_days_on_market`,
`price_reduced_share`, …); their existing silver COMMENTs carry through to Gold. *(Optional: add
`_usd` to price columns and `_share`→`_pct` only if you want unit suffixes uniform across Gold — cosmetic.)*

## 4. `fact_zillow_metro_monthly` — no change

Already well-named (`typical_home_value`, `typical_rent`, `inventory_active`); silver COMMENTs carry through.

---

## 5. `fact_fema_hazard_cbsa`

Source of meaning: **`_local_downloads/fema_nri/README.md`** (the FEMA National Risk Index data
dictionary) + the existing column COMMENTs in `silver_ddl.py` / `weather_data.py`. All `_score`
columns are **0–100 national percentiles**. NRI composite: `Risk = Expected Annual Loss × Social
Vulnerability ÷ Community Resilience`.

| Silver column | Suggested Gold column | Gold COMMENT (`Display Label: description`) |
|---|---|---|
| `population` | **`population`** | Population: resident population of the CBSA (sum of FEMA NRI county population); also the weight behind the intensive scores in this row. |
| `eal_valt` | **`expected_annual_loss_usd`** | Expected Annual Loss ($US): FEMA NRI expected annual loss from all hazards, total, in dollars (summed across the CBSA's counties). |
| `risk_score` | **`overall_risk_score`** | Overall Risk Score: composite FEMA National Risk Index score, 0–100 national percentile (higher = greater risk); Risk = Expected Annual Loss × Social Vulnerability ÷ Community Resilience. |
| `sovi_score` | **`social_vulnerability_score`** | Social Vulnerability Score: how badly the population is likely to be affected by a hazard, and how hard it is for them to respond and recover — driven by socioeconomic/demographic characteristics, independent of the hazard (CDC/ATSDR SVI-derived; 0–100 national percentile, higher = more vulnerable). |
| `resl_score` | **`community_resilience_score`** | Community Resilience Score: the community's capacity to prepare for, absorb, recover from, and adapt to a hazard (BRIC-derived; 0–100 national percentile, higher = more resilient — NOTE: opposite direction to every other score here, where higher = worse). |
| `hrcn_risks` | **`hurricane_risk_score`** | Hurricane Risk Score: FEMA NRI hurricane Risk Index score, 0–100 (higher = greater risk). |
| `cfld_risks` | **`coastal_flood_risk_score`** | Coastal Flood Risk Score: FEMA NRI coastal-flooding Risk Index score, 0–100 (higher = greater risk). |
| `ifld_risks` | **`inland_flood_risk_score`** | Inland Flood Risk Score: FEMA NRI inland (riverine) flooding Risk Index score, 0–100 (higher = greater risk). |
| `trnd_risks` | **`tornado_risk_score`** | Tornado Risk Score: FEMA NRI tornado Risk Index score, 0–100 (higher = greater risk). |
| `wfir_risks` | **`wildfire_risk_score`** | Wildfire Risk Score: FEMA NRI wildfire Risk Index score, 0–100 (higher = greater risk). |
| `erqk_risks` | **`earthquake_risk_score`** | Earthquake Risk Score: FEMA NRI earthquake Risk Index score, 0–100 (higher = greater risk). |
| `hail_risks` | **`hail_risk_score`** | Hail Risk Score: FEMA NRI hail Risk Index score, 0–100 (higher = greater risk). |
| `swnd_risks` | **`strong_wind_risk_score`** | Strong Wind Risk Score: FEMA NRI strong-wind Risk Index score, 0–100 (higher = greater risk). |
| `hwav_risks` | **`heat_wave_risk_score`** | Heat Wave Risk Score: FEMA NRI heat-wave Risk Index score, 0–100 (higher = greater risk). |
| `wntw_risks` | **`winter_weather_risk_score`** | Winter Weather Risk Score: FEMA NRI winter-weather Risk Index score, 0–100 (higher = greater risk). |

---

## 6. `fact_noaa_climate_cbsa`

Source of meaning: column COMMENTs in `silver_ddl.py` / `weather_data.py` (1991–2020 NOAA Climate
Normals; CBSA mean-of-stations). Seasons: DJF = winter, MAM = spring, JJA = summer, SON = autumn.

| Silver column | Suggested Gold column | Gold COMMENT (`Display Label: description`) |
|---|---|---|
| `ann_tavg_normal` | **`avg_annual_temp_f`** | Avg Annual Temp (°F): 1991–2020 annual average temperature normal, °F (CBSA mean-of-stations). |
| `djf_tavg_normal` | **`avg_winter_temp_f`** | Avg Winter Temp (°F): winter (Dec–Feb) average temperature normal, °F (mean-of-stations). |
| `mam_tavg_normal` | **`avg_spring_temp_f`** | Avg Spring Temp (°F): spring (Mar–May) average temperature normal, °F (mean-of-stations). |
| `jja_tavg_normal` | **`avg_summer_temp_f`** | Avg Summer Temp (°F): summer (Jun–Aug) average temperature normal, °F (mean-of-stations). |
| `son_tavg_normal` | **`avg_autumn_temp_f`** | Avg Autumn Temp (°F): autumn (Sep–Nov) average temperature normal, °F (mean-of-stations). |
| `ann_tmax_normal` | **`avg_annual_high_temp_f`** | Avg Annual High (°F): annual average daily maximum temperature normal, °F (mean-of-stations). |
| `ann_tmin_normal` | **`avg_annual_low_temp_f`** | Avg Annual Low (°F): annual average daily minimum temperature normal, °F (mean-of-stations). |
| `jja_tmax_normal` | **`avg_summer_high_temp_f`** | Avg Summer High (°F): summer average daily maximum temperature normal, °F (mean-of-stations). |
| `djf_tmin_normal` | **`avg_winter_low_temp_f`** | Avg Winter Low (°F): winter average daily minimum temperature normal, °F (mean-of-stations). |
| `ann_prcp_normal` | **`annual_precipitation_inches`** | Annual Precipitation (in): annual precipitation normal, inches (mean-of-stations). |
| `ann_snow_normal` | **`annual_snowfall_inches`** | Annual Snowfall (in): annual snowfall normal, inches (mean-of-stations). |
| `ann_htdd_normal` | **`annual_heating_degree_days`** | Annual Heating Degree Days: annual heating degree-days normal, base 65°F (mean-of-stations). |
| `ann_cldd_normal` | **`annual_cooling_degree_days`** | Annual Cooling Degree Days: annual cooling degree-days normal, base 65°F (mean-of-stations). |

---

## Open questions for the Gold design

1. **Unit-suffix uniformity** — apply `_usd`/`_pct`/`_f`/`_inches` everywhere (incl. retro-fitting
   realtor/zillow price/share columns), or only where the source name was cryptic? (Above: only
   where it adds clarity; realtor/zillow left as-is.)
2. **FHFA derived metric** — add `home_price_index_pct_change_yoy` at Gold (more intuitive than the
   rebased level)? Decide in the Gold design.
3. **FRED wide pivot** — confirm the Gold national strip is one column per series (names in §2),
   forward-filled to a common monthly cadence, per the overview's "cadence reconciliation is Gold."
4. **RESL polarity** — `community_resilience_score` is the lone "higher = better" measure among the
   hazard scores; its COMMENT flags this. Decide in the Gold/BI design whether to also surface a
   consistent "higher = worse" framing (do **not** invert the source value silently).
