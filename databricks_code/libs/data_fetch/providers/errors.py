"""Provider error taxonomy (WS-A).

Raised by providers so the retry Decorator (WS-E) can classify transient vs permanent
failures without parsing strings. Permanent HTTP statuses (e.g. 403/404) must NOT be
retried; transient ones (429, >=500) and connection/timeout errors are (design §7.3).
"""

from __future__ import annotations


class ProviderHttpError(Exception):
    """A provider received a non-success HTTP status.

    `status_code` lets the RetryingProvider (WS-E) decide retry eligibility (transient:
    429, >=500; permanent: other 4xx). `url` is the KEY-FREE request URL for diagnostics.
    `retry_after` (seconds) carries a parsed Retry-After header so the decorator can honor
    a server-requested delay on 429/5xx (design §7.3).
    """

    def __init__(self, status_code: int, url: str, message: str | None = None,
                 *, retry_after: float | None = None):
        self.status_code = status_code
        self.url = url
        self.retry_after = retry_after
        super().__init__(message or f"HTTP {status_code} for {url}")


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header expressed in integer seconds. Returns None for an absent
    header or the HTTP-date form (not honored — Zillow/Realtor/FRED use the seconds form).
    """
    if value is None:
        return None
    value = value.strip()
    return float(value) if value.isdigit() else None
