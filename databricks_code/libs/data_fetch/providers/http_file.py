"""HttpFileProvider — Family-A HTTP file pull (WS-A).

Serves Zillow (CDN), FHFA, and Realtor (S3): a plain GET with a browser User-Agent,
streamed to a LOCAL scratch file, with optional HTTP Range resume onto an existing
partial. `canonical_url` is the URL itself — there is no key to strip (§16.5).

Constructed uniformly as `HttpFileProvider(secrets=..., session=...)` per the provider
factory contract (design §5); it uses `session` (a requests.Session) and ignores
`secrets`. Range resume is best-effort hardening — files are ~4–32 MB and both probed
hosts honor Range (design §7.4, §14).
"""

from __future__ import annotations

import os
from typing import Any

import requests

from data_fetch.constants import BROWSER_UA, HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT
from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError, parse_retry_after

_CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunks — never load the whole file in memory


class HttpFileProvider:
    def __init__(self, *, secrets: Any = None, session: requests.Session | None = None):
        # `secrets` accepted for the uniform factory signature; unused (no auth).
        self._session = session if session is not None else requests.Session()

    # -- fetch ---------------------------------------------------------------

    def fetch_to(self, scratch_path: str, spec: SourceSpec, f: SourceFile,
                 *, resume_from: int, ctx: RunContext) -> ProviderFetch:
        url = f.url
        if not url:
            raise ValueError(
                f"http_file source {spec.name!r} file {f.landed_filename!r} has no url"
            )
        timeout = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)

        def _result(resp, status):
            return ProviderFetch(bytes_written=os.path.getsize(scratch_path),
                                 http_status=status, canonical_url=url,
                                 content_length=self._total_size(resp))

        # 1) Try to resume onto an existing local partial (design §7.4).
        if resume_from > 0:
            with self._session.get(url, headers=self._headers(spec, resume_from),
                                   stream=True, timeout=timeout) as resp:
                status = resp.status_code
                if status == 206 and self._range_consistent(resp, resume_from):
                    self._stream_to(resp, scratch_path, mode="ab")   # append remainder
                    return _result(resp, status)
                if status == 200:
                    self._stream_to(resp, scratch_path, mode="wb")   # server ignored Range; full body
                    return _result(resp, status)
                if status >= 400 and status != 416:
                    raise ProviderHttpError(status, url,
                                        retry_after=parse_retry_after(resp.headers.get("Retry-After")))
                # 416 (range unsatisfiable) or an inconsistent 206 → fall through to a
                # clean, Range-less re-download from zero.

        # 2) Fresh (or restarted) full download — no Range header.
        with self._session.get(url, headers=self._headers(spec, 0),
                               stream=True, timeout=timeout) as resp:
            status = resp.status_code
            if status >= 400:
                raise ProviderHttpError(status, url,
                                        retry_after=parse_retry_after(resp.headers.get("Retry-After")))
            self._stream_to(resp, scratch_path, mode="wb")
            return _result(resp, status)

    # -- probe ---------------------------------------------------------------

    def canonical_url(self, spec: SourceSpec, f: SourceFile) -> str:
        # The URL itself — no key to strip. Falls back to a stable identifier for a
        # malformed manifest entry so the value is never null (fetch_to raises on it).
        return f.url or f"{spec.name}/{f.landed_filename}"

    def probe(self, spec: SourceSpec, f: SourceFile) -> ProbeResult:
        url = f.url
        if not url:
            return ProbeResult(ok=False, detail=f"no url for {f.landed_filename!r}")
        headers = {"User-Agent": spec.user_agent or BROWSER_UA, "Range": "bytes=0-0"}
        timeout = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
        try:
            with self._session.get(url, headers=headers, stream=True,
                                   timeout=timeout) as resp:
                status = resp.status_code
                total = self._total_size(resp)
        except requests.RequestException as e:
            return ProbeResult(ok=False, detail=f"{type(e).__name__}: {e}")

        ok = status in (200, 206) and total is not None and total > 0
        if status not in (200, 206):
            detail = f"unexpected status {status}"
        elif total is None:
            detail = "no Content-Length / Content-Range"
        elif total == 0:
            detail = "zero-length"
        else:
            detail = None
        return ProbeResult(ok=ok, http_status=status, content_length=total, detail=detail)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _headers(spec: SourceSpec, resume_from: int) -> dict[str, str]:
        headers = {"User-Agent": spec.user_agent or BROWSER_UA}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        return headers

    @staticmethod
    def _stream_to(resp: Any, scratch_path: str, *, mode: str) -> None:
        with open(scratch_path, mode) as out:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if chunk:
                    out.write(chunk)

    @staticmethod
    def _range_consistent(resp: Any, resume_from: int) -> bool:
        # Content-Range looks like "bytes 100-199/200"; the served range must start
        # exactly where our local partial ends.
        return resp.headers.get("Content-Range", "").startswith(f"bytes {resume_from}-")

    @staticmethod
    def _total_size(resp: Any) -> int | None:
        # Prefer the total after the slash in Content-Range (a bytes=0-0 probe returns
        # Content-Length: 1, which is not the file size); fall back to Content-Length.
        cr = resp.headers.get("Content-Range", "")
        if "/" in cr:
            tail = cr.rsplit("/", 1)[-1].strip()
            if tail.isdigit():
                return int(tail)
        cl = resp.headers.get("Content-Length", "")
        return int(cl) if cl.isdigit() else None
