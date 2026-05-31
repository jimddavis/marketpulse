# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""THROWAWAY probe — basis for a future `arcgis_feature_service` provider in data_fetch.

Downloads the FEMA National Risk Index (NRI) **county** table to
``_local_downloads/nri/nri_counties.csv``.

Why ArcGIS and not the canonical bulk CSV:
    The canonical NRI bulk file lives at
    ``https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/NRI_Table_Counties/``
    which is UNREACHABLE from this environment (TLS handshake dropped — FEMA-side
    WAF/geo/TLS block, sandbox or not). NRI is also NOT exposed on the OpenFEMA API.
    The reachable, FEMA-authoritative substitute is the FEMA-owned ArcGIS Feature
    Service "National Risk Index Counties" — same attribute table (3,232 counties,
    467 fields incl. STCOFIPS county FIPS, RISK_*, EAL_*, SOVI_*, RESL_*, per-hazard
    families). The future production provider can target either host.

Run from the repo root:
    uv run --python 3.12 scripts/scratch/fetch_nri_counties.py

Stdlib only (urllib/json/csv) — no third-party deps, so it lifts cleanly into a
provider later.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
DEST = _REPO / "_local_downloads" / "fema_nri"

# FEMA-owned ArcGIS Feature Service (item 39485e8035d446a5bff03259508ae355).
FS_QUERY = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Counties/FeatureServer/0/query"
)
PAGE = 2000  # service maxRecordCount
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# Best-effort supplementary docs (canonical FEMA host; may be blocked — non-fatal).
DOC_URLS = {
    "NRI_TechnicalDocumentation.pdf":
        "https://www.fema.gov/sites/default/files/documents/fema_national-risk-index_technical-documentation.pdf",
    "NRI_FAQ.pdf":
        "https://www.fema.gov/sites/default/files/documents/fema_national-risk-index_faq-page-documentation.pdf",
}


def _get(url: str, params: dict | None = None) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def fetch_nri_counties() -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / "nri_counties.csv"

    rows: list[dict] = []
    offset = 0
    while True:
        payload = json.loads(_get(FS_QUERY, {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
        }))
        feats = payload.get("features", [])
        if not feats:
            break
        rows.extend(f["attributes"] for f in feats)
        print(f"  [nri] fetched {len(rows):,} rows (offset {offset})")
        if not payload.get("exceededTransferLimit") and len(feats) < PAGE:
            break
        offset += PAGE

    if not rows:
        sys.exit("[nri] ERROR: feature service returned no rows")

    header = list(rows[0].keys())
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    print(f"[nri] wrote {len(rows):,} counties x {len(header)} cols -> {out}")

    for name, url in DOC_URLS.items():
        try:
            (DEST / name).write_bytes(_get(url))
            print(f"[nri] doc OK: {name}")
        except Exception as e:  # noqa: BLE001 — best-effort, non-fatal
            print(f"[nri] doc SKIP ({name}): {type(e).__name__}: {e}")
    return out


if __name__ == "__main__":
    fetch_nri_counties()
