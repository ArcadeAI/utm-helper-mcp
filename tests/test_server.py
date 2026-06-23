"""Tests for the get_guidelines MCP tool end of the path."""

import httpx
import pytest

from arcade_mcp_server.exceptions import ToolExecutionError

from utm_server import server
from utm_server.config import Config
from utm_server.sources import SpecSource


def _source(handler) -> SpecSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = Config(spec_source_url="https://example.test/spec/", is_default_source=False)
    return SpecSource(config, client=client)


def test_get_guidelines_tool_returns_guide(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="# UTM Tagging Guide\n")

    monkeypatch.setattr(server, "get_default_source", lambda: _source(handler))
    assert server.get_guidelines() == "# UTM Tagging Guide\n"


def test_get_guidelines_tool_fails_loud_on_bad_source(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(server, "get_default_source", lambda: _source(handler))
    with pytest.raises(ToolExecutionError) as excinfo:
        server.get_guidelines()
    assert "admin" in str(excinfo.value)


def test_get_guidelines_is_registered_as_a_tool():
    # The decorated function stays directly callable, and importing the module
    # registers it on the app (see the "Added tool" log on import).
    assert callable(server.get_guidelines)
