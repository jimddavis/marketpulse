"""ArcGisFeatureServiceProvider unit tests. No network: FakeSession + FakeResponse."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest
import requests

from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.arcgis_feature_service import ArcGisFeatureServiceProvider
from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError

from fakes import FakeResponse, FakeSession

_QUERY_URL = ("https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
              "National_Risk_Index_Counties/FeatureServer/0/query")


def _spec(url: str | None = _QUERY_URL) -> SourceSpec:
    return SourceSpec(name="fema_nri", provider="arcgis_feature_service",
                      files=(SourceFile("nri_counties.csv", url=url, fmt="csv"),))


def _ctx(tmp_path) -> RunContext:
    return RunContext(catalog="localdev", pipeline_run_id="LOCALDEV", step_log_id="s1",
                      audit_schema="localdev.audit", scratch_dir=str(tmp_path),
                      now=lambda: datetime.now(timezone.utc))


def _page(attribute_rows: list[dict], *, exceeded: bool = False, status: int = 200) -> FakeResponse:
    payload = {"features": [{"attributes": row} for row in attribute_rows],
               "exceededTransferLimit": exceeded}
    return FakeResponse(status, body=json.dumps(payload).encode("utf-8"))


def _count_response(count: int, status: int = 200) -> FakeResponse:
    return FakeResponse(status, body=json.dumps({"count": count}).encode("utf-8"))


# -- fetch -------------------------------------------------------------------

def test_fetch_assembles_all_pages_into_one_csv(tmp_path):
    # exceededTransferLimit=True on the first page signals a second page remains.
    first_page = _page([{"STCOFIPS": "01001", "RISK_SCORE": "57.6"}], exceeded=True)
    second_page = _page([{"STCOFIPS": "01003", "RISK_SCORE": "42.1"}], exceeded=False)
    session = FakeSession([first_page, second_page])
    provider = ArcGisFeatureServiceProvider(session=session)
    scratch = str(tmp_path / "nri.csv")

    result = provider.fetch_to(scratch, _spec(), _spec().files[0], resume_from=0, ctx=_ctx(tmp_path))

    assert isinstance(result, ProviderFetch)
    with open(scratch, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["STCOFIPS", "RISK_SCORE"]        # header = service field order
    assert rows[1] == ["01001", "57.6"]
    assert rows[2] == ["01003", "42.1"]
    assert result.http_status == 200
    assert result.content_length is None                # generated, not a byte stream
    assert result.bytes_written == (tmp_path / "nri.csv").stat().st_size


def test_fetch_stops_when_transfer_limit_not_exceeded(tmp_path):
    session = FakeSession([_page([{"STCOFIPS": "01001"}], exceeded=False)])
    ArcGisFeatureServiceProvider(session=session).fetch_to(
        str(tmp_path / "o.csv"), _spec(), _spec().files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert len(session.calls) == 1                      # single page, no extra request


def test_fetch_sends_deterministic_order_and_advancing_offset(tmp_path):
    session = FakeSession([_page([{"STCOFIPS": "01001"}], exceeded=True),
                           _page([{"STCOFIPS": "01003"}], exceeded=False)])
    ArcGisFeatureServiceProvider(session=session).fetch_to(
        str(tmp_path / "o.csv"), _spec(), _spec().files[0], resume_from=0, ctx=_ctx(tmp_path))
    first_params, second_params = session.calls[0]["params"], session.calls[1]["params"]
    assert first_params["orderByFields"] == "OBJECTID"  # stable order → stable sha256 (no-op)
    assert first_params["returnGeometry"] == "false"
    assert first_params["resultOffset"] == 0
    assert second_params["resultOffset"] == 2000        # advanced by one page


def test_canonical_url_is_the_query_url(tmp_path):
    session = FakeSession([_page([{"STCOFIPS": "01001"}])])
    provider = ArcGisFeatureServiceProvider(session=session)
    pre_fetch_url = provider.canonical_url(_spec(), _spec().files[0])
    result = provider.fetch_to(str(tmp_path / "o.csv"), _spec(), _spec().files[0],
                               resume_from=0, ctx=_ctx(tmp_path))
    assert pre_fetch_url == result.canonical_url == _QUERY_URL


def test_fetch_raises_providerhttperror_on_500(tmp_path):
    session = FakeSession([_page([], status=500)])
    provider = ArcGisFeatureServiceProvider(session=session)
    with pytest.raises(ProviderHttpError) as excinfo:
        provider.fetch_to(str(tmp_path / "o.csv"), _spec(), _spec().files[0],
                          resume_from=0, ctx=_ctx(tmp_path))
    assert excinfo.value.status_code == 500             # >=500 → RetryingProvider retries


def test_fetch_raises_on_empty_result(tmp_path):
    session = FakeSession([_page([], exceeded=False)])
    provider = ArcGisFeatureServiceProvider(session=session)
    with pytest.raises(ValueError, match="no rows"):
        provider.fetch_to(str(tmp_path / "o.csv"), _spec(), _spec().files[0],
                          resume_from=0, ctx=_ctx(tmp_path))


def test_missing_url_raises(tmp_path):
    spec = _spec(url=None)
    with pytest.raises(ValueError, match="has no url"):
        ArcGisFeatureServiceProvider(session=FakeSession([])).fetch_to(
            str(tmp_path / "o.csv"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))


# -- probe -------------------------------------------------------------------

def test_probe_ok_uses_return_count_only(tmp_path):
    session = FakeSession([_count_response(3232)])
    result = ArcGisFeatureServiceProvider(session=session).probe(_spec(), _spec().files[0])
    assert isinstance(result, ProbeResult)
    assert result.ok and result.http_status == 200
    assert session.calls[0]["params"]["returnCountOnly"] == "true"   # cheap count, no rows


def test_probe_flags_zero_rows(tmp_path):
    session = FakeSession([_count_response(0)])
    result = ArcGisFeatureServiceProvider(session=session).probe(_spec(), _spec().files[0])
    assert not result.ok


def test_probe_reports_network_error(tmp_path):
    class Boom:
        def get(self, *args, **kwargs):
            raise requests.Timeout("slow")

    result = ArcGisFeatureServiceProvider(session=Boom()).probe(_spec(), _spec().files[0])
    assert not result.ok and "Timeout" in result.detail
