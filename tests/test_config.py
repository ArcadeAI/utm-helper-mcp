"""Tests for pointers-only configuration."""

from utm_server.config import (
    DEFAULT_SPEC_SOURCE_URL,
    SPEC_SOURCE_URL_ENV,
    file_url,
    load_config,
)


def test_unset_env_uses_default_seed():
    config = load_config(env={})
    assert config.is_default_source is True
    assert config.spec_source_url == DEFAULT_SPEC_SOURCE_URL  # already ends in "/"


def test_blank_env_uses_default_seed():
    config = load_config(env={SPEC_SOURCE_URL_ENV: "   "})
    assert config.is_default_source is True
    assert config.spec_source_url == DEFAULT_SPEC_SOURCE_URL


def test_env_override_wins():
    config = load_config(
        env={SPEC_SOURCE_URL_ENV: "https://example.test/spec/"}
    )
    assert config.is_default_source is False
    assert config.spec_source_url == "https://example.test/spec/"


def test_trailing_slash_is_normalized():
    config = load_config(env={SPEC_SOURCE_URL_ENV: "https://example.test/spec"})
    assert config.spec_source_url == "https://example.test/spec/"


def test_file_url_joins_base_and_filename():
    config = load_config(env={SPEC_SOURCE_URL_ENV: "https://example.test/spec"})
    assert file_url(config, "GUIDE.md") == "https://example.test/spec/GUIDE.md"
    # A leading slash on the filename does not escape the base path.
    assert file_url(config, "/GUIDE.md") == "https://example.test/spec/GUIDE.md"
