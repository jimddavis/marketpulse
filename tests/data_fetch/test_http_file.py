"""WS-A — HttpFileProvider unit tests. No network: a FakeSession feeds responses."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from data_fetch.constants import BROWSER_UA
from data_fetch.context import RunContext
from data_fetch.manifest import SourceFile, SourceSpec
from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError
from data_fetch.providers.http_file import HttpFileProvider

from fakes import FakeResponse, FakeSession


def _spec(url: str | None = "https://h/data.csv", ua: str | None = None) -> SourceSpec:
    return SourceSpec(name="zillow", provider="http_file",
                      user_agent=ua, files=(SourceFile("data.csv", url=url),))


def _ctx(tmp_path) -> RunContext:
    return RunContext(catalog="localdev", pipeline_run_id="LOCALDEV", step_log_id="s1",
                      audit_schema="localdev.audit", scratch_dir=str(tmp_path),
                      now=lambda: datetime.now(timezone.utc))


# -- fresh download ----------------------------------------------------------

def test_fresh_download_writes_full_body(tmp_path):
    spec = _spec()
    body = b"col1,col2\n1,2\n"
    sess = FakeSession([FakeResponse(200, headers={"Content-Length": str(len(body))}, body=body)])
    scratch = str(tmp_path / "data.csv")

    res = HttpFileProvider(session=sess).fetch_to(scratch, spec, spec.files[0],
                                                  resume_from=0, ctx=_ctx(tmp_path))

    assert isinstance(res, ProviderFetch)
    assert res.http_status == 200
    assert res.canonical_url == spec.files[0].url
    assert res.bytes_written == len(body)
    assert open(scratch, "rb").read() == body
    assert sess.calls[0]["headers"]["User-Agent"] == BROWSER_UA
    assert "Range" not in sess.calls[0]["headers"]


def test_canonical_url_matches_fetch_result(tmp_path):
    # The pre-fetch canonical_url must equal what fetch_to stamps (consistent source_url).
    spec = _spec()
    sess = FakeSession([FakeResponse(200, headers={"Content-Length": "1"}, body=b"x")])
    p = HttpFileProvider(session=sess)
    pre = p.canonical_url(spec, spec.files[0])
    res = p.fetch_to(str(tmp_path / "d"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))
    assert pre == res.canonical_url == spec.files[0].url


def test_spec_user_agent_overrides_default(tmp_path):
    spec = _spec(ua="custom-agent/1.0")
    sess = FakeSession([FakeResponse(200, body=b"x")])
    HttpFileProvider(session=sess).fetch_to(str(tmp_path / "d"), spec, spec.files[0],
                                            resume_from=0, ctx=_ctx(tmp_path))
    assert sess.calls[0]["headers"]["User-Agent"] == "custom-agent/1.0"


def test_missing_url_raises(tmp_path):
    spec = _spec(url=None)
    with pytest.raises(ValueError, match="has no url"):
        HttpFileProvider(session=FakeSession([])).fetch_to(
            str(tmp_path / "d"), spec, spec.files[0], resume_from=0, ctx=_ctx(tmp_path))


def test_fetch_raises_provider_http_error_on_4xx(tmp_path):
    spec = _spec()
    sess = FakeSession([FakeResponse(404)])
    with pytest.raises(ProviderHttpError) as ei:
        HttpFileProvider(session=sess).fetch_to(str(tmp_path / "d"), spec, spec.files[0],
                                                resume_from=0, ctx=_ctx(tmp_path))
    assert ei.value.status_code == 404


# -- resume ------------------------------------------------------------------

def test_resume_appends_on_consistent_206(tmp_path):
    spec = _spec()
    scratch = tmp_path / "data.csv"
    scratch.write_bytes(b"AAAA")  # 4-byte local partial
    sess = FakeSession([FakeResponse(206, headers={"Content-Range": "bytes 4-7/8"}, body=b"BBBB")])

    res = HttpFileProvider(session=sess).fetch_to(str(scratch), spec, spec.files[0],
                                                  resume_from=4, ctx=_ctx(tmp_path))

    assert sess.calls[0]["headers"]["Range"] == "bytes=4-"
    assert res.http_status == 206
    assert res.bytes_written == 8
    assert scratch.read_bytes() == b"AAAABBBB"


def test_resume_uses_full_body_when_server_ignores_range(tmp_path):
    # Resume requested, but server returns 200 with the full body → write in place, one call.
    spec = _spec()
    scratch = tmp_path / "data.csv"
    scratch.write_bytes(b"AAAA")
    full = b"WXYZ1234"
    sess = FakeSession([FakeResponse(200, headers={"Content-Length": "8"}, body=full)])

    res = HttpFileProvider(session=sess).fetch_to(str(scratch), spec, spec.files[0],
                                                  resume_from=4, ctx=_ctx(tmp_path))

    assert len(sess.calls) == 1
    assert sess.calls[0]["headers"]["Range"] == "bytes=4-"
    assert res.bytes_written == 8
    assert scratch.read_bytes() == full


def test_inconsistent_206_restarts_with_rangeless_refetch(tmp_path):
    # 206 whose Content-Range starts at 0 (not 4) → cannot place → clean refetch (no Range).
    spec = _spec()
    scratch = tmp_path / "data.csv"
    scratch.write_bytes(b"AAAA")
    sess = FakeSession([
        FakeResponse(206, headers={"Content-Range": "bytes 0-7/8"}, body=b"garbage!"),
        FakeResponse(200, headers={"Content-Length": "8"}, body=b"WXYZ1234"),
    ])

    res = HttpFileProvider(session=sess).fetch_to(str(scratch), spec, spec.files[0],
                                                  resume_from=4, ctx=_ctx(tmp_path))

    assert len(sess.calls) == 2
    assert sess.calls[0]["headers"]["Range"] == "bytes=4-"
    assert "Range" not in sess.calls[1]["headers"]   # second GET is Range-less
    assert res.bytes_written == 8
    assert scratch.read_bytes() == b"WXYZ1234"


def test_416_on_resume_restarts_with_rangeless_refetch(tmp_path):
    spec = _spec()
    scratch = tmp_path / "data.csv"
    scratch.write_bytes(b"AAAA")
    sess = FakeSession([
        FakeResponse(416),
        FakeResponse(200, headers={"Content-Length": "4"}, body=b"FULL"),
    ])

    res = HttpFileProvider(session=sess).fetch_to(str(scratch), spec, spec.files[0],
                                                  resume_from=4, ctx=_ctx(tmp_path))

    assert len(sess.calls) == 2
    assert res.bytes_written == 4
    assert scratch.read_bytes() == b"FULL"


# -- probe -------------------------------------------------------------------

def test_probe_ok_on_206_with_content_range(tmp_path):
    spec = _spec()
    sess = FakeSession([FakeResponse(206, headers={"Content-Range": "bytes 0-0/12345"})])
    res = HttpFileProvider(session=sess).probe(spec, spec.files[0])
    assert isinstance(res, ProbeResult)
    assert res.ok and res.http_status == 206 and res.content_length == 12345
    assert sess.calls[0]["headers"]["Range"] == "bytes=0-0"


def test_probe_ok_on_200_with_content_length(tmp_path):
    spec = _spec()
    sess = FakeSession([FakeResponse(200, headers={"Content-Length": "999"})])
    res = HttpFileProvider(session=sess).probe(spec, spec.files[0])
    assert res.ok and res.content_length == 999


def test_probe_flags_404(tmp_path):
    spec = _spec()
    res = HttpFileProvider(session=FakeSession([FakeResponse(404)])).probe(spec, spec.files[0])
    assert not res.ok and res.http_status == 404 and "404" in res.detail


def test_probe_flags_missing_size(tmp_path):
    spec = _spec()
    res = HttpFileProvider(session=FakeSession([FakeResponse(200)])).probe(spec, spec.files[0])
    assert not res.ok and "Content-Length" in res.detail


def test_probe_reports_network_error(tmp_path):
    class Boom:
        def get(self, *a, **k):
            raise requests.ConnectionError("dns failure")

    res = HttpFileProvider(session=Boom()).probe(_spec(), _spec().files[0])
    assert not res.ok and "ConnectionError" in res.detail
