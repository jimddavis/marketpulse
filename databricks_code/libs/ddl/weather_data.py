# ddl/weather_data.py
# Bronze-layer table DDL for the ANNUAL weather/hazard sources: FEMA National Risk Index
# and NOAA Climate Normals. Kept in a separate module (not bronze_ddl.py, which holds the
# monthly sources) per request. Same contract as bronze_ddl: standalone, imports the shared
# _run_ddl, idempotent CREATE IF NOT EXISTS, all-STRING source fidelity (cast at Silver,
# CLAUDE.md §11.1), audit columns source_file_path / inserted_ts / run_id (§11.3). Unlike
# bronze_ddl, every column carries a COMMENT (units + meaning) — surfaced in Catalog
# Explorer / DESCRIBE — because these wide tables use terse source abbreviations.
#
# Two tables, one per source grain:
#   bronze.fema_nri_counties        <- raw.fema_nri/nri_counties.csv                 (county grain)
#   bronze.climate_normals_stations <- raw.climate_normals/_processed/normals_stations/ (station grain)
#
# Both sources are annual single-vintage snapshots, so the loaders MERGE on the natural key
# (stcofips / station) with UPDATE SET * / INSERT — a refresh updates rows in place.
#
# COLUMN SCOPE (the project's "Selected columns for ingestion" — see the _local_downloads/*/
# README.md and weather_sources_download_design.md):
#   - fema_nri_counties: the curated 29 columns — 4 identity + 5 composite + 10 hazards x
#     {risk score, risk rating}. The full 467-col CSV (loss-model internals + ArcGIS
#     OBJECTID/Shape__* artifacts) is preserved in the Volume; carrying all 467 would be an
#     unmaintainable anti-pattern with no analytical value. Source UPPER_SNAKE names lowercased.
#   - climate_normals_stations: 18 columns — 5 identity + 13 measure NORMAL values. The
#     comp_flag_/years_ QC companions were DROPPED: they have no reporting use in this
#     real-estate app and get averaged away at the station->CBSA rollup; they remain in the
#     _processed dataset (and raw tarball) if a station-level QC pass is ever wanted. Source
#     measure names carry hyphens (ANN-TAVG-NORMAL) -> renamed to underscores (ann_tavg_normal).
#
# Hazard prefixes (NRI): hrcn=hurricane cfld=coastal-flood ifld=inland-flood trnd=tornado
# wfir=wildfire erqk=earthquake hail=hail swnd=strong-wind hwav=heat-wave wntw=winter-weather.

from ddl._utils import _run_ddl


def create_weather_bronze_tables(spark, bronze_schema):
    statements = [
        # --- FEMA NRI: county grain, all STRING. MERGE key = stcofips (one row/county). ---
        (f"{bronze_schema}.fema_nri_counties", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.fema_nri_counties (
                stcofips             STRING    COMMENT '5-digit county FIPS (STATEFIPS+COUNTYFIPS); join key to dim_geo and the county-to-CBSA bridge',
                county               STRING    COMMENT 'County or county-equivalent name',
                stateabbrv           STRING    COMMENT '2-letter state/territory postal abbreviation',
                population           STRING    COMMENT 'Resident population; denominator for NRI rates and the population-weighted CBSA rollup',
                risk_score           STRING    COMMENT 'Composite National Risk Index score, 0 to 100 (national percentile across US counties)',
                risk_ratng           STRING    COMMENT 'Composite National Risk Index rating (Very Low to Very High)',
                eal_valt             STRING    COMMENT 'Expected Annual Loss, total, in US dollars (all hazards, all consequence types)',
                sovi_ratng           STRING    COMMENT 'Social Vulnerability rating (CDC/ATSDR SVI-derived)',
                resl_ratng           STRING    COMMENT 'Community Resilience rating (BRIC-derived)',
                hrcn_risks           STRING    COMMENT 'Hurricane - Risk Index score, 0 to 100',
                hrcn_riskr           STRING    COMMENT 'Hurricane - Risk Index rating (Very Low to Very High)',
                cfld_risks           STRING    COMMENT 'Coastal Flooding - Risk Index score, 0 to 100',
                cfld_riskr           STRING    COMMENT 'Coastal Flooding - Risk Index rating (Very Low to Very High)',
                ifld_risks           STRING    COMMENT 'Inland Flooding - Risk Index score, 0 to 100',
                ifld_riskr           STRING    COMMENT 'Inland Flooding - Risk Index rating (Very Low to Very High)',
                trnd_risks           STRING    COMMENT 'Tornado - Risk Index score, 0 to 100',
                trnd_riskr           STRING    COMMENT 'Tornado - Risk Index rating (Very Low to Very High)',
                wfir_risks           STRING    COMMENT 'Wildfire - Risk Index score, 0 to 100',
                wfir_riskr           STRING    COMMENT 'Wildfire - Risk Index rating (Very Low to Very High)',
                erqk_risks           STRING    COMMENT 'Earthquake - Risk Index score, 0 to 100',
                erqk_riskr           STRING    COMMENT 'Earthquake - Risk Index rating (Very Low to Very High)',
                hail_risks           STRING    COMMENT 'Hail - Risk Index score, 0 to 100',
                hail_riskr           STRING    COMMENT 'Hail - Risk Index rating (Very Low to Very High)',
                swnd_risks           STRING    COMMENT 'Strong Wind - Risk Index score, 0 to 100',
                swnd_riskr           STRING    COMMENT 'Strong Wind - Risk Index rating (Very Low to Very High)',
                hwav_risks           STRING    COMMENT 'Heat Wave - Risk Index score, 0 to 100',
                hwav_riskr           STRING    COMMENT 'Heat Wave - Risk Index rating (Very Low to Very High)',
                wntw_risks           STRING    COMMENT 'Winter Weather - Risk Index score, 0 to 100',
                wntw_riskr           STRING    COMMENT 'Winter Weather - Risk Index rating (Very Low to Very High)',
                source_file_path     STRING    COMMENT 'Audit: source file path the row was read from',
                inserted_ts          TIMESTAMP COMMENT 'Audit: load timestamp',
                run_id               STRING    COMMENT 'Audit: pipeline run id'
            )
        """),
        # --- NOAA Climate Normals: station grain, all STRING. MERGE key = station. ---
        # Source measure names had hyphens (ANN-TAVG-NORMAL) -> underscores here. Units:
        # temperatures Fahrenheit, precip/snow inches, degree days Fahrenheit degree-days.
        (f"{bronze_schema}.climate_normals_stations", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.climate_normals_stations (
                station              STRING    COMMENT 'GHCN station id (the grain key)',
                latitude             STRING    COMMENT 'Station latitude, decimal degrees (input to station-to-county mapping)',
                longitude            STRING    COMMENT 'Station longitude, decimal degrees',
                elevation            STRING    COMMENT 'Station elevation, meters (source value is space-padded)',
                name                 STRING    COMMENT 'Station name plus state/country',
                ann_tavg_normal      STRING    COMMENT 'Annual average temperature normal, Fahrenheit (1991-2020)',
                djf_tavg_normal      STRING    COMMENT 'Winter (Dec-Feb) average temperature normal, Fahrenheit',
                mam_tavg_normal      STRING    COMMENT 'Spring (Mar-May) average temperature normal, Fahrenheit',
                jja_tavg_normal      STRING    COMMENT 'Summer (Jun-Aug) average temperature normal, Fahrenheit',
                son_tavg_normal      STRING    COMMENT 'Autumn (Sep-Nov) average temperature normal, Fahrenheit',
                ann_tmax_normal      STRING    COMMENT 'Annual average daily maximum temperature normal, Fahrenheit',
                ann_tmin_normal      STRING    COMMENT 'Annual average daily minimum temperature normal, Fahrenheit',
                jja_tmax_normal      STRING    COMMENT 'Summer average daily maximum temperature normal, Fahrenheit (the avg summer high)',
                djf_tmin_normal      STRING    COMMENT 'Winter average daily minimum temperature normal, Fahrenheit (the avg winter low)',
                ann_prcp_normal      STRING    COMMENT 'Annual precipitation normal, inches',
                ann_snow_normal      STRING    COMMENT 'Annual snowfall normal, inches',
                ann_htdd_normal      STRING    COMMENT 'Annual heating degree days normal, Fahrenheit degree-days (base 65F)',
                ann_cldd_normal      STRING    COMMENT 'Annual cooling degree days normal, Fahrenheit degree-days (base 65F)',
                source_file_path     STRING    COMMENT 'Audit: source file path the row was read from',
                inserted_ts          TIMESTAMP COMMENT 'Audit: load timestamp',
                run_id               STRING    COMMENT 'Audit: pipeline run id'
            )
        """),
    ]
    return _run_ddl(spark, statements)
