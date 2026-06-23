# UTM Helper MCP server

An [Arcade](https://arcade.dev) MCP server that helps teams produce **consistent
UTM-tagged links** by reading an authoritative, version-controlled UTM spec and
exposing it through MCP tools.

This repo is both the **spec source of truth** ([`GUIDE.md`](./GUIDE.md),
[`utm-spec.yaml`](./utm-spec.yaml)) and the **server** that serves it. See the
[PRD](https://github.com/ArcadeAI/utm-helper-mcp/issues/1) for the full design.

> **Status:** in progress. `get_guidelines()` and `validate_url()` are
> implemented. `build_url` and the campaign-registry tools land in later issues.

## Tools

| Tool | Description |
|---|---|
| `get_guidelines()` | Returns the human-readable UTM guide (`GUIDE.md`) fetched from the configured Git spec source. |
| `validate_url(url)` | The mandatory last hop: normalizes a URL's UTM parameters against the spec and validates them, returning the normalized URL, a changelog of fixups, and any soft nudges. |

### `validate_url` — normalize + validate (the last hop)

`validate_url` reads the structured spec (`utm-spec.yaml`) from the configured
Git source and applies it **end-to-end** to a URL:

1. **Normalize** every UTM value deterministically (lowercase, hyphen-separated,
   no spaces; the structural `_` in `utm_campaign` is preserved). Each change is
   reported in a `changelog`.
2. **Validate**, with per-field behavior asymmetry straight from the spec:

   | Param | On unknown value |
   |---|---|
   | `utm_source` (open enum) | Emits the normalized link **+ a nudge** to add the source to the spec repo. |
   | `utm_medium` (closed enum) | **Hard refuse** (raises): shows the valid set + closest suggestion; **no link is emitted**. |
   | `utm_campaign` (sheet) | Must match the `YYYY-qN_kebab-slug` template; a malformed name **hard-errors**. Registry membership is checked once the campaign registry lands. |
   | `utm_content` / `utm_term` (free) | Always shape-normalized; never refused. |

A missing **required** parameter (`utm_source`, `utm_medium`, `utm_campaign`)
also hard-refuses. Non-UTM query params are passed through untouched.

On success it returns `{ "url", "changelog": [{param, from, to}, ...], "nudges": [...] }`.
Hard refusals and spec-source failures surface as loud tool errors — it never
falls back to a built-in spec.

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
