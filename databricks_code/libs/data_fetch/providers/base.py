"""Provider Strategy protocol and its return value objects (WS0).

Defines the one real axis of variation — HTTP file pull vs JSON API — behind a single
Protocol. Concrete providers (HttpFileProvider, FredApiProvider) are WS-A/B
(design §5, §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec


@dataclass(frozen=True)
class ProviderFetch:
    bytes_written: int
    http_status: int | None        # None for the FRED JSON path
    canonical_url: str             # KEY-FREE url for logging + no-op keying (§16.5)
    content_length: int | None = None  # server-declared total size; drives the truncation
    #                                     check (§7.5). None when unknown / generated (FRED).


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    http_status: int | None = None
    content_length: int | None = None
    detail: str | None = None      # drift / failure explanation for healthcheck (§7.1)


@runtime_checkable
class Provider(Protocol):
    def fetch_to(self, scratch_path: str, spec: SourceSpec, f: SourceFile,
                 *, resume_from: int, ctx: RunContext) -> ProviderFetch:
        """Write the file's raw bytes to `scratch_path` on LOCAL disk.

        `resume_from` > 0 requests an HTTP Range continuation appended to the existing
        local partial (Family A); providers that cannot resume ignore it and restart.
        Returns bytes written, http_status, and a KEY-FREE canonical_url (design §5).
        """
        ...

    def probe(self, spec: SourceSpec, f: SourceFile) -> ProbeResult:
        """Cheap reachability check for healthcheck mode — no full download (§7.1)."""
        ...
