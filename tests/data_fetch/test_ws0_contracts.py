"""WS0 contract tests — frozen value types, satisfiable Protocols, factory behavior.

No network, no SparkSession, no Databricks imports (design §11, §16.1, §16.13).
These freeze the interfaces that WS-A…F build against.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

import data_fetch as df
from data_fetch.providers import PROVIDERS, make_provider


def test_package_imports_without_databricks():
    # The whole public surface must import with no dbutils / SparkSession / requests.
    assert df.RunContext is not None
    assert df.SourceSpec is not None
    assert df.Provider is not None


def test_value_types_are_frozen():
    for cls in (df.RunContext, df.SourceFile, df.SourceSpec,
                df.ProviderFetch, df.ProbeResult,
                df.DownloadLogRow, df.DownloadJournal):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} must be frozen"


def test_runcontext_round_trip_and_immutable():
    ctx = df.RunContext(
        catalog="localdev", pipeline_run_id="LOCALDEV",
        step_log_id="s1", audit_schema="localdev.audit",
        scratch_dir="/tmp", now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert ctx.now().year == 2026
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.catalog = "other"  # type: ignore[misc]


def test_sourcespec_defaults():
    spec = df.SourceSpec(
        name="zillow", provider="http_file", volume="zillow",
        files=(df.SourceFile("x.csv", url="https://h/x.csv"),),
    )
    assert spec.user_agent is None and spec.api_key_env is None
    assert spec.files[0].fmt == "csv"
    assert spec.files[0].expected_header is None


def test_downloadlogrow_fields_match_insert_kwargs():
    # Decision A: record(**asdict(row)) must line up with download_log_insert's
    # keyword-only params (minus spark/audit_schema; no duration_seconds — design §9).
    expected = {
        "download_id", "pipeline_run_id", "step_log_id", "source_system",
        "source_url", "landed_file_path", "status", "http_status_code",
        "bytes_downloaded", "file_sha256", "download_attempts",
        "download_started_ts", "download_ended_ts", "error_message",
    }
    actual = {f.name for f in dataclasses.fields(df.DownloadLogRow)}
    assert actual == expected


def test_protocols_are_runtime_checkable():
    class FakeWriter:
        def promote(self, local_tmp_path, source_system, final_name):
            return "/x"

        def final_size(self, source_system, final_name):
            return 0

        def destination(self, source_system, final_name):
            return "/x"

    class FakeSecrets:
        def get(self, key):
            return "k"

    assert isinstance(FakeWriter(), df.FileWriter)
    assert isinstance(FakeSecrets(), df.SecretResolver)


def test_make_provider_unknown_key_raises():
    spec = df.SourceSpec(name="x", provider="nope", volume="x", files=())
    with pytest.raises(ValueError, match="Unknown provider"):
        make_provider(spec, secrets=None)


def test_make_provider_dispatches_registered(monkeypatch):
    class FakeProvider:
        def __init__(self, *, secrets=None, session=None):
            self.secrets, self.session = secrets, session

        def fetch_to(self, *a, **k): ...
        def probe(self, *a, **k): ...

    monkeypatch.setitem(PROVIDERS, "fake", FakeProvider)
    spec = df.SourceSpec(name="x", provider="fake", volume="x", files=())
    provider = make_provider(spec, secrets="SEC", session="SESS")
    assert isinstance(provider, FakeProvider)
    assert provider.secrets == "SEC" and provider.session == "SESS"
