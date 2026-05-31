"""ArcGisFeatureServiceProvider — paginated ArcGIS Feature Service pull (weather sources).

Pulls every record of an ArcGIS Feature Service layer by paging its `query` endpoint and
assembles the returned attribute rows into a single CSV. Used by FEMA NRI, whose canonical
hazards.fema.gov bulk CSV is unreachable from our environment (TLS block) and which is NOT
exposed on the OpenFEMA API; the FEMA-owned ArcGIS service carries the same attribute table
(see weather_sources_download_design.md §3).

Like FredApiProvider this GENERATES a file rather than streaming bytes: one logical CSV
assembled from N JSON pages. So `resume_from` is ignored (there is no resumable byte
stream) and `content_length` is None. The query is sent with a stable `orderByFields`, so
the row order — and therefore the assembled CSV's sha256 — is identical across runs, which
is what lets the runner's idempotent no-op fire when the source is unchanged (§3.1, §7.6).

Constructed uniformly as `ArcGisFeatureServiceProvider(secrets=..., session=...)` per the
factory contract (§5): it uses `session` (HTTP) and ignores `secrets` — the service is
public, no key. The layer query URL is KEY-FREE, so it is both the request URL and the
logged `canonical_url` (§16.5).
"""

from __future__ import annotations

import csv
import os
from typing import Any

import requests

from data_fetch.constants import HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT
from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError, parse_retry_after

# The service caps a single response at maxRecordCount (2000 for the NRI county layer); we
# page in that size until `exceededTransferLimit` clears.
_PAGE_SIZE = 2000

# Stable sort key so the assembled CSV is byte-identical run to run (→ sha256 no-op fires).
# OBJECTID is the ArcGIS object-id field — present and unique on EVERY Feature Service layer
# (its mandatory primary key) — so ordering by it is both generic (works for any future
# ArcGIS source) and a guaranteed TOTAL order (no ties), which is what the no-op depends on.
_ORDER_BY = "OBJECTID"


class ArcGisFeatureServiceProvider:
    def __init__(self, *, secrets: Any = None, session: requests.Session | None = None):
        # `secrets` accepted for the uniform factory signature; unused (public service, no auth).
        self._session = session if session is not None else requests.Session()

    # -- fetch ---------------------------------------------------------------

    def fetch_to(self, scratch_path: str, spec: SourceSpec, f: SourceFile,
                 *, resume_from: int, ctx: RunContext) -> ProviderFetch:
        query_url = f.url
        if not query_url:
            raise ValueError(
                f"arcgis_feature_service source {spec.name!r} file {f.landed_filename!r} has no url"
            )

        # Page through the layer: each request returns up to _PAGE_SIZE attribute rows plus
        # an `exceededTransferLimit` flag that is True while more rows remain.
        assembled_rows: list[dict[str, Any]] = []
        last_status: int | None = None
        offset = 0
        while True:
            last_status, page = self._request_page(query_url, offset)
            features = page.get("features", [])
            if not features:
                break
            assembled_rows.extend(feature["attributes"] for feature in features)
            if not page.get("exceededTransferLimit", False):
                break
            offset += _PAGE_SIZE

        if not assembled_rows:
            raise ValueError(
                f"arcgis_feature_service source {spec.name!r}: query returned no rows ({query_url})"
            )

        bytes_written = self._write_csv(scratch_path, assembled_rows)
        return ProviderFetch(bytes_written=bytes_written, http_status=last_status,
                             canonical_url=query_url)

    # -- probe ---------------------------------------------------------------

    def canonical_url(self, spec: SourceSpec, f: SourceFile) -> str:
        # The query URL itself — KEY-FREE, no secret to strip. Falls back to a stable
        # identifier for a malformed manifest entry (fetch_to raises on it).
        return f.url or f"{spec.name}/{f.landed_filename}"

    def probe(self, spec: SourceSpec, f: SourceFile) -> ProbeResult:
        query_url = f.url
        if not query_url:
            return ProbeResult(ok=False, detail=f"no url for {f.landed_filename!r}")
        params = {"where": "1=1", "returnCountOnly": "true", "f": "json"}
        timeout = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
        try:
            with self._session.get(query_url, params=params, timeout=timeout) as response:
                status = response.status_code
                if status >= 400:
                    return ProbeResult(ok=False, http_status=status,
                                       detail=f"unexpected status {status}")
                row_count = response.json().get("count")
        except requests.RequestException as e:
            return ProbeResult(ok=False, detail=f"{type(e).__name__}: {e}")

        ok = isinstance(row_count, int) and row_count > 0
        return ProbeResult(ok=ok, http_status=status, content_length=None,
                           detail=None if ok else f"row count {row_count!r}")

    # -- helpers -------------------------------------------------------------

    def _request_page(self, query_url: str, offset: int) -> tuple[int, dict[str, Any]]:
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "false",
            "orderByFields": _ORDER_BY,
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": _PAGE_SIZE,
        }
        timeout = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
        with self._session.get(query_url, params=params, timeout=timeout) as response:
            status = response.status_code
            if status >= 400:
                raise ProviderHttpError(
                    status, query_url,
                    retry_after=parse_retry_after(response.headers.get("Retry-After")),
                )
            return status, response.json()

    @staticmethod
    def _write_csv(scratch_path: str, rows: list[dict[str, Any]]) -> int:
        # Header = the first row's keys, which preserves the service's field order (incl.
        # the OBJECTID / Shape__* ArcGIS artifacts — dropped later at Bronze/Silver, kept
        # here for raw fidelity). All features in a layer share one attribute schema.
        field_names = list(rows[0].keys())
        with open(scratch_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=field_names)
            writer.writeheader()
            writer.writerows(rows)
        return os.path.getsize(scratch_path)
