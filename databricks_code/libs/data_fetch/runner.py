"""DownloadRunner + run_all / healthcheck / main — the integration capstone (WS-G).

Template Method (design §6, §7): the per-file lifecycle is identical for every source —
fetch → validate → sha256 + idempotent no-op → promote → journal. Only the Provider's
fetch varies. Batch policy is ABORT-ON-FIRST (§16.3): the first failing file stops the
run; remaining files are NOT attempted; run_all re-raises after logging the FAILED row.

The composition root (the entry notebook on Databricks, or main() locally) injects the
writer, journal, secrets, and RunContext. This module wires providers (make_provider →
RetryingProvider) unless a `provider_for` is supplied — tests inject fakes that way.
Every provider is wrapped in RetryingProvider, so `provider.last_attempts` always exists
and feeds download_attempts (§7.3 surfacing mechanism).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable

import requests

from data_fetch.constants import STATUS_FAILED, STATUS_SKIPPED, STATUS_SUCCEEDED
from data_fetch.context import RunContext
from data_fetch.file_writer import FileWriter, LocalFileWriter
from data_fetch.journal import DownloadJournal, DownloadLogRow
from data_fetch.manifest import SOURCES, SourceFile, SourceSpec
from data_fetch.providers import make_provider
from data_fetch.providers.base import Provider
from data_fetch.providers.retrying import RetryingProvider
from data_fetch.secrets import DotenvSecretResolver, SecretResolver
from data_fetch.validation import sha256_of, validate_download

ProviderFor = Callable[[SourceSpec], Provider]


@dataclass(frozen=True)
class FileOutcome:
    source_system: str
    landed_filename: str
    status: str                      # STATUS_SUCCEEDED | STATUS_SKIPPED | STATUS_FAILED
    canonical_url: str
    landed_file_path: str | None
    bytes_downloaded: int | None
    sha256: str | None
    attempts: int
    error: str | None = None


@dataclass(frozen=True)
class HealthCheckResult:
    source_system: str
    landed_filename: str
    ok: bool
    http_status: int | None
    content_length: int | None
    detail: str | None


@dataclass(frozen=True)
class RunSummary:
    outcomes: tuple[FileOutcome, ...]

    def by_status(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    def describe(self) -> str:
        return (f"download run: {len(self.by_status(STATUS_SUCCEEDED))} succeeded, "
                f"{len(self.by_status(STATUS_SKIPPED))} skipped, "
                f"{len(self.by_status(STATUS_FAILED))} failed "
                f"({len(self.outcomes)} files total)")


class DownloadRunner:
    def __init__(self, ctx: RunContext, *, provider_for: ProviderFor,
                 writer: FileWriter | None = None, journal: DownloadJournal | None = None):
        self._ctx = ctx
        self._provider_for = provider_for
        self._writer = writer
        self._journal = journal

    def run_all(self, sources) -> RunSummary:
        outcomes: list[FileOutcome] = []
        for spec in sources:
            provider = self._provider_for(spec)
            for f in spec.files:
                outcomes.append(self.run_file(provider, spec, f))   # raises on failure
        return RunSummary(tuple(outcomes))

    def healthcheck(self, sources) -> list[HealthCheckResult]:
        results: list[HealthCheckResult] = []
        for spec in sources:
            provider = self._provider_for(spec)
            for f in spec.files:
                p = provider.probe(spec, f)
                results.append(HealthCheckResult(spec.name, f.landed_filename, p.ok,
                                                 p.http_status, p.content_length, p.detail))
        return results

    def run_file(self, provider: Provider, spec: SourceSpec, f: SourceFile) -> FileOutcome:
        scratch = os.path.join(self._ctx.scratch_dir, f"{spec.name}__{f.landed_filename}")
        dest = self._writer.destination(spec.name, f.landed_filename)
        started = self._ctx.now()
        download_id = str(uuid.uuid4())
        # Seed source_url for the FAILED-before-fetch case from the provider's own KEY-FREE
        # URL shaping (no provider-specific logic here); overwritten with fetch.canonical_url
        # on success — both produce the same string, so the namespace is consistent.
        canonical_url = provider.canonical_url(spec, f)
        bytes_dl: int | None = None
        http_status: int | None = None
        sha: str | None = None
        attempts = 1
        try:
            fetch = provider.fetch_to(scratch, spec, f, resume_from=0, ctx=self._ctx)
            attempts = getattr(provider, "last_attempts", 1)
            canonical_url = fetch.canonical_url
            bytes_dl = fetch.bytes_written
            http_status = fetch.http_status

            validate_download(scratch, fmt=f.fmt, expected_header=f.expected_header,
                              expected_size=fetch.content_length)
            sha = sha256_of(scratch)

            prior = self._journal.last_sha256(canonical_url)
            if prior is not None and prior == sha:
                status, landed = STATUS_SKIPPED, dest      # identical bytes already landed (§7.6) — no promote
            else:
                status = STATUS_SUCCEEDED
                landed = self._writer.promote(scratch, spec.name, f.landed_filename)
            self._record(download_id, spec, canonical_url, landed, status,
                         http_status, bytes_dl, sha, attempts, started, None)
            return FileOutcome(spec.name, f.landed_filename, status,
                               canonical_url, landed, bytes_dl, sha, attempts)
        except Exception as e:
            attempts = getattr(provider, "last_attempts", attempts)
            self._record(download_id, spec, canonical_url, dest, STATUS_FAILED,
                         http_status, bytes_dl, sha, attempts, started,
                         f"{type(e).__name__}: {e}")
            raise                                            # abort-on-first (§16.3)
        finally:
            if os.path.exists(scratch):
                os.remove(scratch)                           # scratch orphan cleanup (§7.2)

    def _record(self, download_id: str, spec: SourceSpec, canonical_url: str,
                landed_file_path: str, status: str, http_status: int | None,
                bytes_dl: int | None, sha: str | None, attempts: int,
                started: datetime, error: str | None) -> None:
        row = DownloadLogRow(
            download_id=download_id,
            pipeline_run_id=self._ctx.pipeline_run_id,
            step_log_id=self._ctx.step_log_id,
            source_system=spec.name,
            source_url=canonical_url,
            landed_file_path=landed_file_path,
            status=status,
            http_status_code=http_status,
            bytes_downloaded=bytes_dl,
            file_sha256=sha,
            download_attempts=attempts,
            download_started_ts=started,
            download_ended_ts=self._ctx.now(),
            error_message=error,
        )
        self._journal.record(**asdict(row))


def _default_provider_for(secrets: SecretResolver, *,
                          session: requests.Session | None = None,
                          retry: bool = True) -> ProviderFor:
    session = session or requests.Session()

    def provider_for(spec: SourceSpec) -> Provider:
        provider = make_provider(spec, secrets=secrets, session=session)
        return RetryingProvider(provider) if retry else provider

    return provider_for


def local_run_context(scratch_dir: str | None = None) -> RunContext:
    """Dummy RunContext for local dev / CLI (design §8.1): localdev catalog, LOCALDEV run
    id, a fresh uuid4 step_log_id, UTC clock, and scratch in the system temp dir. Shared by
    runner.main and scripts/download_local.py so the local-dev wiring lives in one place."""
    return RunContext(
        catalog="localdev", pipeline_run_id="LOCALDEV", step_log_id=str(uuid.uuid4()),
        audit_schema="localdev.audit", scratch_dir=scratch_dir or tempfile.gettempdir(),
        now=lambda: datetime.now(timezone.utc),
    )


def run_all(sources, ctx: RunContext, *, writer: FileWriter, journal: DownloadJournal,
            secrets: SecretResolver, provider_for: ProviderFor | None = None) -> RunSummary:
    provider_for = provider_for or _default_provider_for(secrets)
    runner = DownloadRunner(ctx, provider_for=provider_for, writer=writer, journal=journal)
    return runner.run_all(sources)


def healthcheck(sources, ctx: RunContext, *, secrets: SecretResolver,
                provider_for: ProviderFor | None = None) -> list[HealthCheckResult]:
    provider_for = provider_for or _default_provider_for(secrets)
    return DownloadRunner(ctx, provider_for=provider_for).healthcheck(sources)


def main(argv: list[str] | None = None) -> int:
    """Local / CI entry: `python -m data_fetch --root <dir>` or `--healthcheck`.

    Builds a local composition root — LocalFileWriter, no-op journal (a missing audit
    table must never fail a local run, §9), DotenvSecretResolver — with dummy RunContext
    values. The deployed Databricks entry is the bronze/download_sources notebook (§8.1).
    """
    parser = argparse.ArgumentParser(prog="python -m data_fetch",
                                     description="Download raw source files (local-first).")
    parser.add_argument("--root", help="local destination root (mirrors /Volumes/<catalog>/raw/)")
    parser.add_argument("--scratch", default=tempfile.gettempdir(), help="scratch dir for partial downloads")
    parser.add_argument("--healthcheck", action="store_true", help="probe every source URL; land nothing")
    args = parser.parse_args(argv)

    ctx = local_run_context(args.scratch)
    secrets = DotenvSecretResolver()

    if args.healthcheck:
        results = healthcheck(SOURCES, ctx, secrets=secrets)
        for r in results:
            flag = "OK " if r.ok else "BAD"
            print(f"  [{flag}] {r.source_system}/{r.landed_filename}  "
                  f"http={r.http_status} size={r.content_length} {r.detail or ''}")
        return 0 if all(r.ok for r in results) else 1

    if not args.root:
        parser.error("--root is required unless --healthcheck")
    journal = DownloadJournal.noop()
    try:
        summary = run_all(SOURCES, ctx, writer=LocalFileWriter(args.root),
                          journal=journal, secrets=secrets)
    except Exception as e:
        print(f"download run failed (abort-on-first): {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(summary.describe())
    return 0
