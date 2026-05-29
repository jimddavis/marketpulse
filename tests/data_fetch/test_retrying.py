"""WS-E — RetryingProvider unit tests. Deterministic: injected sleep recorder + fixed rng."""

from __future__ import annotations

import pytest
import requests

from data_fetch.providers.base import ProbeResult, ProviderFetch
from data_fetch.providers.errors import ProviderHttpError
from data_fetch.providers.retrying import RetryingProvider


class ScriptedProvider:
    """Inner provider: each fetch_to consumes the next scripted outcome (an Exception to
    raise, or a ProviderFetch to return)."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.fetch_calls = 0
        self.probe_calls = 0

    def fetch_to(self, scratch_path, spec, f, *, resume_from, ctx):
        self.fetch_calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def probe(self, spec, f):
        self.probe_calls += 1
        return ProbeResult(ok=True, http_status=200)


_OK = ProviderFetch(bytes_written=10, http_status=200, canonical_url="https://h/x")


def _wrap(outcomes, **kw):
    sleeps: list[float] = []
    inner = ScriptedProvider(outcomes)
    provider = RetryingProvider(inner, sleep=sleeps.append, rng=lambda: 0.5,
                                base_seconds=2.0, jitter_seconds=0.5, **kw)
    return provider, inner, sleeps


def _fetch(provider):
    return provider.fetch_to("scratch", spec=None, f=None, resume_from=0, ctx=None)


# -- happy path / no retry ---------------------------------------------------

def test_succeeds_first_try_no_sleep():
    provider, inner, sleeps = _wrap([_OK])
    assert _fetch(provider) is _OK
    assert inner.fetch_calls == 1 and provider.last_attempts == 1 and sleeps == []


# -- transient retries -------------------------------------------------------

def test_retries_connection_error_then_succeeds():
    provider, inner, sleeps = _wrap([requests.ConnectionError("drop"), _OK])
    assert _fetch(provider) is _OK
    assert inner.fetch_calls == 2 and provider.last_attempts == 2 and len(sleeps) == 1


def test_retries_5xx_and_429_then_succeeds():
    provider, inner, sleeps = _wrap([
        ProviderHttpError(503, "u"), ProviderHttpError(429, "u"), _OK])
    assert _fetch(provider) is _OK
    assert inner.fetch_calls == 3 and provider.last_attempts == 3 and len(sleeps) == 2


def test_gives_up_after_max_attempts_and_reraises():
    provider, inner, sleeps = _wrap([requests.Timeout("t")] * 4, max_attempts=4)
    with pytest.raises(requests.Timeout):
        _fetch(provider)
    assert inner.fetch_calls == 4 and provider.last_attempts == 4 and len(sleeps) == 3


# -- permanent failures: no retry --------------------------------------------

def test_permanent_4xx_not_retried():
    provider, inner, sleeps = _wrap([ProviderHttpError(404, "u")])
    with pytest.raises(ProviderHttpError) as ei:
        _fetch(provider)
    assert ei.value.status_code == 404
    assert inner.fetch_calls == 1 and provider.last_attempts == 1 and sleeps == []


def test_permanent_valueerror_not_retried():
    provider, inner, sleeps = _wrap([ValueError("missing url")])
    with pytest.raises(ValueError):
        _fetch(provider)
    assert inner.fetch_calls == 1 and sleeps == []


# -- backoff math ------------------------------------------------------------

def test_exponential_backoff_with_jitter():
    # base=2, jitter=0.5, rng()=0.5 → delay = 2*2^(n-1) + 0.25
    provider, inner, sleeps = _wrap([
        requests.Timeout("t"), requests.Timeout("t"), _OK])
    _fetch(provider)
    assert sleeps == [2.0 + 0.25, 4.0 + 0.25]   # [2.25, 4.25]


def test_honors_retry_after_over_backoff():
    provider, inner, sleeps = _wrap([ProviderHttpError(429, "u", retry_after=7.0), _OK])
    _fetch(provider)
    assert sleeps == [7.0]            # server Retry-After used verbatim, not exponential


# -- probe is delegated ------------------------------------------------------

def test_probe_delegates_without_retry():
    provider, inner, sleeps = _wrap([])
    res = provider.probe(spec=None, f=None)
    assert res.ok and inner.probe_calls == 1 and sleeps == []
