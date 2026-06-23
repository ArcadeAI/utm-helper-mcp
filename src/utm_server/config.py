"""Pointers-only configuration for the UTM Helper MCP server.

Configuration says *where to look* for the authoritative spec — never how the
server behaves. All behavior (enums, shape rules, casing) lives in the spec repo
(``GUIDE.md`` / ``utm-spec.yaml``) and changes only by reviewed PR. The single
knob is the raw base URL of that Git spec source.

That URL is supplied as an **Arcade tool secret** (configured on the Arcade
dashboard, or via ``.env`` / env var for local dev) and injected into the tool
``Context`` at call time — it is never hard-coded in the server. See
:mod:`utm_server.server` for how the secret is read.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Name of the Arcade secret holding the raw base URL of the Git spec source.
SPEC_SOURCE_SECRET = "UTM_SPEC_SOURCE_URL"

#: Arcade secret holding the campaign-registry Google Sheet ID (a pointer).
CAMPAIGN_SHEET_ID_SECRET = "UTM_CAMPAIGN_SHEET_ID"

#: Arcade secret holding the Sheet's A1 tab/range to read (a pointer). Optional;
#: falls back to :data:`DEFAULT_CAMPAIGN_SHEET_RANGE` when unset.
CAMPAIGN_SHEET_RANGE_SECRET = "UTM_CAMPAIGN_SHEET_RANGE"

#: Arcade secret holding the shared **service-account** credential (the full
#: Google service-account key JSON). This is the server-side credential the tool
#: uses to read the Sheet — end users need no direct Google/Sheet access.
CAMPAIGN_SA_JSON_SECRET = "UTM_CAMPAIGN_SA_JSON"

#: Default tab/range when the range secret is unset: the whole ``Campaigns`` tab,
#: columns A–D (campaign, description, added_by, added_at). A pointer default
#: only — never silently substitutes a *sheet* (there is no shipped default
#: registry, so a missing Sheet ID fails loud).
DEFAULT_CAMPAIGN_SHEET_RANGE = "Campaigns!A:D"

#: The announced first-run / no-config default: the opinionated seed spec that
#: ships in this repo. Using it logs a warning (see ``sources``) so a
#: misconfigured deploy is never mistaken for a working one.
DEFAULT_SPEC_SOURCE_URL = (
    "https://raw.githubusercontent.com/ArcadeAI/utm-helper-mcp/main/"
)


@dataclass(frozen=True)
class Config:
    """Resolved, pointers-only server configuration.

    Attributes:
        spec_source_url: Raw base URL of the Git spec source, always ending in
            ``/``. File names are appended to it (see :func:`file_url`).
        is_default_source: ``True`` when no source secret was configured and the
            shipped default seed is in use (the announced first-run case).
    """

    spec_source_url: str
    is_default_source: bool


def config_from_url(url: str | None) -> Config:
    """Build :class:`Config` from a spec-source URL (e.g. an Arcade secret).

    A missing or blank URL falls back to the announced default seed and flips
    ``is_default_source``. The base URL is normalized to end in a single ``/``
    so file names join predictably.
    """
    cleaned = (url or "").strip()
    if cleaned:
        return Config(spec_source_url=_with_trailing_slash(cleaned), is_default_source=False)
    return Config(
        spec_source_url=_with_trailing_slash(DEFAULT_SPEC_SOURCE_URL),
        is_default_source=True,
    )


def file_url(config: Config, filename: str) -> str:
    """Join the spec source base URL with a spec file name (e.g. ``GUIDE.md``)."""
    return config.spec_source_url + filename.lstrip("/")


@dataclass(frozen=True)
class SheetConfig:
    """Resolved, pointers-only configuration for the campaign-registry Sheet.

    Attributes:
        sheet_id: The Google Sheet ID (the long token in the Sheet's URL).
        sheet_range: The A1 tab/range to read (e.g. ``Campaigns!A:D``).
    """

    sheet_id: str
    sheet_range: str


def sheet_config_from(sheet_id: str, sheet_range: str | None) -> SheetConfig:
    """Build :class:`SheetConfig` from the Sheet pointer secrets.

    A blank range falls back to :data:`DEFAULT_CAMPAIGN_SHEET_RANGE`. The Sheet
    ID has no default — a missing/blank ID is a misconfiguration the caller must
    surface loudly (there is no shipped default registry to fall back to).
    """
    cleaned_range = (sheet_range or "").strip() or DEFAULT_CAMPAIGN_SHEET_RANGE
    return SheetConfig(sheet_id=sheet_id.strip(), sheet_range=cleaned_range)


def _with_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"
