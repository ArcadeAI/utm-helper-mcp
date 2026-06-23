"""Tests for the validate_and_normalize engine — one per behavior branch."""

import pytest

from utm_server.engine import Fixup, ValidationRefused, validate_and_normalize
from utm_server.spec import parse_spec

SPEC = parse_spec(
    """
version: 1
normalization:
  separator: "-"
parameters:
  utm_source: {store: git, required: true, enum_type: open, on_unknown: emit_and_nudge, values: [reddit, linkedin, x]}
  utm_medium: {store: git, required: true, enum_type: closed, on_unknown: refuse, values: [social, email, cpc]}
  utm_campaign: {store: sheet, required: true, template_regex: "^[0-9]{4}-q[1-4]_[a-z0-9]+(-[a-z0-9]+)*$"}
  utm_content: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: "^[a-z0-9]+(-[a-z0-9]+)*$"}
  utm_term: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: "^[a-z0-9]+(-[a-z0-9]+)*$"}
"""
)


def _valid_url(**overrides) -> str:
    params = {
        "utm_source": "reddit",
        "utm_medium": "social",
        "utm_campaign": "2026-q2_agent-launch",
    }
    params.update(overrides)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://arcade.dev/?{query}"


def test_clean_url_passes_unchanged():
    result = validate_and_normalize(_valid_url(), SPEC)
    assert result.changelog == []
    assert result.nudges == []
    assert "utm_source=reddit" in result.url
    assert "utm_medium=social" in result.url
    assert "utm_campaign=2026-q2_agent-launch" in result.url


def test_messy_url_returns_normalized_url_and_changelog():
    url = "https://arcade.dev/?utm_source=Reddit&utm_medium=Social&utm_campaign=2026-Q2_Agent%20Launch&utm_content=Header%20CTA"
    result = validate_and_normalize(url, SPEC)
    assert "utm_source=reddit" in result.url
    assert "utm_campaign=2026-q2_agent-launch" in result.url
    assert "utm_content=header-cta" in result.url
    # Every messy field is reported in the changelog.
    changed = {f.param for f in result.changelog}
    assert changed == {"utm_source", "utm_medium", "utm_campaign", "utm_content"}
    assert Fixup("utm_content", "Header CTA", "header-cta") in result.changelog


def test_non_utm_params_are_preserved():
    url = _valid_url() + "&ref=homepage&fbclid=abc123"
    result = validate_and_normalize(url, SPEC)
    assert "ref=homepage" in result.url
    assert "fbclid=abc123" in result.url


def test_unknown_source_emits_link_with_nudge():
    result = validate_and_normalize(_valid_url(utm_source="mastodon"), SPEC)
    # The link is still produced...
    assert "utm_source=mastodon" in result.url
    # ...with a nudge to add the source to the spec repo.
    assert len(result.nudges) == 1
    assert "mastodon" in result.nudges[0]
    assert "spec repo" in result.nudges[0]


def test_unknown_medium_hard_refuses_with_values_and_suggestion():
    with pytest.raises(ValidationRefused) as excinfo:
        validate_and_normalize(_valid_url(utm_medium="paid-social"), SPEC)
    message = str(excinfo.value)
    assert "social" in message  # valid values shown
    assert "email" in message
    assert "Closest match" in message  # closest suggestion offered
    assert "no link" in message.lower()  # nothing emitted


def test_unknown_medium_emits_nothing_even_with_other_issues():
    # The exception path returns no result object at all.
    with pytest.raises(ValidationRefused):
        validate_and_normalize(_valid_url(utm_medium="bogus"), SPEC)


def test_malformed_campaign_hard_errors():
    with pytest.raises(ValidationRefused) as excinfo:
        validate_and_normalize(_valid_url(utm_campaign="agentlaunch"), SPEC)
    assert "campaign" in str(excinfo.value).lower()
    assert "template" in str(excinfo.value).lower()


def test_unknown_campaign_refused_when_registry_supplied():
    known = {"2026-q1_existing"}
    with pytest.raises(ValidationRefused) as excinfo:
        validate_and_normalize(
            _valid_url(utm_campaign="2026-q2_agent-launch"), SPEC, known_campaigns=known
        )
    assert "registry" in str(excinfo.value).lower()


def test_known_campaign_passes_when_registry_supplied():
    known = {"2026-q2_agent-launch"}
    result = validate_and_normalize(
        _valid_url(utm_campaign="2026-q2_agent-launch"), SPEC, known_campaigns=known
    )
    assert "utm_campaign=2026-q2_agent-launch" in result.url


def test_content_and_term_are_shape_normalized():
    url = _valid_url(utm_medium="cpc", utm_content="Variant%20A", utm_term="MCP%20Server")
    result = validate_and_normalize(url, SPEC)
    assert "utm_content=variant-a" in result.url
    assert "utm_term=mcp-server" in result.url


def test_missing_required_parameter_refuses():
    url = "https://arcade.dev/?utm_source=reddit&utm_medium=social"  # no campaign
    with pytest.raises(ValidationRefused) as excinfo:
        validate_and_normalize(url, SPEC)
    assert "utm_campaign" in str(excinfo.value)


def test_uppercase_param_key_is_normalized_and_logged():
    url = "https://arcade.dev/?UTM_Source=reddit&utm_medium=social&utm_campaign=2026-q2_x"
    result = validate_and_normalize(url, SPEC)
    assert "utm_source=reddit" in result.url
    assert any(f.param == "utm_source" for f in result.changelog)
