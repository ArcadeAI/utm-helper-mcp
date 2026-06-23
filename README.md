# UTM Helper MCP server

An [Arcade](https://arcade.dev) MCP server that helps teams produce **consistent
UTM-tagged links** by reading an authoritative, version-controlled UTM spec and
exposing it through MCP tools.

This repo is both the **spec source of truth** ([`GUIDE.md`](./GUIDE.md),
[`utm-spec.yaml`](./utm-spec.yaml)) and the **server** that serves it. See the
[PRD](https://github.com/ArcadeAI/utm-helper-mcp/issues/1) for the full design.

> **Status:** first tracer bullet. The only tool so far is `get_guidelines()`
> (fetch the guide from the configured Git source). `build_url`,
> `validate_and_normalize`, and the campaign tools land in later issues.

## Tools

| Tool | Description |
|---|---|
| `get_guidelines()` | Returns the human-readable UTM guide (`GUIDE.md`) fetched from the configured Git spec source. |

## Setup (admin)

Requires Python ≥ 3.10 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev        # install runtime + dev deps into .venv
```

### Configuration — pointers only, via an Arcade secret

Configuration only says **where to look** for the spec; it never encodes
behavior. All behavior (enums, shape rules, casing) lives in the spec repo and
changes by reviewed PR.

The single pointer is provided as the Arcade **tool secret**
`UTM_SPEC_SOURCE_URL` — it is **not** hard-coded in the server. The tool reads it
from its injected `Context` at call time (`context.get_secret(...)`).

| Secret | Meaning |
|---|---|
| `UTM_SPEC_SOURCE_URL` | Raw base URL of the Git spec source. The server appends file names (e.g. `GUIDE.md`), so it must serve **raw** file contents. Works with GitHub raw, GitLab raw, or any self-hosted mirror. A trailing `/` is added if omitted. |

Set it where it belongs for your environment:

- **Production:** configure it on the [Arcade dashboard](https://api.arcade.dev/dashboard),
  or with `arcade secret set UTM_SPEC_SOURCE_URL <url>`.
- **Local dev:** put it in `.env` (copy [`.env.example`](./.env.example)) — Arcade
  discovers `.env` and injects the secret into the tool `Context`.

**First run / no config:** if the secret is unset, the tool uses the opinionated
**default seed** shipped in this repo
(`https://raw.githubusercontent.com/ArcadeAI/utm-helper-mcp/main/`) and **logs a
warning**. This is the *only* case where a default is used — see Failure
behavior below.

### Run

```bash
# stdio (Claude Desktop, CLI clients)
uv run src/utm_server/server.py

# http (Cursor, VS Code)
uv run src/utm_server/server.py http   # serves on http://127.0.0.1:8000/mcp/
```

## Caching

Successful spec reads are cached **in memory for 5 minutes**
(`SPEC_CACHE_TTL_SECONDS` in [`sources.py`](./src/utm_server/sources.py)). The
spec is slow-changing (reviewed-PR cadence), so this trades a little staleness
for far fewer network round-trips. The cache is per-process and per-file; a
restart clears it. The TTL is a code constant, not configuration, to keep config
strictly pointers-only.

## Failure behavior — fail loud, never silently default

If the spec source is unreachable, returns a non-2xx status, or the file is
missing, the tool **raises a specific error** naming the URL and failure and
telling the user to contact the admin. It **never** falls back to a built-in or
stale guide — a misconfigured deploy must look broken, not quietly serve the
wrong content. The single announced exception is the first-run default seed
*source* above (which is still fetched over the network like any other source).

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run mypy src        # type-check
```
