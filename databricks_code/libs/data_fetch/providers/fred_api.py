"""FredApiProvider — Family-B JSON API with key (WS-B).

Pulls the FULL history of a FRED series (no `observation_start`) and writes the
canonical 4-column CSV `date,value,realtime_start,realtime_end`. A single call
suffices — even the largest in-scope series (~2,877 rows) is far below FRED's 100000
default `limit`, so no pagination (design §5; fred_README Phase 2a).

Key handling: the API key is obtained from the injected SecretResolver (keyed by
`spec.api_key_env`) — never `os.environ` (§16.5, §8.1). The logged `canonical_url`
carries `series_id` only; the `api_key` is never placed in any logged or raised string
(§16.5). Bronze fidelity: `value` is written verbatim, including the "." missing
sentinel — no casting here (design §5, §11.1).

Constructed uniformly as `FredApiProvider(secrets=..., session=...)` per the factory
contract (design §5): it uses both `secrets` (for the key) and `session` (HTTP).
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

_FRED_BASE = "https://api.stlouisfed.org/fred"
_OBS_COLUMNS = ("date", "value", "realtime_start", "realtime_end")


class FredApiProvider:
    def __init__(self, *, secrets: Any = None, session: requests.Session | None = None):
        self._secrets = secrets
        self._session = session if session is not None else requests.Session()

    # -- fetch ---------------------------------------------------------------

    def fetch_to(self, scratch_path: str, spec: SourceSpec, f: SourceFile,
                 *, resume_from: int, ctx: RunContext) -> ProviderFetch:
        if not f.series_id:
            raise ValueError(
                f"fred_api source {spec.name!r} file {f.landed_filename!r} has no series_id"
            )
        key = self._api_key(spec)
        # Full history → no observation_start (design §5). `resume_from` is ignored:
        # the API yields a single JSON document, not a resumable byte stream.
        _, payload = self._request_json(
            f"{_FRED_BASE}/series/observations",
            params={"series_id": f.series_id, "api_key": key, "file_type": "json"},
        )
        bytes_written = self._write_csv(scratch_path, payload.get("observations", []))
        return ProviderFetch(
            bytes_written=bytes_written,
            http_status=None,                       # FRED JSON path → null http_status_code (design §5, §9)
            canonical_url=self._canonical_url(f.series_id),
        )

    # -- probe ---------------------------------------------------------------

    def canonical_url(self, spec: SourceSpec, f: SourceFile) -> str:
        # KEY-FREE observations endpoint (series_id only) — same value fetch_to stamps.
        if f.series_id:
            return self._canonical_url(f.series_id)
        return f"{spec.name}/{f.landed_filename}"

    def probe(self, spec: SourceSpec, f: SourceFile) -> ProbeResult:
        if not f.series_id:
            return ProbeResult(ok=False, detail=f"no series_id for {f.landed_filename!r}")
        try:
            key = self._api_key(spec)
            status, payload = self._request_json(   # /series metadata only (design §5)
                f"{_FRED_BASE}/series",
                params={"series_id": f.series_id, "api_key": key, "file_type": "json"},
            )
        except ProviderHttpError as e:
            return ProbeResult(ok=False, http_status=e.status_code, detail=str(e))
        except requests.RequestException as e:
            return ProbeResult(ok=False, detail=f"{type(e).__name__}: {e}")
        except (KeyError, ValueError) as e:
            return ProbeResult(ok=False, detail=f"{type(e).__name__}: {e}")

        seriess = payload.get("seriess") or []
        ok = bool(seriess)
        return ProbeResult(ok=ok, http_status=status,
                           detail=None if ok else "series not found (empty seriess)")

    # -- helpers -------------------------------------------------------------

    def _api_key(self, spec: SourceSpec) -> str:
        if not spec.api_key_env:
            raise ValueError(f"fred_api source {spec.name!r} has no api_key_env")
        if self._secrets is None:
            raise ValueError("FredApiProvider requires a SecretResolver (secrets=...)")
        return self._secrets.get(spec.api_key_env)

    def _request_json(self, url: str, *, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
        # `url` is always KEY-FREE; the key rides in `params`, which requests encodes
        # into the outgoing query but which is never logged. ProviderHttpError carries
        # only the key-free `url` (§16.5).
        timeout = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
        with self._session.get(url, params=params, timeout=timeout) as resp:
            status = resp.status_code
            if status >= 400:
                raise ProviderHttpError(status, url,
                                        retry_after=parse_retry_after(resp.headers.get("Retry-After")))
            return status, resp.json()

    @staticmethod
    def _write_csv(scratch_path: str, observations: list[dict[str, Any]]) -> int:
        with open(scratch_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(_OBS_COLUMNS)
            for obs in observations:
                writer.writerow([obs.get("date", ""), obs.get("value", ""),
                                 obs.get("realtime_start", ""), obs.get("realtime_end", "")])
        return os.path.getsize(scratch_path)

    @staticmethod
    def _canonical_url(series_id: str) -> str:
        # KEY-FREE: series_id only, no api_key — safe for download_log (§16.5).
        return f"{_FRED_BASE}/series/observations?series_id={series_id}&file_type=json"
