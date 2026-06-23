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


def _with_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"
