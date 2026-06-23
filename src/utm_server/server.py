#!/usr/bin/env python3
"""UTM Helper MCP server.

Helps teams produce consistent UTM-tagged links by reading an authoritative,
version-controlled spec (Git) and exposing it through MCP tools. This first
tracer bullet ships a single tool, ``get_guidelines``, which returns the guide
from the configured Git spec source.
"""

import sys
from typing import Annotated, TypedDict

from arcade_mcp_server import Context, MCPApp
from arcade_mcp_server.exceptions import ToolExecutionError

from utm_server.config import SPEC_SOURCE_SECRET, Config, config_from_url
from utm_server.engine import ValidationRefused, validate_and_normalize
from utm_server.sources import SpecSourceError, get_source

app = MCPApp(name="utm_server", version="0.1.0")


def resolve_config(context: Context) -> Config:
    """Resolve pointers-only config from the injected Arcade tool secret.

    The spec source URL is configured as the ``UTM_SPEC_SOURCE_URL`` secret on
    the Arcade dashboard (or in ``.env`` for local dev) and injected into the
    tool ``Context`` at call time — never hard-coded here. A missing secret
    falls back to the announced first-run default seed.
    """
    try:
        url: str | None = context.get_secret(SPEC_SOURCE_SECRET)
    except ValueError:
        # Secret not configured (e.g. local dev) -> announced default seed.
        url = None
    return config_from_url(url)


# app.tool() lacks @overload for the factory form, so mypy mis-infers Never (upstream).
@app.tool(requires_secrets=[SPEC_SOURCE_SECRET])  # type: ignore[arg-type]
def get_guidelines(context: Context) -> Annotated[
    str,
    "The UTM tagging guide (GUIDE.md) fetched from the configured Git spec source.",
]:
    """Return the authoritative UTM tagging guide.

    Fetches ``GUIDE.md`` from the Git spec source pointed at by the
    ``UTM_SPEC_SOURCE_URL`` secret (briefly cached). If the source is
    unreachable or misconfigured, this fails loud with a specific error and does
    NOT fall back to any built-in guide — fix the configuration or contact the
    admin.
    """
    config = resolve_config(context)
    try:
        return get_source(config).get_guidelines()
    except SpecSourceError as exc:
        # Surface loudly to the agent/user rather than emitting a silent default.
        raise ToolExecutionError(str(exc)) from exc


class ValidatedLink(TypedDict):
    """The structured result of a successful ``validate_url`` call."""

    url: str
    changelog: list[dict[str, str]]
    nudges: list[str]


# app.tool() lacks @overload for the factory form, so mypy mis-infers Never (upstream).
@app.tool(requires_secrets=[SPEC_SOURCE_SECRET])  # type: ignore[arg-type]
def validate_url(
    context: Context,
    url: Annotated[str, "The URL whose UTM parameters should be normalized and validated."],
) -> Annotated[
    ValidatedLink,
    "The normalized URL, a changelog of fixups applied, and any soft nudges.",
]:
    """Normalize and validate a URL's UTM parameters — the mandatory last hop.

    Reads the authoritative spec from the configured Git source and applies it
    end-to-end: every UTM value is normalized (lowercase, hyphens, no spaces) and
    validated with the spec's per-field behavior. An unknown ``utm_source`` still
    returns the normalized link with a nudge to add it to the spec repo; an
    unknown ``utm_medium`` or a malformed ``utm_campaign`` hard-refuses (raises)
    and emits no link; ``utm_content``/``utm_term`` are shape-normalized.

    Fails loud if the spec source is unreachable or misconfigured — it never
    falls back to a built-in spec.
    """
    config = resolve_config(context)
    try:
        spec = get_source(config).get_spec()
        result = validate_and_normalize(url, spec)
    except (SpecSourceError, ValidationRefused) as exc:
        # Spec failures and hard-refusals both surface loudly; a refused link is
        # never emitted.
        raise ToolExecutionError(str(exc)) from exc

    return ValidatedLink(
        url=result.url,
        changelog=[
            {"param": f.param, "from": f.original, "to": f.normalized}
            for f in result.changelog
        ],
        nudges=result.nudges,
    )


if __name__ == "__main__":
    # Transport: "stdio" (default) for Claude Desktop / CLI; "http" for
    # Cursor / VS Code. See the README for details.
    requested = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if requested == "http":
        app.run(transport="http", host="127.0.0.1", port=8000)
    elif requested == "stdio":
        app.run(transport="stdio", host="127.0.0.1", port=8000)
    else:
        sys.exit(f"Unknown transport {requested!r}; use 'stdio' or 'http'.")
