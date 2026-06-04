# ddl/gold_ddl.py
# Gold-layer table DDL. create_gold_tables creates the 8-object star schema (idempotent,
# CREATE IF NOT EXISTS) so the Gold build transforms have their targets. Standalone — imports
# the shared _run_ddl/_ok/_fail from ddl._utils (same contract as audit_ddl/bronze_ddl/silver_ddl).
# Design + decisions: _dev_planning/design_docs/gold_layer_design.md (Phase G0).
#
# Three conformed dims + four per-source facts:
#   dim_geo            CBSA. CARRIED VERBATIM from silver.dim_geo with the SAME key values —
#                      geo_key is a plain BIGINT PK here, NOT GENERATED ALWAYS AS IDENTITY:
#                      Gold inherits Silver's geo_key (the G1 build does INSERT...SELECT geo_key),
#                      so re-generating identity would mint non-matching keys (design §2.1/§2.3).
#   dim_date           day (every calendar day; daily so it can be a Power BI Date Table). Carried
#                      verbatim from Silver; date_key is the deterministic yyyymmdd INT. is_month_end /
#                      is_quarter_end flag the days the monthly / quarterly facts join on.
#   dim_metro_environment  CBSA, static (no date), 1:1 with dim_geo. Holds the FEMA hazard (15) + NOAA
#                      climate (13) attributes, renamed/COMMENTed per silver_gold_column_name_mapping
#                      §5/§6. expected_annual_loss_usd + population are RETAINED as the additive base
#                      for the deferred region rollup — do NOT trim (design §3.3; risk-aggregation §7).
#   fact_zillow_metro_monthly     CBSA x month. + derived price_to_rent_ratio, gross_rental_yield_pct.
#   fact_realtor_metro_monthly    CBSA x month. 15 base metrics; the inventory/time-on-market family
#                                 carries the Sep-Nov 2022 methodology-break note in its COMMENT.
#   fact_fhfa_metro_quarterly     CBSA x quarter. index_nsa->home_price_index; + derived YoY.
#   fact_fred_national_monthly    month, NATIONAL (no geo). The 10 FRED series as wide columns
#                                 (mapping §2); forward-filled monthly is a build concern (G2).
# dim_fred_series is NOT carried into Gold — FRED pivots wide, so series become columns (design §2.1).
#
# Derived columns (price_to_rent_ratio, gross_rental_yield_pct, home_price_index_pct_change_yoy) are
# declared here but NULL until the G2 build populates them.
#
# PK constraints are declared inline (UC informational, not enforced — documents the grain). FK
# constraints are added in a SECOND guarded pass (_add_gold_foreign_keys) because ALTER...ADD FOREIGN
# KEY requires the parent PK to already exist and is not idempotent; the guard mirrors _migrate_dim_geo.
# Audit columns inserted_ts/updated_ts are on every table (left uncommented, self-evident, per silver).

from ddl._utils import _fail, _ok, _run_ddl

# (child_table, constraint_name, fk_columns, parent_table, parent_columns)
# Added after all tables exist. REFERENCES targets the parent PK (Verified: ALTER...ADD FOREIGN KEY
# requires a defined PRIMARY KEY on the parent). No RELY — it is an optimizer hint, irrelevant to the
# Power BI connector's relationship discovery, which reads UC metadata (design §6, §8 open-Q #1).
_FOREIGN_KEYS = [
    ("dim_metro_environment",          "fk_metro_environment_geo", "geo_key",  "dim_geo",  "geo_key"),
    ("fact_zillow_metro_monthly",  "fk_fact_zillow_geo",   "geo_key",  "dim_geo",  "geo_key"),
    ("fact_zillow_metro_monthly",  "fk_fact_zillow_date",  "date_key", "dim_date", "date_key"),
    ("fact_realtor_metro_monthly", "fk_fact_realtor_geo",  "geo_key",  "dim_geo",  "geo_key"),
    ("fact_realtor_metro_monthly", "fk_fact_realtor_date", "date_key", "dim_date", "date_key"),
    ("fact_fhfa_metro_quarterly",  "fk_fact_fhfa_geo",     "geo_key",  "dim_geo",  "geo_key"),
    ("fact_fhfa_metro_quarterly",  "fk_fact_fhfa_date",    "date_key", "dim_date", "date_key"),
    ("fact_fred_national_monthly", "fk_fact_fred_date",    "date_key", "dim_date", "date_key"),
]


def _add_gold_foreign_keys(spark, gold_schema):
    """Idempotently add the Gold FK constraints once all tables exist.

    ALTER TABLE ... ADD CONSTRAINT is not idempotent and has no IF NOT EXISTS, so each FK is guarded
    by an existence check against information_schema.table_constraints (three-part addressable).
    Safe to re-run: an FK already present is skipped. Mirrors the guard style of _migrate_dim_geo.
    """
    catalog     = gold_schema.split(".")[0]
    schema_name = gold_schema.split(".")[-1]
    try:
        added = []
        for child, fk_name, fk_cols, parent, parent_cols in _FOREIGN_KEYS:
            already = spark.sql(f"""
                SELECT 1 FROM {catalog}.information_schema.table_constraints
                WHERE constraint_schema = '{schema_name}' AND constraint_name = '{fk_name}'
                LIMIT 1
            """).take(1)
            if not already:
                spark.sql(
                    f"ALTER TABLE {gold_schema}.{child} ADD CONSTRAINT {fk_name} "
                    f"FOREIGN KEY ({fk_cols}) REFERENCES {gold_schema}.{parent} ({parent_cols})"
                )
                added.append(fk_name)
        return _ok(f"Gold foreign keys ok ({len(added)} added).", added)
    except Exception as e:
        return _fail("Gold foreign-key creation failed.", e)


def create_gold_tables(spark, gold_schema):
    statements = [
        # ---- Conformed dimensions (created before facts) --------------------------------
        (f"{gold_schema}.dim_geo", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.dim_geo (
                geo_key            BIGINT NOT NULL,    -- plain BIGINT: carries Silver geo_key, NOT identity
                cbsa_code          STRING NOT NULL COMMENT '5-digit Census CBSA code; canonical US metro/micro identifier (OMB 2023 delineation)',
                cbsa_title         STRING COMMENT 'Official OMB CBSA title, e.g. New York-Newark-Jersey City, NY-NJ',
                cbsa_type          STRING COMMENT 'metro (Metropolitan) or micro (Micropolitan) Statistical Area',
                zillow_region_id   STRING COMMENT 'Zillow RegionID mapped to this CBSA via the crosswalk; null where Zillow has no metro',
                primary_state      STRING COMMENT 'Primary (first-listed) state postal code of the CBSA',
                state_list         STRING COMMENT 'Hyphen-joined state postals the CBSA spans, e.g. NY-NJ-PA',
                household_rank     INT COMMENT 'Realtor.com household rank (1 = most populous); null where Realtor lacks the CBSA',
                census_region      STRING COMMENT 'US Census region (Northeast/Midwest/South/West) derived from primary_state; null for territories outside the four Census regions (e.g. PR)',
                cbsa_population    BIGINT COMMENT 'Total CBSA population (sum of FEMA NRI county population over the CBSA); shared weight for population-weighted State/Region rollups',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_dim_geo PRIMARY KEY (geo_key)
            )
        """),
        (f"{gold_schema}.dim_date", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.dim_date (
                date_key           INT NOT NULL COMMENT 'Deterministic yyyymmdd surrogate key (equals full_date as yyyymmdd)',
                full_date          DATE NOT NULL COMMENT 'Calendar date this row represents (one row per day)',
                year               INT COMMENT 'Calendar year',
                quarter            INT COMMENT 'Calendar quarter (1 to 4)',
                month              INT COMMENT 'Calendar month (1 to 12)',
                month_start        DATE COMMENT 'First day of the month',
                quarter_start      DATE COMMENT 'First day of the quarter',
                is_month_end       BOOLEAN COMMENT 'True if full_date is the last day of its month (the days the monthly facts join on)',
                is_quarter_end     BOOLEAN COMMENT 'True if full_date is a quarter-end (Mar/Jun/Sep/Dec)',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_dim_date PRIMARY KEY (date_key)
            )
        """),
        (f"{gold_schema}.dim_metro_environment", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.dim_metro_environment (
                geo_key                     BIGINT NOT NULL,
                population                  BIGINT COMMENT 'Population: resident population of the CBSA (sum of FEMA NRI county population); also the weight behind the intensive scores in this row.',
                expected_annual_loss_usd    BIGINT COMMENT 'Expected Annual Loss ($US): FEMA NRI expected annual loss from all hazards, total, in dollars (summed across the CBSA''s counties).',
                overall_risk_score          DOUBLE COMMENT 'Overall Risk Score: composite FEMA National Risk Index score, 0-100 national percentile (higher = greater risk); Risk = Expected Annual Loss x Social Vulnerability / Community Resilience.',
                social_vulnerability_score  DOUBLE COMMENT 'Social Vulnerability Score: how badly the population is likely to be affected by a hazard, and how hard it is for them to respond and recover - driven by socioeconomic/demographic characteristics, independent of the hazard (CDC/ATSDR SVI-derived; 0-100 national percentile, higher = more vulnerable).',
                community_resilience_score  DOUBLE COMMENT 'Community Resilience Score: the community''s capacity to prepare for, absorb, recover from, and adapt to a hazard (BRIC-derived; 0-100 national percentile, higher = more resilient - NOTE: opposite direction to every other score here, where higher = worse).',
                hurricane_risk_score        DOUBLE COMMENT 'Hurricane Risk Score: FEMA NRI hurricane Risk Index score, 0-100 (higher = greater risk).',
                coastal_flood_risk_score    DOUBLE COMMENT 'Coastal Flood Risk Score: FEMA NRI coastal-flooding Risk Index score, 0-100 (higher = greater risk).',
                inland_flood_risk_score     DOUBLE COMMENT 'Inland Flood Risk Score: FEMA NRI inland (riverine) flooding Risk Index score, 0-100 (higher = greater risk).',
                tornado_risk_score          DOUBLE COMMENT 'Tornado Risk Score: FEMA NRI tornado Risk Index score, 0-100 (higher = greater risk).',
                wildfire_risk_score         DOUBLE COMMENT 'Wildfire Risk Score: FEMA NRI wildfire Risk Index score, 0-100 (higher = greater risk).',
                earthquake_risk_score       DOUBLE COMMENT 'Earthquake Risk Score: FEMA NRI earthquake Risk Index score, 0-100 (higher = greater risk).',
                hail_risk_score             DOUBLE COMMENT 'Hail Risk Score: FEMA NRI hail Risk Index score, 0-100 (higher = greater risk).',
                strong_wind_risk_score      DOUBLE COMMENT 'Strong Wind Risk Score: FEMA NRI strong-wind Risk Index score, 0-100 (higher = greater risk).',
                heat_wave_risk_score        DOUBLE COMMENT 'Heat Wave Risk Score: FEMA NRI heat-wave Risk Index score, 0-100 (higher = greater risk).',
                winter_weather_risk_score   DOUBLE COMMENT 'Winter Weather Risk Score: FEMA NRI winter-weather Risk Index score, 0-100 (higher = greater risk).',
                avg_annual_temp_f           DOUBLE COMMENT 'Avg Annual Temp (F): 1991-2020 annual average temperature normal, Fahrenheit (CBSA mean-of-stations).',
                avg_winter_temp_f           DOUBLE COMMENT 'Avg Winter Temp (F): winter (Dec-Feb) average temperature normal, Fahrenheit (mean-of-stations).',
                avg_spring_temp_f           DOUBLE COMMENT 'Avg Spring Temp (F): spring (Mar-May) average temperature normal, Fahrenheit (mean-of-stations).',
                avg_summer_temp_f           DOUBLE COMMENT 'Avg Summer Temp (F): summer (Jun-Aug) average temperature normal, Fahrenheit (mean-of-stations).',
                avg_autumn_temp_f           DOUBLE COMMENT 'Avg Autumn Temp (F): autumn (Sep-Nov) average temperature normal, Fahrenheit (mean-of-stations).',
                avg_annual_high_temp_f      DOUBLE COMMENT 'Avg Annual High (F): annual average daily maximum temperature normal, Fahrenheit (mean-of-stations).',
                avg_annual_low_temp_f       DOUBLE COMMENT 'Avg Annual Low (F): annual average daily minimum temperature normal, Fahrenheit (mean-of-stations).',
                avg_summer_high_temp_f      DOUBLE COMMENT 'Avg Summer High (F): summer average daily maximum temperature normal, Fahrenheit (mean-of-stations).',
                avg_winter_low_temp_f       DOUBLE COMMENT 'Avg Winter Low (F): winter average daily minimum temperature normal, Fahrenheit (mean-of-stations).',
                annual_precipitation_inches DOUBLE COMMENT 'Annual Precipitation (in): annual precipitation normal, inches (mean-of-stations).',
                annual_snowfall_inches      DOUBLE COMMENT 'Annual Snowfall (in): annual snowfall normal, inches (mean-of-stations).',
                annual_heating_degree_days  DOUBLE COMMENT 'Annual Heating Degree Days: annual heating degree-days normal, base 65F (mean-of-stations).',
                annual_cooling_degree_days  DOUBLE COMMENT 'Annual Cooling Degree Days: annual cooling degree-days normal, base 65F (mean-of-stations).',
                inserted_ts                 TIMESTAMP,
                updated_ts                  TIMESTAMP,
                CONSTRAINT pk_dim_metro_environment PRIMARY KEY (geo_key)
            )
        """),
        # ---- Per-source fact tables -----------------------------------------------------
        (f"{gold_schema}.fact_zillow_metro_monthly", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.fact_zillow_metro_monthly (
                geo_key             BIGINT NOT NULL,
                date_key            INT NOT NULL,
                typical_home_value  BIGINT COMMENT 'Zillow smoothed mid-tier home value (35th-65th percentile)',
                typical_rent        BIGINT COMMENT 'Zillow smoothed asking rent across SFR + condo + multifamily',
                inventory_active    BIGINT COMMENT 'Zillow count of active for-sale listings observed in the metro that month',
                price_to_rent_ratio DOUBLE COMMENT 'Price-to-Rent Ratio: typical home value divided by annualized typical rent (typical_rent x 12); higher = buying is relatively more expensive than renting. Populated by the Gold build (G2).',
                gross_rental_yield_pct DOUBLE COMMENT 'Gross Rental Yield (%): annualized typical rent (typical_rent x 12) divided by typical home value, x100; gross, before costs. Populated by the Gold build (G2).',
                inserted_ts         TIMESTAMP,
                updated_ts          TIMESTAMP,
                CONSTRAINT pk_fact_zillow PRIMARY KEY (geo_key, date_key)
            )
        """),
        (f"{gold_schema}.fact_realtor_metro_monthly", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.fact_realtor_metro_monthly (
                geo_key                              BIGINT NOT NULL,
                date_key                             INT NOT NULL,
                median_listing_price                 BIGINT COMMENT 'Median asking price (USD) of active for-sale listings in the metro that month (asking, not sale)',
                active_listing_count                 BIGINT COMMENT 'Count of homes actively listed for sale (excludes pending, under-contract, off-market). Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                median_days_on_market                DOUBLE COMMENT 'Median days active listings have been on market at month-end (lower = hotter market). Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                new_listing_count                    BIGINT COMMENT 'Count of listings newly added during the month (flow, not snapshot). Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                price_increased_count                BIGINT COMMENT 'Count of active listings whose price was increased during the month. Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                price_increased_share                DOUBLE COMMENT 'Share of active listings with a price increase, decimal fraction (0.0049 = 0.49%). Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                price_reduced_count                  BIGINT COMMENT 'Count of active listings whose price was reduced during the month. Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                price_reduced_share                  DOUBLE COMMENT 'Share of active listings with a price reduction, decimal fraction. Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                pending_listing_count                BIGINT COMMENT 'Count of listings under contract at month-end (offer-accepted, not yet closed). Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                median_listing_price_per_square_foot BIGINT COMMENT 'Median listing price per square foot (USD per sq ft)',
                median_square_feet                   BIGINT COMMENT 'Median home size of active listings (square feet)',
                average_listing_price                BIGINT COMMENT 'Mean listing price (USD); outlier-sensitive vs median_listing_price',
                total_listing_count                  BIGINT COMMENT 'Total listings including pending and contingent (active + pending + others)',
                pending_ratio                        DOUBLE COMMENT 'Realtor.com market-velocity metric = pending_listing_count / active_listing_count (higher = faster). Realtor.com re-based this metric in Sep-Nov 2022; values before and after are not directly comparable - flag in multi-year trends.',
                quality_flag                         STRING COMMENT 'Realtor.com data-quality indicator (0 = no issue flagged; nonzero = flagged row)',
                inserted_ts                          TIMESTAMP,
                updated_ts                           TIMESTAMP,
                CONSTRAINT pk_fact_realtor PRIMARY KEY (geo_key, date_key)
            )
        """),
        (f"{gold_schema}.fact_fhfa_metro_quarterly", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.fact_fhfa_metro_quarterly (
                geo_key                        BIGINT NOT NULL,
                date_key                       INT NOT NULL,     -- quarter-end
                home_price_index               DOUBLE COMMENT 'Home Price Index (1995-Q1 = 100): rebased all-transactions repeat-sales house-price index, not seasonally adjusted; 100 = the reference quarter''s price level (e.g. 293 = ~2.93x reference-quarter prices).',
                home_price_index_std_error     DOUBLE COMMENT 'Home Price Index - Std. Error: standard error of the index estimate, in index points.',
                home_price_index_pct_change_yoy DOUBLE COMMENT 'Home Price Appreciation YoY (%): year-over-year percent change in home_price_index vs the same quarter one year prior (date-aware join; null where the prior-year quarter is absent). Populated by the Gold build (G2).',
                inserted_ts                    TIMESTAMP,
                updated_ts                     TIMESTAMP,
                CONSTRAINT pk_fact_fhfa PRIMARY KEY (geo_key, date_key)
            )
        """),
        (f"{gold_schema}.fact_fred_national_monthly", f"""
            CREATE TABLE IF NOT EXISTS {gold_schema}.fact_fred_national_monthly (
                date_key                          INT NOT NULL,
                mortgage_rate_30yr_pct            DOUBLE COMMENT '30-Yr Fixed Mortgage Rate (%): average US 30-year fixed mortgage rate (FRED MORTGAGE30US); percent, weekly.',
                mortgage_rate_15yr_pct            DOUBLE COMMENT '15-Yr Fixed Mortgage Rate (%): average US 15-year fixed mortgage rate (FRED MORTGAGE15US); percent, weekly.',
                housing_affordability_index       DOUBLE COMMENT 'Housing Affordability Index: fixed-rate housing affordability index (FRED FIXHAI); monthly; higher = more affordable.',
                median_sales_price_usd            DOUBLE COMMENT 'Median Sales Price ($US): median sales price of houses sold in the US (FRED MSPUS); quarterly.',
                unemployment_rate_pct             DOUBLE COMMENT 'Unemployment Rate (%): US unemployment rate (FRED UNRATE); monthly.',
                real_median_household_income_usd  DOUBLE COMMENT 'Real Median Household Income (2022 $): inflation-adjusted US median household income (FRED MEHOINUSA672N); annual.',
                active_listing_count              DOUBLE COMMENT 'Active Listing Count: Realtor.com US active for-sale listing count (FRED ACTLISCOUUS); monthly.',
                case_shiller_hpi_sa               DOUBLE COMMENT 'Case-Shiller US HPI (Seasonally Adjusted): S&P/Case-Shiller US national home price index, seasonally adjusted (FRED CSUSHPISA); index, monthly.',
                case_shiller_hpi_nsa              DOUBLE COMMENT 'Case-Shiller US HPI (Non Seasonally Adjusted): S&P/Case-Shiller US national home price index, raw/unadjusted (FRED CSUSHPINSA); index, monthly.',
                cpi_all_urban_sa                  DOUBLE COMMENT 'CPI - All Urban (Seasonally Adjusted): Consumer Price Index for all urban consumers, SA (FRED CPIAUCSL); the deflator for real-dollar analysis.',
                inserted_ts                       TIMESTAMP,
                updated_ts                        TIMESTAMP,
                CONSTRAINT pk_fact_fred_national PRIMARY KEY (date_key)
            )
        """),
    ]
    result = _run_ddl(spark, statements)
    if result["status"] != "succeeded":
        return result

    # Wire the informational FK constraints (separate guarded pass — parents must exist first).
    fk_result = _add_gold_foreign_keys(spark, gold_schema)
    if fk_result["status"] != "succeeded":
        return fk_result
    if fk_result["objects_created"]:
        result["message"] += f" Foreign keys: added {', '.join(fk_result['objects_created'])}."
    return result
