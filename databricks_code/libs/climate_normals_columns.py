"""Selected Climate Normals columns — single source of truth (CLAUDE.md §6).

The NOAA 1991-2020 Annual/Seasonal by-station files are wide and ragged (508-2,140 columns
per station). Both consumers — the normalize step (process_climate_normals) and the future
climate-normals Bronze loader — select exactly this column set, so it lives in ONE place.
See _local_downloads/climate_normals/README.md "Selected columns for ingestion" and
weather_sources_download_design.md §4.

Each measure also has companion comp_flag_<col> / years_<col> columns in the source; the
normalize step derives those names from MEASURE_COLS rather than listing them here.
"""

from __future__ import annotations

# Station identity / location — the first 5 columns of every station file.
IDENTITY_COLS: tuple[str, ...] = (
    "STATION", "LATITUDE", "LONGITUDE", "ELEVATION", "NAME",
)

# The 13 plain `-NORMAL` measures kept for the climate profile: the seasonal avg-temp curve,
# the annual high/low band, the headline summer-high / winter-low, annual precip / snow, and
# heating/cooling degree days. (The other ~520 source variables — frost probabilities,
# degree-day bases, day-count thresholds, std-devs — are dropped.)
MEASURE_COLS: tuple[str, ...] = (
    "ANN-TAVG-NORMAL", "DJF-TAVG-NORMAL", "MAM-TAVG-NORMAL",
    "JJA-TAVG-NORMAL", "SON-TAVG-NORMAL",
    "ANN-TMAX-NORMAL", "ANN-TMIN-NORMAL",
    "JJA-TMAX-NORMAL", "DJF-TMIN-NORMAL",
    "ANN-PRCP-NORMAL", "ANN-SNOW-NORMAL",
    "ANN-HTDD-NORMAL", "ANN-CLDD-NORMAL",
)
