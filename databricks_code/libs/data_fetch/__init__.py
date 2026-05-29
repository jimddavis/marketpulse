"""data_fetch — extensible data-acquisition framework for marketpulse.

WS0 (foundations) exposes the frozen contracts: value types, the manifest dataclasses,
the Provider/FileWriter/SecretResolver Protocols, the journal types, and the provider
factory. Behavior (concrete providers, writers, resolvers, the runner, the SOURCES
manifest) lands in later workstreams and is re-exported here as it arrives.
"""

from __future__ import annotations

from data_fetch.constants import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_JITTER_SECONDS,
    BROWSER_UA,
    HTTP_CONNECT_TIMEOUT,
    HTTP_READ_TIMEOUT,
    RETRY_MAX_ATTEMPTS,
    STATUS_FAILED,
    STATUS_NO_FILES,
    STATUS_SKIPPED,
    STATUS_SUCCEEDED,
)
from data_fetch.context import RunContext
from data_fetch.file_writer import FileWriter, LocalFileWriter, VolumeFileWriter
from data_fetch.journal import DownloadJournal, DownloadLogRow
from data_fetch.manifest import SOURCES, SourceFile, SourceSpec
from data_fetch.providers import PROVIDERS, make_provider
from data_fetch.providers.base import ProbeResult, Provider, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError
from data_fetch.providers.fred_api import FredApiProvider
from data_fetch.providers.http_file import HttpFileProvider
from data_fetch.providers.retrying import RetryingProvider
from data_fetch.runner import (
    DownloadRunner,
    FileOutcome,
    HealthCheckResult,
    RunSummary,
    healthcheck,
    local_run_context,
    main,
    run_all,
)
from data_fetch.secrets import (
    DatabricksSecretResolver,
    DotenvSecretResolver,
    SecretResolver,
)
from data_fetch.validation import ValidationError, sha256_of, validate_download

__all__ = [
    # constants
    "BROWSER_UA",
    "RETRY_MAX_ATTEMPTS",
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_JITTER_SECONDS",
    "HTTP_CONNECT_TIMEOUT",
    "HTTP_READ_TIMEOUT",
    "STATUS_SUCCEEDED",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "STATUS_NO_FILES",
    # context
    "RunContext",
    # manifest
    "SourceFile",
    "SourceSpec",
    "SOURCES",
    # providers
    "Provider",
    "ProviderFetch",
    "ProbeResult",
    "ProviderHttpError",
    "HttpFileProvider",
    "FredApiProvider",
    "RetryingProvider",
    "PROVIDERS",
    "make_provider",
    # writer / secrets
    "FileWriter",
    "LocalFileWriter",
    "VolumeFileWriter",
    "SecretResolver",
    "DotenvSecretResolver",
    "DatabricksSecretResolver",
    # journal
    "DownloadJournal",
    "DownloadLogRow",
    # validation
    "validate_download",
    "sha256_of",
    "ValidationError",
    # runner / entry
    "DownloadRunner",
    "run_all",
    "healthcheck",
    "local_run_context",
    "main",
    "RunSummary",
    "FileOutcome",
    "HealthCheckResult",
]
