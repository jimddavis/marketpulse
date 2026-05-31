# ddl/bronze_ddl.py
# Bronze-layer table DDL. create_bronze_tables creates ALL Bronze tables (idempotent,
# CREATE IF NOT EXISTS) so the layer's loaders have their targets even before a first
# write. Standalone — imports the shared _run_ddl from ddl._utils (same contract as
# audit_ddl). Six tables, one per source schema-shape (NOT one per file — FRED's 10
# series and Realtor's snapshot+history each collapse to a single table; see
# _dev_planning/bronze_silver_pipeline_overview.md).
#
# Typing:
#   - Zillow loads from the wide->long Parquet (raw/zillow/_long/), which is already
#     typed: period_date DATE, value DOUBLE. This is the documented exception to the
#     bronze-all-STRING rule (CLAUDE.md §11.1). The Parquet keeps source CamelCase id
#     names; the loader aliases them to the snake_case columns below.
#   - FHFA / Realtor / FRED load from CSV as all-STRING — source fidelity, cast at Silver.
#
# Audit columns on every table: source_file_path, inserted_ts, run_id (CLAUDE.md §11.3).
# series_id (FRED) and source_file_path (Zillow) are injected by the loader from the
# manifest / ZILLOW_FEEDS — they are not present in the file bytes.

from ddl._utils import _run_ddl


def create_bronze_tables(spark, bronze_schema):
    statements = [
        # --- Zillow: 3 typed long tables (read from raw/zillow/_long/ Parquet). ---
        # MERGE key (region_id, period_date); single `value` payload -> UPDATE SET *.
        (f"{bronze_schema}.zillow_zhvi", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.zillow_zhvi (
                region_id            STRING,
                size_rank            STRING,
                region_name          STRING,
                region_type          STRING,
                state_name           STRING,
                period_date          DATE,
                value                DOUBLE,
                source_file_path     STRING,
                inserted_ts          TIMESTAMP,
                run_id               STRING
            )
        """),
        (f"{bronze_schema}.zillow_zori", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.zillow_zori (
                region_id            STRING,
                size_rank            STRING,
                region_name          STRING,
                region_type          STRING,
                state_name           STRING,
                period_date          DATE,
                value                DOUBLE,
                source_file_path     STRING,
                inserted_ts          TIMESTAMP,
                run_id               STRING
            )
        """),
        (f"{bronze_schema}.zillow_inventory", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.zillow_inventory (
                region_id            STRING,
                size_rank            STRING,
                region_name          STRING,
                region_type          STRING,
                state_name           STRING,
                period_date          DATE,
                value                DOUBLE,
                source_file_path     STRING,
                inserted_ts          TIMESTAMP,
                run_id               STRING
            )
        """),
        # --- FHFA: master CSV only (the two xlsx are verified subsets). All STRING. ---
        # MERGE key (hpi_type, hpi_flavor, frequency, level, place_id, yr, period) — the
        # full grain, because master mixes monthly+quarterly and multiple flavors.
        (f"{bronze_schema}.fhfa_hpi_master", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.fhfa_hpi_master (
                hpi_type             STRING,
                hpi_flavor           STRING,
                frequency            STRING,
                level                STRING,
                place_name           STRING,
                place_id             STRING,
                yr                   STRING,
                period               STRING,
                index_nsa            STRING,
                index_sa             STRING,
                rstderr              STRING,
                note                 STRING,
                source_file_path     STRING,
                inserted_ts          TIMESTAMP,
                run_id               STRING
            )
        """),
        # --- Realtor: snapshot + history into one table (same 47-col schema). All STRING. ---
        # MERGE key (cbsa_code, month_date_yyyymm) + row_hash guard — collapses the
        # snapshot's latest month onto the history row. HouseholdRank -> household_rank.
        (f"{bronze_schema}.realtor_metro_monthly", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.realtor_metro_monthly (
                month_date_yyyymm                       STRING,
                cbsa_code                               STRING,
                cbsa_title                              STRING,
                household_rank                          STRING,
                median_listing_price                    STRING,
                median_listing_price_mm                 STRING,
                median_listing_price_yy                 STRING,
                active_listing_count                    STRING,
                active_listing_count_mm                 STRING,
                active_listing_count_yy                 STRING,
                median_days_on_market                   STRING,
                median_days_on_market_mm                STRING,
                median_days_on_market_yy                STRING,
                new_listing_count                       STRING,
                new_listing_count_mm                    STRING,
                new_listing_count_yy                    STRING,
                price_increased_count                   STRING,
                price_increased_count_mm                STRING,
                price_increased_count_yy                STRING,
                price_increased_share                   STRING,
                price_increased_share_mm                STRING,
                price_increased_share_yy                STRING,
                price_reduced_count                     STRING,
                price_reduced_count_mm                  STRING,
                price_reduced_count_yy                  STRING,
                price_reduced_share                     STRING,
                price_reduced_share_mm                  STRING,
                price_reduced_share_yy                  STRING,
                pending_listing_count                   STRING,
                pending_listing_count_mm                STRING,
                pending_listing_count_yy                STRING,
                median_listing_price_per_square_foot    STRING,
                median_listing_price_per_square_foot_mm STRING,
                median_listing_price_per_square_foot_yy STRING,
                median_square_feet                      STRING,
                median_square_feet_mm                   STRING,
                median_square_feet_yy                   STRING,
                average_listing_price                   STRING,
                average_listing_price_mm                STRING,
                average_listing_price_yy                STRING,
                total_listing_count                     STRING,
                total_listing_count_mm                  STRING,
                total_listing_count_yy                  STRING,
                pending_ratio                           STRING,
                pending_ratio_mm                        STRING,
                pending_ratio_yy                        STRING,
                quality_flag                            STRING,
                row_hash                                STRING,
                source_file_path                        STRING,
                inserted_ts                             TIMESTAMP,
                run_id                                  STRING
            )
        """),
        # --- FRED: 10 series into one table, series_id injected from the manifest. ---
        # All STRING. MERGE key (series_id, observation_date, realtime_start) — realtime_start
        # is in the key to preserve FRED vintages. Source col `date` -> observation_date.
        (f"{bronze_schema}.fred_series_observations", f"""
            CREATE TABLE IF NOT EXISTS {bronze_schema}.fred_series_observations (
                series_id            STRING,
                observation_date     STRING,
                value                STRING,
                realtime_start       STRING,
                realtime_end         STRING,
                source_file_path     STRING,
                inserted_ts          TIMESTAMP,
                run_id               STRING
            )
        """),
    ]
    return _run_ddl(spark, statements)
