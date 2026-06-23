#!/usr/bin/env python3
"""UTM Helper MCP server.

Helps teams produce consistent UTM-tagged links by reading an authoritative,
version-controlled spec (Git) and exposing it through MCP tools. This first
tracer bullet ships a single tool, ``get_guidelines``, which returns the guide
from the configured Git spec source.
"""

import sys
from typing import Annotated

from arcade_mcp_server import MCPApp
from arcade_mcp_server.exceptions import ToolExecutionError

from utm_server.sources import SpecSourceError, get_default_source

app = MCPApp(name="utm_server", version="0.1.0")


@app.tool
def get_guidelines() -> Annotated[
    str,
    "The UTM tagging guide (GUIDE.md) fetched from the configured Git spec source.",
]:
    """Return the authoritative UTM tagging guide.

    Fetches ``GUIDE.md`` from the configured Git spec source (briefly cached).
    If the source is unreachable or misconfigured, this fails loud with a
    specific error and does NOT fall back to any built-in guide — fix the
    configuration or contact the admin.
    """
    try:
        return get_default_source().get_guidelines()
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
