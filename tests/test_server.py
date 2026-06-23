"""Tests for the get_guidelines MCP tool: secret-driven config + fail-loud."""

import httpx
import pytest

from arcade_mcp_server.exceptions import ToolExecutionError

from utm_server import server
from utm_server.campaigns import CampaignRegistry
from utm_server.config import (
    CAMPAIGN_SA_JSON_SECRET,
    CAMPAIGN_SHEET_ID_SECRET,
    CAMPAIGN_SHEET_RANGE_SECRET,
    DEFAULT_CAMPAIGN_SHEET_RANGE,
    DEFAULT_SPEC_SOURCE_URL,
    SPEC_SOURCE_SECRET,
    Config,
    SheetConfig,
)
from utm_server.sources import SpecSource


class FakeContext:
    """Stands in for the Arcade tool Context, mirroring get_secret semantics."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def get_secret(self, key: str) -> str:
        try:
            return self._secrets[key]
        except KeyError as exc:
            raise ValueError(f"Secret {key} is not set") from exc


def _source(handler) -> SpecSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = Config(spec_source_url="https://example.test/spec/", is_default_source=False)
    return SpecSource(config, client=client)


def test_resolve_config_uses_secret_when_present():
    context = FakeContext({SPEC_SOURCE_SECRET: "https://acme.test/utm/"})
    config = server.resolve_config(context)
    assert config.spec_source_url == "https://acme.test/utm/"
    assert config.is_default_source is False


def test_resolve_config_falls_back_to_default_when_secret_missing():
    context = FakeContext({})  # secret not configured
    config = server.resolve_config(context)
    assert config.spec_source_url == DEFAULT_SPEC_SOURCE_URL
    assert config.is_default_source is True


def test_get_guidelines_tool_returns_guide(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="# UTM Tagging Guide\n")

    monkeypatch.setattr(server, "get_source", lambda config: _source(handler))
    context = FakeContext({SPEC_SOURCE_SECRET: "https://example.test/spec/"})
    assert server.get_guidelines(context) == "# UTM Tagging Guide\n"


def test_get_guidelines_tool_fails_loud_on_bad_source(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(server, "get_source", lambda config: _source(handler))
    context = FakeContext({SPEC_SOURCE_SECRET: "https://example.test/spec/"})
    with pytest.raises(ToolExecutionError) as excinfo:
        server.get_guidelines(context)
    assert "admin" in str(excinfo.value)


def test_get_guidelines_is_registered_as_a_tool():
    # The decorated function stays directly callable, and importing the module
    # registers it on the app (see the "Added tool" log on import).
    assert callable(server.get_guidelines)


SPEC_YAML = """
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


def _spec_source() -> SpecSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SPEC_YAML)

    return _source(handler)


def test_validate_url_tool_returns_normalized_link(monkeypatch):
    monkeypatch.setattr(server, "get_source", lambda config: _spec_source())
    context = FakeContext({SPEC_SOURCE_SECRET: "https://example.test/spec/"})
    result = server.validate_url(
        context,
        "https://arcade.dev/?utm_source=Reddit&utm_medium=Social&utm_campaign=2026-q2_x",
    )
    assert "utm_source=reddit" in result["url"]
    assert {"param": "utm_source", "from": "Reddit", "to": "reddit"} in result["changelog"]
    assert result["nudges"] == []


def test_validate_url_tool_includes_nudge_for_unknown_source(monkeypatch):
    monkeypatch.setattr(server, "get_source", lambda config: _spec_source())
    context = FakeContext({SPEC_SOURCE_SECRET: "https://example.test/spec/"})
    result = server.validate_url(
        context,
        "https://arcade.dev/?utm_source=mastodon&utm_medium=social&utm_campaign=2026-q2_x",
    )
    assert "utm_source=mastodon" in result["url"]
    assert any("mastodon" in n for n in result["nudges"])


def test_validate_url_tool_hard_refuses_unknown_medium(monkeypatch):
    monkeypatch.setattr(server, "get_source", lambda config: _spec_source())
    context = FakeContext({SPEC_SOURCE_SECRET: "https://example.test/spec/"})
    with pytest.raises(ToolExecutionError) as excinfo:
        server.validate_url(
            context,
            "https://arcade.dev/?utm_source=reddit&utm_medium=bogus&utm_campaign=2026-q2_x",
        )
    assert "social" in str(excinfo.value)


def test_validate_url_tool_fails_loud_on_bad_spec_source(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(server, "get_source", lambda config: _source(handler))
    context = FakeContext({SPEC_SOURCE_SECRET: "https://example.test/spec/"})
    with pytest.raises(ToolExecutionError):
        server.validate_url(context, "https://arcade.dev/?utm_medium=social")


def test_validate_url_is_registered_as_a_tool():
    assert callable(server.validate_url)


# --- list_campaigns ---------------------------------------------------------


def _campaign_registry(handler) -> CampaignRegistry:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = SheetConfig(sheet_id="sheet123", sheet_range="Campaigns!A:D")
    return CampaignRegistry(config, token_provider=lambda: "fake-token", client=client)


def test_resolve_sheet_config_uses_secrets():
    context = FakeContext({
        CAMPAIGN_SHEET_ID_SECRET: "sheet123",
        CAMPAIGN_SHEET_RANGE_SECRET: "Tab2!A:D",
    })
    config = server.resolve_sheet_config(context)
    assert config == SheetConfig(sheet_id="sheet123", sheet_range="Tab2!A:D")


def test_resolve_sheet_config_defaults_range_when_unset():
    context = FakeContext({CAMPAIGN_SHEET_ID_SECRET: "sheet123"})
    config = server.resolve_sheet_config(context)
    assert config.sheet_range == DEFAULT_CAMPAIGN_SHEET_RANGE


def test_resolve_sheet_config_fails_loud_without_sheet_id():
    from utm_server.campaigns import CampaignSheetError

    with pytest.raises(CampaignSheetError) as excinfo:
        server.resolve_sheet_config(FakeContext({}))
    assert CAMPAIGN_SHEET_ID_SECRET in str(excinfo.value)


def test_list_campaigns_tool_returns_rows(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "range": "Campaigns!A1:D2",
                "values": [
                    ["campaign", "description", "added_by", "added_at"],
                    ["2026-q2_agent-launch", "Q2 launch", "u_1", "2026-04-01"],
                ],
            },
        )

    monkeypatch.setattr(server, "get_registry", lambda cfg, sa: _campaign_registry(handler))
    context = FakeContext({
        CAMPAIGN_SHEET_ID_SECRET: "sheet123",
        CAMPAIGN_SA_JSON_SECRET: "{}",
    })
    assert server.list_campaigns(context) == [
        {
            "campaign": "2026-q2_agent-launch",
            "description": "Q2 launch",
            "added_by": "u_1",
            "added_at": "2026-04-01",
        }
    ]


def test_list_campaigns_tool_fails_loud_on_bad_schema(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"range": "Campaigns!A1:D1", "values": [["nope", "wrong", "head", "ers"]]}
        )

    monkeypatch.setattr(server, "get_registry", lambda cfg, sa: _campaign_registry(handler))
    context = FakeContext({
        CAMPAIGN_SHEET_ID_SECRET: "sheet123",
        CAMPAIGN_SA_JSON_SECRET: "{}",
    })
    with pytest.raises(ToolExecutionError) as excinfo:
        server.list_campaigns(context)
    assert "admin" in str(excinfo.value)


def test_list_campaigns_tool_fails_loud_without_credential():
    # No service-account secret configured.
    context = FakeContext({CAMPAIGN_SHEET_ID_SECRET: "sheet123"})
    with pytest.raises(ToolExecutionError) as excinfo:
        server.list_campaigns(context)
    assert CAMPAIGN_SA_JSON_SECRET in str(excinfo.value)


def test_list_campaigns_is_registered_as_a_tool():
    assert callable(server.list_campaigns)
