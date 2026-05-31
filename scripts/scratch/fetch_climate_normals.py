# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""THROWAWAY probe — basis for a future Climate-Normals provider in data_fetch.

Downloads the NOAA U.S. Climate Normals **1991-2020 Annual/Seasonal** product
(by-station, multivariate) plus its documentation into
``_local_downloads/climate_normals/``.

Mechanism note:
    NCEI ships the whole product as a single consolidated ``.tar.gz`` in ``archive/``
    (avoids fetching ~9,000 per-station CSVs from ``access/`` one by one), plus a
    ``doc/`` folder with the station inventory (lat/lon — the station->county mapping
    input), the by-variable readme, and the documentation/methodology PDFs. This maps
    onto the existing ``http_file`` provider + a local untar step — NOT a new provider
    type. We extract a few sample station CSVs for the README data dictionary.

Run from the repo root:
    uv run --python 3.12 scripts/scratch/fetch_climate_normals.py

Stdlib only (urllib/tarfile).
"""

from __future__ import annotations

import tarfile
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
DEST = _REPO / "_local_downloads" / "climate_normals"

BASE = "https://www.ncei.noaa.gov/data/normals-annualseasonal/1991-2020"
TARBALL = "us-climate-normals_1991-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

FILES = {
    f"{TARBALL}":                                    f"{BASE}/archive/{TARBALL}",
    "inventory_30yr.txt":                            f"{BASE}/doc/inventory_30yr.txt",
    "Readme_By-Variable_By-Station_Normals_Files.txt": f"{BASE}/doc/Readme_By-Variable_By-Station_Normals_Files.txt",
    "Normals_ANN_Documentation_1991-2020.pdf":       f"{BASE}/doc/Normals_ANN_Documentation_1991-2020.pdf",
    "Normals_Calculation_Methodology_2020.pdf":      f"{BASE}/doc/Normals_Calculation_Methodology_2020.pdf",
    "Normals_ANN_1991-2020_sample.csv":              f"{BASE}/doc/Normals_ANN_1991-2020_sample.csv",
}
N_SAMPLE_STATIONS = 3


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as fh:
        fh.write(resp.read())
    print(f"[normals] OK ({dest.stat().st_size:,} bytes): {dest.name}")


def fetch_climate_normals() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        try:
            _download(url, DEST / name)
        except Exception as e:  # noqa: BLE001 — report and continue
            print(f"[normals] SKIP ({name}): {type(e).__name__}: {e}")

    # Extract a few sample station CSVs (not the whole archive) for the data dictionary.
    tar_path = DEST / TARBALL
    if tar_path.exists():
        sample_dir = DEST / "sample_stations"
        sample_dir.mkdir(exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tf:
            members = [m for m in tf.getmembers() if m.name.endswith(".csv")][:N_SAMPLE_STATIONS]
            for m in members:
                data = tf.extractfile(m).read()
                (sample_dir / Path(m.name).name).write_bytes(data)
                print(f"[normals] sample station: {Path(m.name).name} ({len(data):,} bytes)")
        # quick station count for the README
        with tarfile.open(tar_path, "r:gz") as tf:
            n = sum(1 for m in tf.getmembers() if m.name.endswith(".csv"))
        print(f"[normals] archive contains {n:,} station CSV files")


if __name__ == "__main__":
    fetch_climate_normals()
