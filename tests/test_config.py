"""Tests for pointers-only configuration."""

from utm_server.config import (
    DEFAULT_SPEC_SOURCE_URL,
    config_from_url,
    file_url,
)


def test_none_url_uses_default_seed():
    config = config_from_url(None)
    assert config.is_default_source is True
    assert config.spec_source_url == DEFAULT_SPEC_SOURCE_URL  # already ends in "/"


def test_blank_url_uses_default_seed():
    config = config_from_url("   ")
    assert config.is_default_source is True
    assert config.spec_source_url == DEFAULT_SPEC_SOURCE_URL


def test_configured_url_wins():
    config = config_from_url("https://example.test/spec/")
    assert config.is_default_source is False
    assert config.spec_source_url == "https://example.test/spec/"


def test_trailing_slash_is_normalized():
    config = config_from_url("https://example.test/spec")
    assert config.spec_source_url == "https://example.test/spec/"


def test_file_url_joins_base_and_filename():
    config = config_from_url("https://example.test/spec")
    assert file_url(config, "GUIDE.md") == "https://example.test/spec/GUIDE.md"
    # A leading slash on the filename does not escape the base path.
    assert file_url(config, "/GUIDE.md") == "https://example.test/spec/GUIDE.md"
