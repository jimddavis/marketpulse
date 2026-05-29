"""Download journal — the functional logging seam (WS0).

The project's logging is functional (pipeline_logging module-level functions), NOT a
logger class hierarchy. The core sees logging as two injected callables bundled here
(design §9, §16.10). On Databricks they are partial-bound to pipeline_logging.
download_log_insert / download_log_last_sha256; locally they are no-ops so a missing
audit table never fails a local run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class DownloadLogRow:
    """One download_log row.

    Field names match pipeline_logging.download_log_insert's keyword args exactly
    (decision A this session), so the runner calls `journal.record(**asdict(row))` and
    the Databricks binding `partial(download_log_insert, spark, AUDIT)` works verbatim
    (design §8.1, §9, §16.10). `duration_seconds` is intentionally absent — the insert
    derives it from the two timestamps. `status` is a notebook_init STATUS_* literal
    (§16.4); `source_url` is the KEY-FREE canonical url (§16.5).
    """
    download_id: str
    pipeline_run_id: str
    step_log_id: str
    source_system: str
    source_url: str
    landed_file_path: str
    status: str
    http_status_code: int | None = None
    bytes_downloaded: int | None = None
    file_sha256: str | None = None
    download_attempts: int | None = None
    download_started_ts: datetime | None = None
    download_ended_ts: datetime | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DownloadJournal:
    """Two injected callables.

    `record` persists a row (called as `record(**asdict(row))`); `last_sha256` returns
    the last successfully-landed sha256 for a canonical url, or None (locally always
    None → local runs always download, design §7.6).
    """
    record: Callable[..., object]
    last_sha256: Callable[[str], str | None]
