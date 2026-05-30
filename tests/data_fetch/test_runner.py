"""WS-G — DownloadRunner lifecycle + run_all/healthcheck. No network, no Spark.

Injected fakes: StubProvider (writes scratch bytes / raises), LocalFileWriter over
tmp_path, a CapturingJournal, a fixed clock. Covers the design §11 lifecycle matrix.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
import requests

from data_fetch.constants import STATUS_FAILED, STATUS_SKIPPED, STATUS_SUCCEEDED
from data_fetch.context import RunContext
from data_fetch.file_writer import LocalFileWriter
from data_fetch.journal import DownloadJournal
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError
from data_fetch.providers.retrying import RetryingProvider
from data_fetch.runner import DownloadRunner, RunSummary, run_all
from data_fetch.validation import ValidationError

_HEADER = ("RegionID", "SizeRank", "RegionName", "RegionType", "StateName")
_GOOD = b"RegionID,SizeRank,RegionName,RegionType,StateName\n1,2,3,4,5\n"


# -- fakes -------------------------------------------------------------------

class StubProvider:
    """Inner provider: writes `content` to scratch and returns a ProviderFetch, or raises
    `raises`. Records fetch_to call count; exposes last_attempts like RetryingProvider."""

    def __init__(self, content=_GOOD, *, http_status=200, content_length=None,
                 canonical_url="https://h/x.csv", raises=None, last_attempts=1):
        self._content = content
        self._http = http_status
        self._cl = content_length
        self._url = canonical_url
        self._raises = raises
        self.last_attempts = last_attempts
        self.fetch_count = 0

    def fetch_to(self, scratch_path, spec, f, *, resume_from, ctx):
        self.fetch_count += 1
        if self._raises is not None:
            raise self._raises
        with open(scratch_path, "wb") as fh:
            fh.write(self._content)
        return ProviderFetch(bytes_written=len(self._content), http_status=self._http,
                             canonical_url=self._url, content_length=self._cl)

    def probe(self, spec, f):
        return ProbeResult(ok=True, http_status=200, content_length=len(self._content))

    def canonical_url(self, spec, f):
        return self._url


class CapturingJournal:
    def __init__(self, last_sha=None):
        self.records: list[dict] = []
        self._last_sha = last_sha          # str | dict[url,str] | None

    def record(self, **kw):
        self.records.append(kw)

    def last_sha256(self, url):
        if isinstance(self._last_sha, dict):
            return self._last_sha.get(url)
        return self._last_sha

    def as_journal(self) -> DownloadJournal:
        return DownloadJournal(record=self.record, last_sha256=self.last_sha256)


def _ctx(tmp_path) -> RunContext:
    return RunContext(catalog="localdev", pipeline_run_id="RUN1", step_log_id="STEP1",
                      audit_schema="localdev.audit", scratch_dir=str(tmp_path / "scratch"),
                      now=lambda: datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc))


def _spec(*files):
    return SourceSpec(name="zillow", provider="http_file", files=files)


def _runner(tmp_path, provider, journal):
    (tmp_path / "scratch").mkdir(exist_ok=True)
    return DownloadRunner(_ctx(tmp_path), provider_for=lambda spec: provider,
                          writer=LocalFileWriter(str(tmp_path / "root")), journal=journal)


# -- success -----------------------------------------------------------------

def test_success_lands_file_and_logs_succeeded(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)
    cap = CapturingJournal()
    runner = _runner(tmp_path, StubProvider(content_length=len(_GOOD)), cap.as_journal())

    summary = runner.run_all((_spec(f),))

    landed = tmp_path / "root" / "zillow" / "z.csv"
    assert landed.read_bytes() == _GOOD
    assert isinstance(summary, RunSummary)
    [o] = summary.outcomes
    assert o.status == STATUS_SUCCEEDED and o.landed_file_path == str(landed)
    assert o.sha256 == hashlib.sha256(_GOOD).hexdigest()
    # one download_log row, succeeded, key-free url, sha + bytes recorded
    [row] = cap.records
    assert row["status"] == STATUS_SUCCEEDED
    assert row["source_url"] == "https://h/x.csv"
    assert row["file_sha256"] == o.sha256 and row["bytes_downloaded"] == len(_GOOD)
    assert row["pipeline_run_id"] == "RUN1" and row["step_log_id"] == "STEP1"
    # scratch cleaned up
    assert not (tmp_path / "scratch" / "zillow__z.csv").exists()


# -- validation failure → no promote + raise ---------------------------------

def test_validation_failure_does_not_promote_and_raises(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=("WRONG",))
    cap = CapturingJournal()
    runner = _runner(tmp_path, StubProvider(), cap.as_journal())

    with pytest.raises(ValidationError):
        runner.run_all((_spec(f),))

    assert not (tmp_path / "root" / "zillow" / "z.csv").exists()   # nothing landed
    [row] = cap.records
    assert row["status"] == STATUS_FAILED and "header prefix mismatch" in row["error_message"]


# -- abort-on-first ----------------------------------------------------------

def test_abort_on_first_stops_the_batch(tmp_path):
    f1 = SourceFile("a.csv", url="https://h/a.csv", expected_header=_HEADER)
    f2 = SourceFile("b.csv", url="https://h/b.csv", expected_header=_HEADER)
    provider = StubProvider(raises=ProviderHttpError(404, "https://h/a.csv"))
    cap = CapturingJournal()
    runner = _runner(tmp_path, provider, cap.as_journal())

    with pytest.raises(ProviderHttpError):
        runner.run_all((_spec(f1, f2),))

    assert provider.fetch_count == 1          # second file never attempted
    assert len(cap.records) == 1 and cap.records[0]["status"] == STATUS_FAILED


# -- retry semantics (real RetryingProvider wrapping a scripted inner) --------

def test_retry_then_succeed_records_attempts(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)

    class FlakyInner(StubProvider):
        def fetch_to(self, scratch_path, spec, file, *, resume_from, ctx):
            if self.fetch_count == 0:
                self.fetch_count += 1
                raise requests.ConnectionError("blip")
            return super().fetch_to(scratch_path, spec, file, resume_from=resume_from, ctx=ctx)

    wrapped = RetryingProvider(FlakyInner(), sleep=lambda s: None)
    cap = CapturingJournal()
    runner = _runner(tmp_path, wrapped, cap.as_journal())

    [o] = runner.run_all((_spec(f),)).outcomes
    assert o.status == STATUS_SUCCEEDED and o.attempts == 2
    assert cap.records[0]["download_attempts"] == 2


def test_retry_exhaustion_logs_failed_with_attempts(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)
    wrapped = RetryingProvider(StubProvider(raises=requests.Timeout("t")),
                               max_attempts=3, sleep=lambda s: None)
    cap = CapturingJournal()
    runner = _runner(tmp_path, wrapped, cap.as_journal())

    with pytest.raises(requests.Timeout):
        runner.run_all((_spec(f),))
    [row] = cap.records
    assert row["status"] == STATUS_FAILED and row["download_attempts"] == 3


# -- idempotent no-op (sha match) --------------------------------------------

def test_sha_match_skips_promote(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)
    prior_sha = hashlib.sha256(_GOOD).hexdigest()
    cap = CapturingJournal(last_sha={"https://h/x.csv": prior_sha})   # keyed on canonical_url
    runner = _runner(tmp_path, StubProvider(), cap.as_journal())

    # File already landed from a prior run. Pre-create it with sentinel bytes so we can
    # prove promote did NOT overwrite it on the skip.
    dest = tmp_path / "root" / "zillow" / "z.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"ALREADY-LANDED")

    [o] = runner.run_all((_spec(f),)).outcomes
    assert o.status == STATUS_SKIPPED
    assert dest.read_bytes() == b"ALREADY-LANDED"                    # promote skipped (not overwritten)
    assert cap.records[0]["status"] == STATUS_SKIPPED
    assert o.landed_file_path == str(dest)                           # destination, not promoted


def test_sha_match_but_file_missing_re_promotes(tmp_path):
    # Content unchanged from the prior run (sha matches the journal), but the landed file
    # was deleted out-of-band (e.g. Volume cleared). The runner must re-promote, not no-op.
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)
    prior_sha = hashlib.sha256(_GOOD).hexdigest()
    cap = CapturingJournal(last_sha={"https://h/x.csv": prior_sha})   # keyed on canonical_url
    runner = _runner(tmp_path, StubProvider(), cap.as_journal())

    dest = tmp_path / "root" / "zillow" / "z.csv"
    assert not dest.exists()                                         # landed file is gone

    [o] = runner.run_all((_spec(f),)).outcomes
    assert o.status == STATUS_SUCCEEDED                              # re-downloaded despite sha match
    assert dest.read_bytes() == _GOOD                               # file restored
    assert cap.records[0]["status"] == STATUS_SUCCEEDED


# -- run_all module function with injected provider_for ----------------------

def test_run_all_function_with_injected_provider_for(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)
    (tmp_path / "scratch").mkdir()
    cap = CapturingJournal()
    summary = run_all((_spec(f),), _ctx(tmp_path),
                      writer=LocalFileWriter(str(tmp_path / "root")), journal=cap.as_journal(),
                      secrets=None, provider_for=lambda spec: StubProvider())
    assert len(summary.by_status(STATUS_SUCCEEDED)) == 1


# -- healthcheck -------------------------------------------------------------

def test_healthcheck_reports_without_landing(tmp_path):
    f = SourceFile("z.csv", url="https://h/z.csv", expected_header=_HEADER)
    runner = DownloadRunner(_ctx(tmp_path), provider_for=lambda spec: StubProvider())
    results = runner.healthcheck((_spec(f),))
    assert len(results) == 1 and results[0].ok and results[0].source_system == "zillow"
    assert not (tmp_path / "root").exists()      # nothing written


# -- status literals agree across all three definitions (drift guard) --------

def test_status_literals_match_pipeline_logging():
    # STATUS_* now lives in ONE place — pipeline_logging (notebook_init re-exports it,
    # so it is transitively covered). data_fetch.constants keeps its OWN copy by design:
    # the package is standalone and never imports the notebook/logging layer. This
    # asserts the two independent definitions agree, so a change in one surfaces as a
    # test failure, not silent audit drift.
    import pipeline_logging as pl
    from data_fetch import constants as c

    assert c.STATUS_SUCCEEDED == pl.STATUS_SUCCEEDED == "succeeded"
    assert c.STATUS_FAILED    == pl.STATUS_FAILED    == "failed"
    assert c.STATUS_SKIPPED   == pl.STATUS_SKIPPED   == "skipped"
    assert c.STATUS_NO_FILES  == pl.STATUS_NO_FILES  == "no_files"
