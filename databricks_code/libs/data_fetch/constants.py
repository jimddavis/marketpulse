"""Module-top constants for the data_fetch framework (WS0).

Centralized so no magic literal appears in two places (CLAUDE.md §6; design §16.11).
Tuning values for retry/backoff/HTTP timeouts and the shared browser User-Agent.
"""

from __future__ import annotations

# Shared browser User-Agent for Family-A HTTP file pulls (Zillow CDN, FHFA, Realtor
# S3). One shared constant — verified sufficient for all three hosts this session
# (design §10). Consumed by HttpFileProvider (WS-A) via SourceSpec.user_agent.
BROWSER_UA: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Retry-with-backoff caps (consumed by RetryingProvider, WS-E). Transient failures
# only — connection errors, timeouts, HTTP 5xx, 429; permanent failures (404/403/
# header mismatch) never retry (design §7.3).
RETRY_MAX_ATTEMPTS: int = 4
BACKOFF_BASE_SECONDS: float = 2.0
BACKOFF_JITTER_SECONDS: float = 0.5

# HTTP timeouts (seconds) for the requests session (Family A + FRED).
HTTP_CONNECT_TIMEOUT: float = 10.0
HTTP_READ_TIMEOUT: float = 60.0

# Pipeline status literals. This package is standalone (it never imports the notebook /
# logging layer), so it keeps its OWN copy; these MUST equal pipeline_logging's STATUS_*
# (the single source of truth, which notebook_init re-exports). The runner stamps these
# on every download_log row — do not invent strings (§16.4). A drift test (test_runner)
# asserts agreement with pipeline_logging.
STATUS_SUCCEEDED: str = "succeeded"
STATUS_FAILED: str = "failed"
STATUS_SKIPPED: str = "skipped"
STATUS_NO_FILES: str = "no_files"
