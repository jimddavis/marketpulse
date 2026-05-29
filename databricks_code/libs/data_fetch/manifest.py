"""Source manifest dataclasses (WS0).

Typed registry types declaring WHAT to download. WS0 defines only the dataclasses;
the populated SOURCES tuple lands in WS-G (design §4, §5, §12).

Adding a source is config-only: append one SourceSpec to SOURCES — no change to
providers, runner, writer, or journal (design §4).
"""

from __future__ import annotations

from dataclasses import dataclass

from data_fetch.constants import BROWSER_UA


@dataclass(frozen=True)
class SourceFile:
    landed_filename: str                               # friendly final name
    url: str | None = None                             # Family A (http_file)
    series_id: str | None = None                       # Family B (fred_api)
    fmt: str = "csv"                                    # "csv" | "xlsx" | "json"
    expected_header: tuple[str, ...] | None = None     # PREFIX-matched, CSV only; None → skip (§7.5)
    note: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    name: str                                          # source_system: zillow|fhfa|realtor|fred
    provider: str                                      # "http_file" | "fred_api" → factory key
    volume: str                                        # raw Volume name; joined onto RAW_FILES base
    files: tuple[SourceFile, ...]
    user_agent: str | None = None                      # Family A
    api_key_env: str | None = None                     # Family B, e.g. "FRED_API_KEY"


# ---------------------------------------------------------------------------
# The manifest (design §10). Adding a source = appending one SourceSpec here —
# no change to providers, runner, writer, or journal. SourceSpec.name ==
# SourceSpec.volume for every source (the writer joins source_system onto the
# RAW_FILES base). Volumes catalog.raw.{name} are provisioned by
# catalog_setup.create_volumes(). Pull ALL available history — no date windowing.
# ---------------------------------------------------------------------------
SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="zillow", provider="http_file", volume="zillow", user_agent=BROWSER_UA,
        files=(
            SourceFile("zhvi_home_values_metro_monthly.csv",
                url="https://files.zillowstatic.com/research/public_csvs/zhvi/"
                    "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
                fmt="csv",
                expected_header=("RegionID", "SizeRank", "RegionName", "RegionType", "StateName"),
                note="wide; ZHVI back to 2000; needs wide_to_long downstream"),
            SourceFile("zori_asking_rents_metro_monthly.csv",
                url="https://files.zillowstatic.com/research/public_csvs/zori/"
                    "Metro_zori_uc_sfrcondomfr_sm_sa_month.csv", fmt="csv",
                expected_header=("RegionID", "SizeRank", "RegionName", "RegionType", "StateName")),
            SourceFile("inventory_for_sale_metro_monthly.csv",
                url="https://files.zillowstatic.com/research/public_csvs/invt_fs/"
                    "Metro_invt_fs_uc_sfrcondo_sm_month.csv", fmt="csv",
                expected_header=("RegionID", "SizeRank", "RegionName", "RegionType", "StateName")),
        ),
    ),
    SourceSpec(
        name="fhfa", provider="http_file", volume="fhfa", user_agent=BROWSER_UA,
        files=(
            SourceFile("hpi_master_all_geographies.csv",
                url="https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv",
                fmt="csv",
                expected_header=("hpi_type", "hpi_flavor", "frequency", "level", "place_name",
                                 "place_id", "yr", "period", "index_nsa", "index_sa")),
            SourceFile("hpi_purchase_only_metro_quarterly.xlsx",
                url="https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_po_metro.xlsx",
                fmt="xlsx", note="opaque bytes; banner/sheet parsing is a Bronze concern"),
            SourceFile("hpi_all_transactions_metro_quarterly.xlsx",
                url="https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.xlsx",
                fmt="xlsx", note="2-row banner; header handled in Bronze, not here"),
        ),
    ),
    SourceSpec(
        name="realtor", provider="http_file", volume="realtor", user_agent=BROWSER_UA,
        files=(
            SourceFile("inventory_core_metrics_metro_snapshot.csv",
                url="https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
                    "RDC_Inventory_Core_Metrics_Metro.csv", fmt="csv"),
            SourceFile("inventory_core_metrics_metro_history.csv",
                url="https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
                    "RDC_Inventory_Core_Metrics_Metro_History.csv", fmt="csv",
                note="full history ~32 MB; Range-resume capable"),
        ),
    ),
    SourceSpec(
        name="fred", provider="fred_api", volume="fred", api_key_env="FRED_API_KEY",
        files=tuple(
            SourceFile(friendly, series_id=sid, fmt="csv",
                       expected_header=("date", "value", "realtime_start", "realtime_end"))
            for sid, friendly in (
                ("MORTGAGE30US",  "mortgage_rate_30yr_fixed_weekly.csv"),
                ("MORTGAGE15US",  "mortgage_rate_15yr_fixed_weekly.csv"),
                ("FIXHAI",        "housing_affordability_index_monthly.csv"),
                ("MSPUS",         "median_sales_price_us_quarterly.csv"),
                ("UNRATE",        "unemployment_rate_national_monthly.csv"),
                ("MEHOINUSA672N", "real_median_household_income_annual.csv"),
                ("ACTLISCOUUS",   "realtor_active_listing_count_us_monthly.csv"),
                ("CSUSHPISA",     "case_shiller_us_national_sa_monthly.csv"),
                ("CSUSHPINSA",    "case_shiller_us_national_nsa_monthly.csv"),
                ("CPIAUCSL",      "cpi_all_urban_sa_monthly.csv"),   # README-recommended addition
            )
        ),
    ),
)
