"""Tests for spec parsing and the deterministic normalization transform."""

import pytest

from utm_server.spec import (
    SPEC_FILENAME,
    SpecParseError,
    normalize_campaign,
    normalize_value,
    parse_spec,
)

MINIMAL_SPEC = """
version: 1
normalization:
  separator: "-"
parameters:
  utm_source: {store: git, required: true, enum_type: open, on_unknown: emit_and_nudge, values: [reddit, linkedin]}
  utm_medium: {store: git, required: true, enum_type: closed, on_unknown: refuse, values: [social, email]}
  utm_campaign: {store: sheet, required: true, template_regex: "^[0-9]{4}-q[1-4]_[a-z0-9]+(-[a-z0-9]+)*$"}
  utm_content: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: "^[a-z0-9]+(-[a-z0-9]+)*$"}
  utm_term: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: "^[a-z0-9]+(-[a-z0-9]+)*$"}
"""


def test_parses_the_shipped_spec():
    # The real spec in the repo root must parse and expose the five params.
    with open(SPEC_FILENAME) as fh:
        spec = parse_spec(fh.read())
    assert spec.version == 1
    assert spec.separator == "-"
    assert "social" in spec.parameter("utm_medium").values
    assert spec.parameter("utm_medium").enum_type == "closed"
    assert spec.parameter("utm_source").on_unknown == "emit_and_nudge"
    assert spec.parameter("utm_campaign").template_regex is not None


def test_parse_minimal_spec_fields():
    spec = parse_spec(MINIMAL_SPEC)
    medium = spec.parameter("utm_medium")
    assert medium.required is True
    assert medium.on_unknown == "refuse"
    assert medium.values == ("social", "email")
    assert spec.parameter("utm_content").required is False


def test_invalid_yaml_raises_specparseerror():
    with pytest.raises(SpecParseError):
        parse_spec("version: 1\n  bad: : indentation")


def test_non_mapping_top_level_raises():
    with pytest.raises(SpecParseError):
        parse_spec("- just\n- a\n- list\n")


def test_missing_required_parameter_raises():
    spec_text = MINIMAL_SPEC.replace(
        "  utm_term: {store: git, required: false, enum_type: free, on_unknown: normalize, shape_regex: \"^[a-z0-9]+(-[a-z0-9]+)*$\"}\n",
        "",
    )
    with pytest.raises(SpecParseError) as excinfo:
        parse_spec(spec_text)
    assert "utm_term" in str(excinfo.value)


def test_missing_normalization_block_raises():
    with pytest.raises(SpecParseError):
        parse_spec("version: 1\nparameters: {}\n")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Reddit", "reddit"),
        ("  Header CTA  ", "header-cta"),
        ("variant_a", "variant-a"),
        ("AI  Agent   Tools", "ai-agent-tools"),
        ("foo!!!bar", "foobar"),
        ("--double--", "double"),
        ("Header—CTA", "headercta"),  # em-dash is stripped (not [a-z0-9-])
        ("already-clean", "already-clean"),
    ],
)
def test_normalize_value(raw, expected):
    assert normalize_value(raw) == expected


def test_normalize_value_is_idempotent():
    once = normalize_value("Some  Messy_Value!!")
    assert normalize_value(once) == once


def test_normalize_campaign_preserves_structural_underscore():
    assert normalize_campaign("2026-Q2_Agent Launch") == "2026-q2_agent-launch"
    # Only the first underscore is structural; later ones become separators.
    assert normalize_campaign("2026-q2_agent_launch") == "2026-q2_agent-launch"


def test_normalize_campaign_without_underscore_is_plain_kebab():
    # No structural underscore -> normalized whole (and will fail template later).
    assert normalize_campaign("Agent Launch") == "agent-launch"
