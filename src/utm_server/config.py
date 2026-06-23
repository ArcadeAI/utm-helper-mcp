"""Pointers-only configuration for the UTM Helper MCP server.

Configuration says *where to look* for the authoritative spec — never how the
server behaves. All behavior (enums, shape rules, casing) lives in the spec repo
(``GUIDE.md`` / ``utm-spec.yaml``) and changes only by reviewed PR. The single
knob here is the raw base URL of that Git spec source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

#: Environment variable holding the raw base URL of the Git spec source.
SPEC_SOURCE_URL_ENV = "UTM_SPEC_SOURCE_URL"

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
        is_default_source: ``True`` when no source was configured and the
            shipped default seed is in use (the announced first-run case).
    """

    spec_source_url: str
    is_default_source: bool


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    """Build :class:`Config` from the environment.

    An unset or blank ``UTM_SPEC_SOURCE_URL`` falls back to the announced
    default seed and flips ``is_default_source``. The base URL is normalized to
    end in a single ``/`` so file names join predictably.
    """
    raw = env.get(SPEC_SOURCE_URL_ENV, "").strip()
    if raw:
        return Config(spec_source_url=_with_trailing_slash(raw), is_default_source=False)
    return Config(
        spec_source_url=_with_trailing_slash(DEFAULT_SPEC_SOURCE_URL),
        is_default_source=True,
    )


def file_url(config: Config, filename: str) -> str:
    """Join the spec source base URL with a spec file name (e.g. ``GUIDE.md``)."""
    return config.spec_source_url + filename.lstrip("/")


def _with_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"
