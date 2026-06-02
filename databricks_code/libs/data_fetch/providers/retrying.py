"""RetryingProvider — Decorator adding retry-with-backoff to any Provider (WS-E).

Wraps an inner Provider and retries only TRANSIENT failures: connection errors, timeouts,
mid-stream drops, HTTP 5xx, and 429 (the latter honoring Retry-After). PERMANENT failures
— 4xx other than 429, and ValueError (e.g. a missing url) — propagate immediately without
retry (design §7.3, §6). Backoff is exponential with additive jitter; the attempt cap is
RETRY_MAX_ATTEMPTS.

The number of attempts the most recent fetch_to consumed is exposed as `last_attempts` for
the runner to record in download_log.download_attempts (ProviderFetch carries no attempt
field — this is the surfacing mechanism). `probe` is delegated straight through: a
healthcheck should report a transient blip as drift, not mask it behind retries.

`sleep` and `rng` are injected so tests are deterministic and don't actually wait.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import requests

from data_fetch.constants import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_JITTER_SECONDS,
    RETRY_MAX_ATTEMPTS,
)
from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.base import ProbeResult, Provider, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError

# Transient network exceptions worth a retry: connection drops, timeouts, and a stream
# interrupted mid-download (which a subsequent attempt can resume).
_TRANSIENT_NETWORK = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class RetryingProvider:
    def __init__(self, inner: Provider, *,
                 max_attempts: int = RETRY_MAX_ATTEMPTS,
                 base_seconds: float = BACKOFF_BASE_SECONDS,
                 jitter_seconds: float = BACKOFF_JITTER_SECONDS,
                 sleep: Callable[[float], Any] = time.sleep,
                 rng: Callable[[], float] = random.random):
        self._inner = inner
        self._max_attempts = max_attempts
        self._base = base_seconds
        self._jitter = jitter_seconds
        self._sleep = sleep
        self._rng = rng
        self.last_attempts = 0

    def fetch_to(self, scratch_path: str, spec: SourceSpec, source_file: SourceFile,
                 *, resume_from: int, ctx: RunContext) -> ProviderFetch:
        for attempt in range(1, self._max_attempts + 1):
            try:
                result = self._inner.fetch_to(scratch_path, spec, source_file,
                                              resume_from=resume_from, ctx=ctx)
                self.last_attempts = attempt
                return result
            except Exception as e:  # classify-and-rethrow boundary, not a swallow
                if not self._is_transient(e) or attempt == self._max_attempts:
                    self.last_attempts = attempt
                    raise
                self._sleep(self._delay(attempt, e))
        raise AssertionError("retry loop exited without returning")  # unreachable

    def probe(self, spec: SourceSpec, source_file: SourceFile) -> ProbeResult:
        return self._inner.probe(spec, source_file)   # cheap healthcheck — delegated, no retry

    def canonical_url(self, spec: SourceSpec, source_file: SourceFile) -> str:
        return self._inner.canonical_url(spec, source_file)   # pure, no I/O — delegated

    def _is_transient(self, e: BaseException) -> bool:
        if isinstance(e, _TRANSIENT_NETWORK):
            return True
        if isinstance(e, ProviderHttpError):
            return e.status_code == 429 or e.status_code >= 500
        return False

    def _delay(self, attempt: int, e: BaseException) -> float:
        if isinstance(e, ProviderHttpError) and e.retry_after is not None:
            return e.retry_after                         # honor server Retry-After (§7.3)
        return self._base * (2 ** (attempt - 1)) + self._rng() * self._jitter
