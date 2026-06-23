#!/usr/bin/env python3
"""UTM Helper MCP server.

Helps teams produce consistent UTM-tagged links by reading an authoritative,
version-controlled spec (Git) and exposing it through MCP tools. This first
tracer bullet ships a single tool, ``get_guidelines``, which returns the guide
from the configured Git spec source.
"""

import sys
from typing import Annotated

from arcade_mcp_server import Context, MCPApp
from arcade_mcp_server.exceptions import ToolExecutionError

from utm_server.config import SPEC_SOURCE_SECRET, Config, config_from_url
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
