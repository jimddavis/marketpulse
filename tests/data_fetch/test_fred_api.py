"""WS-B — FredApiProvider unit tests. No network: FakeSession + FakeSecretResolver."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest
import requests

from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError
from data_fetch.providers.fred_api import FredApiProvider

from fakes import FakeResponse, FakeSession, FakeSecretResolver


def _spec(series_id: str | None = "MORTGAGE30US", api_key_env: str | None = "FRED_API_KEY") -> SourceSpec:
    return SourceSpec(name="fred", provider="fred_api",
                      api_key_env=api_key_env,
                      files=(SourceFile("mortgage_rate_30yr_weekly.csv", series_id=series_id),))


def _ctx(tmp_path) -> RunContext:
    return RunContext(catalog="localdev", pipeline_run_id="LOCALDEV", step_log_id="s1",
                      audit_schema="localdev.audit", scratch_dir=str(tmp_path),
                      now=lambda: datetime.now(timezone.utc))


def _json_response(payload: dict, status: int = 200) -> FakeResponse:
    return FakeResponse(status, body=json.dumps(payload).encode("utf-8"))


_OBS_PAYLOAD = {
    "count": 2,
    "observations": [
        {"realtime_start": "2026-05-20", "realtime_end": "2026-05-20", "date": "1971-04-02", "value": "7.33"},
        {"realtime_start": "2026-05-20", "realtime_end": "2026-05-20", "date": "2025-10-01", "value": "."},
    ],
}
_SERIES_PAYLOAD = {"seriess": [{"id": "MORTGAGE30US", "title": "30-Year Fixed Rate Mortgage Average"}]}


# -- fetch -------------------------------------------------------------------

def test_fetch_writes_4col_csv_preserving_value_verbatim(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response(_OBS_PAYLOAD)])
    provider = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="k123"), session=sess)
    scratch = str(tmp_path / "out.csv")

    res = provider.fetch_to(scratch, spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))

    assert isinstance(res, ProviderFetch)
    with open(scratch, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["date", "value", "realtime_start", "realtime_end"]   # canonical order
    assert rows[1] == ["1971-04-02", "7.33", "2026-05-20", "2026-05-20"]
    assert rows[2][1] == "."          # missing sentinel preserved (Bronze fidelity, §11.1)
    assert res.bytes_written == (tmp_path / "out.csv").stat().st_size


def test_fetch_http_status_is_none_for_fred_path(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response(_OBS_PAYLOAD)])
    res = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="k"), session=sess).fetch_to(
        str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert res.http_status is None     # design §5, §9 — null http_status_code for FRED


def test_fetch_requests_full_history_no_observation_start(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response(_OBS_PAYLOAD)])
    FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="k"), session=sess).fetch_to(
        str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    params = sess.calls[0]["params"]
    assert params["series_id"] == "MORTGAGE30US"
    assert params["file_type"] == "json"
    assert "observation_start" not in params      # full history (design §5)
    assert sess.calls[0]["url"].endswith("/series/observations")


def test_api_key_comes_from_resolver_not_environ(tmp_path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "ENV-SHOULD-NOT-BE-USED")
    spec = _spec()
    sess = FakeSession([_json_response(_OBS_PAYLOAD)])
    FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="from-resolver"), session=sess).fetch_to(
        str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert sess.calls[0]["params"]["api_key"] == "from-resolver"


def test_canonical_url_is_key_free(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response(_OBS_PAYLOAD)])
    res = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="SECRET"), session=sess).fetch_to(
        str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert "api_key" not in res.canonical_url
    assert "SECRET" not in res.canonical_url
    assert "series_id=MORTGAGE30US" in res.canonical_url


def test_canonical_url_matches_fetch_and_is_key_free(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response(_OBS_PAYLOAD)])
    p = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="SECRET"), session=sess)
    pre = p.canonical_url(spec, spec.files[0])
    res = p.fetch_to(str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert pre == res.canonical_url
    assert "api_key" not in pre and "SECRET" not in pre and "series_id=MORTGAGE30US" in pre


def test_fetch_raises_on_bad_key_400_without_leaking_key(tmp_path):
    spec = _spec()
    err = {"error_code": 400, "error_message": "Bad Request. Variable api_key is not set."}
    sess = FakeSession([_json_response(err, status=400)])
    provider = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="SECRET"), session=sess)
    with pytest.raises(ProviderHttpError) as ei:
        provider.fetch_to(str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert ei.value.status_code == 400
    assert "SECRET" not in str(ei.value)          # key never in the raised message (§16.5)


def test_missing_series_id_raises(tmp_path):
    spec = _spec(series_id=None)
    with pytest.raises(ValueError, match="has no series_id"):
        FredApiProvider(secrets=FakeSecretResolver(), session=FakeSession([])).fetch_to(
            str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))


def test_missing_api_key_env_raises(tmp_path):
    spec = _spec(api_key_env=None)
    with pytest.raises(ValueError, match="has no api_key_env"):
        FredApiProvider(secrets=FakeSecretResolver(), session=FakeSession([])).fetch_to(
            str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))


def test_no_secret_resolver_raises(tmp_path):
    spec = _spec()
    with pytest.raises(ValueError, match="requires a SecretResolver"):
        FredApiProvider(secrets=None, session=FakeSession([])).fetch_to(
            str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))


# -- probe -------------------------------------------------------------------

def test_probe_ok_hits_series_endpoint(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response(_SERIES_PAYLOAD)])
    res = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="k"), session=sess).probe(
        spec, spec.files[0])
    assert isinstance(res, ProbeResult)
    assert res.ok and res.http_status == 200
    assert sess.calls[0]["url"].endswith("/series")        # metadata only, not observations


def test_probe_flags_unknown_series(tmp_path):
    spec = _spec()
    sess = FakeSession([_json_response({"seriess": []})])
    res = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="k"), session=sess).probe(
        spec, spec.files[0])
    assert not res.ok and "series not found" in res.detail


def test_probe_flags_bad_key_without_leaking(tmp_path):
    spec = _spec()
    err = {"error_code": 400, "error_message": "Bad Request."}
    sess = FakeSession([_json_response(err, status=400)])
    res = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="SECRET"), session=sess).probe(
        spec, spec.files[0])
    assert not res.ok and res.http_status == 400 and "SECRET" not in (res.detail or "")


def test_probe_reports_network_error(tmp_path):
    class Boom:
        def get(self, *a, **k):
            raise requests.Timeout("slow")

    res = FredApiProvider(secrets=FakeSecretResolver(FRED_API_KEY="k"), session=Boom()).probe(
        _spec(), _spec().files[0])
    assert not res.ok and "Timeout" in res.detail
