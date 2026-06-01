# ddl/silver_ddl.py
# Silver-layer table DDL. create_silver_tables creates ALL Silver tables (idempotent,
# CREATE IF NOT EXISTS) so the loaders have their targets. Standalone — imports the shared
# _run_ddl from ddl._utils (same contract as audit_ddl / bronze_ddl). Design + decisions:
# _dev_planning/bronze_silver_pipeline_overview.md (reconciled 2026-05-31).
#
# Two conformed dims + six per-source facts + one consolidated quarantine:
#   dim_geo                       grain = CBSA. Universe seeded from the OMB/Census CBSA
#                                 delineation. geo_key is GENERATED ALWAYS AS IDENTITY, so
#                                 seeders use INSERT INTO ... SELECT and never supply it.
#   dim_date                      grain = day (period-end). date_key is a deterministic
#                                 yyyymmdd INT (NOT identity) — seeders compute it.
#   fact_zillow_metro_monthly     3 Bronze feeds (zhvi/zori/inventory) outer-joined on
#                                 (geo, month). Zillow joins to dim_geo via zillow_region_id.
#   fact_realtor_metro_monthly    15 base metrics cast from STRING; _mm/_yy companions dropped
#                                 (Gold recomputes). Joins dim_geo directly on cbsa_code.
#   fact_fhfa_hpi_metro_quarterly canonical variant = traditional/all-transactions (1975+,
#                                 NSA-only -> index_sa is omitted; standard_error kept).
#                                 Joins dim_geo directly on place_id == cbsa_code.
#   dim_fred_series                    FRED series metadata (label/units/frequency); natural key
#                                 series_id. Drives the Gold cadence-reconciliation views.
#   fact_fred_series              NATIONAL, LONG, native cadence — one row per (series_id,
#                                 observation_date). No resample/pivot/forward-fill at Silver:
#                                 keeping it long means no grain-mixing in the fact. The wide
#                                 monthly forward-filled view is a GOLD serving concern (per the
#                                 overview's "cadence reconciliation is a Gold concern").
#   fact_fema_hazard_cbsa         grain = CBSA, geo-keyed, NO date (static hazard characteristic).
#                                 FEMA NRI counties rolled up via the county->CBSA bridge: dollars/
#                                 population SUM, risk scores population-weighted mean. Joins dim_geo
#                                 on cbsa_code. Scores-only (ratings dropped).
#   fact_noaa_climate_cbsa        grain = CBSA, geo-keyed, NO date (static climate characteristic).
#                                 NOAA Climate Normals stations rolled up via the station->CBSA
#                                 crosswalk: mean-of-stations per measure. Joins dim_geo on cbsa_code.
#   quarantine                    one consolidated table (source_system discriminator) for
#                                 rows that fail cast or geo lookup; raw_payload = to_json of
#                                 the offending Bronze row, so nothing is silently dropped.
#
# Value columns carry COLUMN COMMENTs (surfaced in Catalog Explorer / DESCRIBE / BI tools);
# wording derived from _dev_planning/datasource_descriptions/*_README.md. Surrogate keys and
# inserted_ts/updated_ts audit columns are left uncommented (self-evident).
# Audit columns: dims + facts carry inserted_ts + updated_ts (Silver, per CLAUDE.md §11.3).
# PRIMARY KEY constraints document the grain (UC informational, not enforced).

from ddl._utils import _run_ddl, _ok, _fail

# Columns added to dim_geo after its initial release (the conformed geography for the weather
# Silver/Gold tier). Each is (name, type, comment); MUST mirror the dim_geo CREATE TABLE
# definition below so fresh and migrated catalogs converge. Applied by _migrate_dim_geo.
_DIM_GEO_ADDED_COLUMNS = [
    ("census_region", "STRING",
     "US Census region (Northeast/Midwest/South/West) derived from primary_state; null for "
     "territories outside the four Census regions (e.g. PR)"),
    ("cbsa_population", "BIGINT",
     "Total CBSA population (sum of FEMA NRI county population over the CBSA); shared weight "
     "for population-weighted State/Region rollups"),
]


def _migrate_dim_geo(spark, silver_schema):
    """Idempotently add the post-release dim_geo columns to an existing table.

    CREATE IF NOT EXISTS is a no-op on an existing table, so it never alters one — a catalog
    provisioned before these columns existed needs an explicit ALTER. Guarded by column
    presence, so it is a no-op on fresh catalogs (which get the columns from CREATE TABLE)
    and safe to re-run.
    """
    table = f"{silver_schema}.dim_geo"
    try:
        existing = {field.name for field in spark.table(table).schema}
        added = []
        for name, col_type, comment in _DIM_GEO_ADDED_COLUMNS:
            if name not in existing:
                escaped = comment.replace("'", "''")
                spark.sql(f"ALTER TABLE {table} ADD COLUMN {name} {col_type} COMMENT '{escaped}'")
                added.append(name)
        return _ok(f"dim_geo migration ok ({len(added)} column(s) added).", added)
    except Exception as e:
        return _fail("dim_geo migration failed.", e)


def create_silver_tables(spark, silver_schema):
    statements = [
        # ---- Conformed dimensions (created before facts) --------------------------------
        (f"{silver_schema}.dim_geo", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_geo (
                geo_key            BIGINT GENERATED ALWAYS AS IDENTITY,
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
        (f"{silver_schema}.dim_date", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_date (
                date_key           INT NOT NULL COMMENT 'Deterministic yyyymmdd surrogate key (equals full_date as yyyymmdd)',
                full_date          DATE NOT NULL COMMENT 'Calendar date this row represents (always a month-end)',
                year               INT COMMENT 'Calendar year',
                quarter            INT COMMENT 'Calendar quarter (1 to 4)',
                month              INT COMMENT 'Calendar month (1 to 12)',
                month_start        DATE COMMENT 'First day of the month',
                quarter_start      DATE COMMENT 'First day of the quarter',
                is_month_end       BOOLEAN COMMENT 'True if full_date is the last day of its month (always true at this grain)',
                is_quarter_end     BOOLEAN COMMENT 'True if full_date is a quarter-end (Mar/Jun/Sep/Dec)',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_dim_date PRIMARY KEY (date_key)
            )
        """),
        (f"{silver_schema}.dim_fred_series", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.dim_fred_series (
                series_id      STRING NOT NULL COMMENT 'FRED series code, e.g. MORTGAGE30US (natural key; fact_fred_series joins on it)',
                series_label   STRING COMMENT 'Human-readable FRED series title',
                units          STRING COMMENT 'Native units: Percent / Index / USD / 2022 USD / Count',
                frequency      STRING COMMENT 'Native cadence: weekly / monthly / quarterly / annual — drives the Gold cadence-reconciliation views',
                inserted_ts    TIMESTAMP,
                updated_ts     TIMESTAMP,
                CONSTRAINT pk_dim_fred_series PRIMARY KEY (series_id)
            )
        """),
        # ---- Per-source fact tables -----------------------------------------------------
        (f"{silver_schema}.fact_zillow_metro_monthly", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.fact_zillow_metro_monthly (
                geo_key            BIGINT NOT NULL,
                date_key           INT NOT NULL,
                typical_home_value BIGINT COMMENT 'Zillow smoothed mid-tier home value (35th–65th percentile)',
                typical_rent       BIGINT COMMENT 'Zillow smoothed asking rent across SFR + condo + multifamily',
                inventory_active   BIGINT COMMENT 'Zillow count of active for-sale listings observed in the metro that month',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_fact_zillow PRIMARY KEY (geo_key, date_key)
            )
        """),
        (f"{silver_schema}.fact_realtor_metro_monthly", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.fact_realtor_metro_monthly (
                geo_key                              BIGINT NOT NULL,
                date_key                             INT NOT NULL,
                median_listing_price                 BIGINT COMMENT 'Median asking price (USD) of active for-sale listings in the metro that month (asking, not sale)',
                active_listing_count                 BIGINT COMMENT 'Count of homes actively listed for sale (excludes pending, under-contract, off-market)',
                median_days_on_market                DOUBLE COMMENT 'Median days active listings have been on market at month-end (lower = hotter market)',
                new_listing_count                    BIGINT COMMENT 'Count of listings newly added during the month (flow, not snapshot)',
                price_increased_count                BIGINT COMMENT 'Count of active listings whose price was increased during the month',
                price_increased_share                DOUBLE COMMENT 'Share of active listings with a price increase, decimal fraction (0.0049 = 0.49%)',
                price_reduced_count                  BIGINT COMMENT 'Count of active listings whose price was reduced during the month',
                price_reduced_share                  DOUBLE COMMENT 'Share of active listings with a price reduction, decimal fraction',
                pending_listing_count                BIGINT COMMENT 'Count of listings under contract at month-end (offer-accepted, not yet closed)',
                median_listing_price_per_square_foot BIGINT COMMENT 'Median listing price per square foot (USD per sq ft)',
                median_square_feet                   BIGINT COMMENT 'Median home size of active listings (square feet)',
                average_listing_price                BIGINT COMMENT 'Mean listing price (USD); outlier-sensitive vs median_listing_price',
                total_listing_count                  BIGINT COMMENT 'Total listings including pending and contingent (active + pending + others)',
                pending_ratio                        DOUBLE COMMENT 'Realtor.com market-velocity metric = pending_listing_count / active_listing_count (higher = faster)',
                quality_flag                         STRING COMMENT 'Realtor.com data-quality indicator (0 = no issue flagged; nonzero = flagged row)',
                inserted_ts                          TIMESTAMP,
                updated_ts                           TIMESTAMP,
                CONSTRAINT pk_fact_realtor PRIMARY KEY (geo_key, date_key)
            )
        """),
        (f"{silver_schema}.fact_fhfa_hpi_metro_quarterly", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.fact_fhfa_hpi_metro_quarterly (
                geo_key            BIGINT NOT NULL,
                date_key           INT NOT NULL,     -- quarter-end
                index_nsa          DOUBLE COMMENT 'FHFA traditional all-transactions house price index, not seasonally adjusted (unitless, rebased x100)',
                standard_error     DOUBLE COMMENT 'Standard error of the NSA index estimate, in index points (~95% CI = index +/- 1.96*SE)',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_fact_fhfa PRIMARY KEY (geo_key, date_key)
            )
        """),
        (f"{silver_schema}.fact_fred_series", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.fact_fred_series (
                series_id          STRING NOT NULL COMMENT 'FRED series code (FK -> dim_fred_series); national macro indicator',
                observation_date   DATE NOT NULL COMMENT 'Native observation date as published by FRED (NOT normalized to month-end — weekly/quarterly/annual kept native)',
                value              DOUBLE COMMENT 'Observed value in the series native units (see dim_fred_series.units); dollar series keep cents here, Gold rounds when serving',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_fact_fred_series PRIMARY KEY (series_id, observation_date)
            )
        """),
        # ---- Weather/hazard facts (CBSA grain, geo-keyed, NO date — static characteristics) ----
        (f"{silver_schema}.fact_fema_hazard_cbsa", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.fact_fema_hazard_cbsa (
                geo_key            BIGINT NOT NULL,
                population         BIGINT COMMENT 'Resident population of the CBSA (SUM of FEMA NRI county population); also the weight behind the intensive scores in this row',
                eal_valt           BIGINT COMMENT 'Expected Annual Loss, total, in US dollars (SUM of county EAL across all hazards/consequence types)',
                risk_score         DOUBLE COMMENT 'Composite National Risk Index score, 0 to 100 (population-weighted mean of county scores)',
                sovi_score         DOUBLE COMMENT 'Social Vulnerability score, 0 to 100 (population-weighted mean; CDC/ATSDR SVI-derived)',
                resl_score         DOUBLE COMMENT 'Community Resilience score, 0 to 100 (population-weighted mean; BRIC-derived)',
                hrcn_risks         DOUBLE COMMENT 'Hurricane Risk Index score, 0 to 100 (population-weighted mean)',
                cfld_risks         DOUBLE COMMENT 'Coastal Flooding Risk Index score, 0 to 100 (population-weighted mean)',
                ifld_risks         DOUBLE COMMENT 'Inland Flooding Risk Index score, 0 to 100 (population-weighted mean)',
                trnd_risks         DOUBLE COMMENT 'Tornado Risk Index score, 0 to 100 (population-weighted mean)',
                wfir_risks         DOUBLE COMMENT 'Wildfire Risk Index score, 0 to 100 (population-weighted mean)',
                erqk_risks         DOUBLE COMMENT 'Earthquake Risk Index score, 0 to 100 (population-weighted mean)',
                hail_risks         DOUBLE COMMENT 'Hail Risk Index score, 0 to 100 (population-weighted mean)',
                swnd_risks         DOUBLE COMMENT 'Strong Wind Risk Index score, 0 to 100 (population-weighted mean)',
                hwav_risks         DOUBLE COMMENT 'Heat Wave Risk Index score, 0 to 100 (population-weighted mean)',
                wntw_risks         DOUBLE COMMENT 'Winter Weather Risk Index score, 0 to 100 (population-weighted mean)',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_fact_fema_hazard PRIMARY KEY (geo_key)
            )
        """),
        (f"{silver_schema}.fact_noaa_climate_cbsa", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.fact_noaa_climate_cbsa (
                geo_key            BIGINT NOT NULL,
                ann_tavg_normal    DOUBLE COMMENT 'Annual average temperature normal, Fahrenheit (mean across CBSA stations, 1991-2020)',
                djf_tavg_normal    DOUBLE COMMENT 'Winter (Dec-Feb) average temperature normal, Fahrenheit (mean-of-stations)',
                mam_tavg_normal    DOUBLE COMMENT 'Spring (Mar-May) average temperature normal, Fahrenheit (mean-of-stations)',
                jja_tavg_normal    DOUBLE COMMENT 'Summer (Jun-Aug) average temperature normal, Fahrenheit (mean-of-stations)',
                son_tavg_normal    DOUBLE COMMENT 'Autumn (Sep-Nov) average temperature normal, Fahrenheit (mean-of-stations)',
                ann_tmax_normal    DOUBLE COMMENT 'Annual average daily maximum temperature normal, Fahrenheit (mean-of-stations)',
                ann_tmin_normal    DOUBLE COMMENT 'Annual average daily minimum temperature normal, Fahrenheit (mean-of-stations)',
                jja_tmax_normal    DOUBLE COMMENT 'Summer average daily maximum temperature normal, Fahrenheit — the avg summer high (mean-of-stations)',
                djf_tmin_normal    DOUBLE COMMENT 'Winter average daily minimum temperature normal, Fahrenheit — the avg winter low (mean-of-stations)',
                ann_prcp_normal    DOUBLE COMMENT 'Annual precipitation normal, inches (mean-of-stations)',
                ann_snow_normal    DOUBLE COMMENT 'Annual snowfall normal, inches (mean-of-stations)',
                ann_htdd_normal    DOUBLE COMMENT 'Annual heating degree days normal, Fahrenheit degree-days base 65F (mean-of-stations)',
                ann_cldd_normal    DOUBLE COMMENT 'Annual cooling degree days normal, Fahrenheit degree-days base 65F (mean-of-stations)',
                inserted_ts        TIMESTAMP,
                updated_ts         TIMESTAMP,
                CONSTRAINT pk_fact_noaa_climate PRIMARY KEY (geo_key)
            )
        """),
        # ---- Quarantine (consolidated; source_system discriminator) ---------------------
        (f"{silver_schema}.quarantine", f"""
            CREATE TABLE IF NOT EXISTS {silver_schema}.quarantine (
                quarantine_id      STRING NOT NULL,
                source_system      STRING NOT NULL,  -- 'zillow' / 'realtor' / 'fhfa' / 'fred' / 'fema_nri' / 'climate_normals'
                source_file_path   STRING,
                natural_key        STRING,           -- human-readable key of the offending row
                raw_payload        STRING,           -- to_json(struct(*)) of the Bronze row
                quarantine_reason  STRING NOT NULL,  -- 'cast_failed:<col>' / 'unmatched_geography' / 'null_value'
                quarantined_ts     TIMESTAMP NOT NULL
            )
        """),
    ]
    result = _run_ddl(spark, statements)
    if result["status"] != "succeeded":
        return result

    # Back-fill the post-release dim_geo columns onto any pre-existing table (idempotent).
    migrated = _migrate_dim_geo(spark, silver_schema)
    if migrated["status"] != "succeeded":
        return migrated
    if migrated["objects_created"]:
        result["message"] += f" dim_geo migration: added {', '.join(migrated['objects_created'])}."
    return result
