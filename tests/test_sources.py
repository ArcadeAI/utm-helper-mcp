"""Tests for spec fetching: caching, and fail-loud behavior (no silent default)."""

import httpx
import pytest

from utm_server.config import Config, config_from_url
from utm_server.sources import GUIDE_FILENAME, SpecSource, SpecSourceError, get_source


class FakeClock:
    """A controllable monotonic clock for exercising cache expiry."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_config(url: str = "https://example.test/spec/") -> Config:
    return Config(spec_source_url=url, is_default_source=False)


def make_source(handler, clock=None, ttl=300.0) -> SpecSource:
    """Build a SpecSource backed by an httpx.MockTransport handler."""
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return SpecSource(make_config(), client=client, clock=clock or FakeClock(), ttl=ttl)


def test_get_guidelines_returns_fetched_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/spec/GUIDE.md"
        return httpx.Response(200, text="# The Guide\n")

    source = make_source(handler)
    assert source.get_guidelines() == "# The Guide\n"


def test_successful_fetch_is_cached_within_ttl():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text="cached body")

    clock = FakeClock()
    source = make_source(handler, clock=clock, ttl=300.0)

    assert source.get_text(GUIDE_FILENAME) == "cached body"
    clock.advance(299)  # still within TTL
    assert source.get_text(GUIDE_FILENAME) == "cached body"
    assert calls["n"] == 1  # only one network hit


def test_cache_expires_after_ttl():
    bodies = iter(["first", "second"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=next(bodies))

    clock = FakeClock()
    source = make_source(handler, clock=clock, ttl=300.0)

    assert source.get_text(GUIDE_FILENAME) == "first"
    clock.advance(301)  # past TTL -> refetch
    assert source.get_text(GUIDE_FILENAME) == "second"


def test_http_error_raises_loud_and_specific():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    source = make_source(handler)
    with pytest.raises(SpecSourceError) as excinfo:
        source.get_guidelines()
    message = str(excinfo.value)
    assert "GUIDE.md" in message
    assert "404" in message
    assert "admin" in message


def test_transport_error_raises_loud_and_specific():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    source = make_source(handler)
    with pytest.raises(SpecSourceError) as excinfo:
        source.get_guidelines()
    message = str(excinfo.value)
    assert "unreachable" in message or "reach" in message
    assert "admin" in message


def test_get_source_is_cached_per_url():
    config = config_from_url("https://cached.test/spec/")
    first = get_source(config)
    second = get_source(config_from_url("https://cached.test/spec/"))
    assert first is second  # same URL -> same cached SpecSource (shared TTL cache)
    other = get_source(config_from_url("https://other.test/spec/"))
    assert other is not first


VALID_SPEC = """
version: 1
normalization:
  separator: "-"
parameters:
  utm_source: {store: git, required: true, enum_type: open, on_unknown: emit_and_nudge, values: [reddit]}
  utm_medium: {store: git, required: true, enum_type: closed, on_unknown: refuse, values: [social]}
  utm_campaign: {store: sheet, required: true, template_regex: "^[0-9]{4}-q[1-4]_[a-z0-9]+(-[a-z0-9]+)*$"}
  utm_content: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: "^[a-z0-9]+(-[a-z0-9]+)*$"}
  utm_term: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: "^[a-z0-9]+(-[a-z0-9]+)*$"}
"""


def test_get_spec_parses_fetched_yaml():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/spec/utm-spec.yaml"
        return httpx.Response(200, text=VALID_SPEC)

    spec = make_source(handler).get_spec()
    assert spec.version == 1
    assert spec.parameter("utm_medium").values == ("social",)


def test_get_spec_wraps_parse_error_as_specsourceerror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="- not a mapping\n")

    with pytest.raises(SpecSourceError):
        make_source(handler).get_spec()


def test_get_spec_fails_loud_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(SpecSourceError):
        make_source(handler).get_spec()


def test_failure_never_returns_a_default_body():
    """A failed read must raise, never silently yield built-in/stale content."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    source = make_source(handler)
    with pytest.raises(SpecSourceError):
        source.get_guidelines()
    # And nothing was cached, so a retry also fails loudly.
    with pytest.raises(SpecSourceError):
        source.get_guidelines()
