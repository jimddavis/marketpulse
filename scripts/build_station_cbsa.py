# /// script
# requires-python = ">=3.12"
# dependencies = ["geopandas", "shapely", "pandas"]
# ///
"""Build the station -> CBSA crosswalk reference data for the climate Silver rollup.

Output (committed CSV under data/crosswalks/):
  station_to_cbsa.csv   NOAA Climate Normals station -> cbsa_code (station, cbsa_code), one
                        row per US station that falls inside a CBSA polygon.

How: point-in-polygon. The NCEI 30-year normals inventory carries each station's lat/lon;
the TIGER CBSA shapefile carries the 935 metro/micro polygons. A spatial join assigns each
station to the CBSA whose polygon contains it. Stations outside every CBSA (rural — much of
the US1 CoCoRaHS network) simply drop out; that is expected, not an error.

This is the spatial half of weather_research.md Appendix A. It runs OFFLINE (never on
Databricks — Sedona-on-serverless is avoided per the Silver/Gold design). The result is
static reference data: stations don't move and the CBSA vintage is frozen, so this is built
once and committed, like the other crosswalks.

Inputs are local, committed files:
  _local_downloads/climate_normals/inventory_30yr.txt   station id, lat, lon, elev, state, name
  _dev_planning/TIGER_2025_cbsa/tl_2025_us_cbsa.shp      935 CBSA polygons (EPSG:4269), CBSAFP

Run:  uv run --script scripts/build_station_cbsa.py
Re-run only when the normals vintage or the CBSA delineation changes (reference data, not
pipeline output).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = REPO_ROOT / "_local_downloads" / "climate_normals" / "inventory_30yr.txt"
CBSA_SHAPEFILE = REPO_ROOT / "_dev_planning" / "TIGER_2025_cbsa" / "tl_2025_us_cbsa.shp"
OUT_DIR = REPO_ROOT / "data" / "crosswalks"

# The inventory mixes US stations with international/GSN ones (2-char field is a US state
# OR a foreign province, e.g. ON = Ontario). Filter to US states + DC to match dim_geo
# coverage; international points would fall outside every US CBSA polygon anyway, but the
# filter keeps the station count aligned with the Bronze table.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}

# TIGER ships in NAD83; reproject station points to match before the join.
TIGER_CRS = 4269   # EPSG:4269 (NAD83), per tl_2025_us_cbsa.prj
WGS84_CRS = 4326   # EPSG:4326 (WGS84) — the datum of GPS lat/lon in the inventory


def load_inventory() -> pd.DataFrame:
    """Parse the fixed-layout inventory into (station, lat, lon, state), US stations only.

    The file is whitespace-delimited with a free-text name that can contain spaces, so split
    on the first 5 tokens only: station, lat, lon, elevation, state. We keep station/lat/lon
    plus state for the US filter; name/elevation are not needed for the spatial join.
    """
    records = []
    with open(INVENTORY, encoding="utf-8") as inventory_file:
        for line in inventory_file:
            parts = line.split(maxsplit=5)
            if len(parts) < 5:
                continue
            station, latitude, longitude, _elevation, state = parts[:5]
            records.append((station, float(latitude), float(longitude), state))

    inventory = pd.DataFrame(records, columns=["station", "latitude", "longitude", "state"])
    us_inventory = inventory[inventory["state"].isin(US_STATES)].reset_index(drop=True)
    print(f"Inventory: {len(inventory)} stations total, {len(us_inventory)} US stations")
    return us_inventory


def assign_cbsa(stations: pd.DataFrame) -> pd.DataFrame:
    """Point-in-polygon each station into its containing CBSA. Returns (station, cbsa_code)
    for stations inside a CBSA; rural stations outside every polygon are dropped."""
    # Build station points in WGS84, then reproject to the shapefile's NAD83 for the join.
    station_points = gpd.GeoDataFrame(
        stations,
        geometry=gpd.points_from_xy(stations["longitude"], stations["latitude"]),
        crs=WGS84_CRS,
    ).to_crs(TIGER_CRS)

    cbsa_polygons = gpd.read_file(CBSA_SHAPEFILE)[["CBSAFP", "geometry"]]

    # Left join keeps every station; CBSAFP is null where a station sits outside all polygons.
    joined = gpd.sjoin(station_points, cbsa_polygons, predicate="within", how="left")

    inside = joined[joined["CBSAFP"].notna()]
    crosswalk = (
        inside[["station", "CBSAFP"]]
        .rename(columns={"CBSAFP": "cbsa_code"})
        .drop_duplicates(subset="station")     # a point can border-touch >1 polygon; keep one
        .sort_values("station")
        .reset_index(drop=True)
    )

    inside_count = len(crosswalk)
    dropped_count = len(stations) - inside_count
    print(f"Inside a CBSA : {inside_count} ({inside_count / len(stations):.1%})")
    print(f"Dropped (rural): {dropped_count} ({dropped_count / len(stations):.1%})")
    return crosswalk


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stations = load_inventory()
    crosswalk = assign_cbsa(stations)
    out_path = OUT_DIR / "station_to_cbsa.csv"
    crosswalk.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(crosswalk)} rows)")


if __name__ == "__main__":
    main()
