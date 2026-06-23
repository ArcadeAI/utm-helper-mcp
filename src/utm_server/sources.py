"""Read the authoritative spec from its Git source — cached briefly, fail-loud.

The spec is slow-changing, so successful reads are cached for a short TTL. Any
read failure (unreachable host, non-2xx, transport error) raises
:class:`SpecSourceError` with a specific, admin-facing message. The fetcher
NEVER falls back to a default body on error — a misconfigured deploy must look
broken, not quietly serve stale or built-in content. The only "default" is the
announced first-run seed *source URL* (see :mod:`utm_server.config`), which is
still fetched over the network like any other source.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

from .config import Config, file_url
from .spec import SPEC_FILENAME, Spec, SpecParseError, parse_spec

logger = logging.getLogger(__name__)

#: How long a successfully fetched spec file is served from cache, in seconds.
#: The spec is slow-changing (reviewed-PR cadence), so a brief cache trades a
#: little staleness for far fewer network round-trips. Kept as a module
#: constant rather than config to honor the "pointers only" config contract.
SPEC_CACHE_TTL_SECONDS = 300

#: The human-readable guide served by ``get_guidelines``.
GUIDE_FILENAME = "GUIDE.md"


class SpecSourceError(Exception):
    """A spec file could not be read from the configured Git source.

    The message is intended to surface directly to the user/agent: it names the
    URL and failure and tells them to contact the admin.
    """


class SpecSource:
    """Fetches spec files from the configured Git source with a brief TTL cache.

    Args:
        config: Resolved pointers-only configuration.
        client: HTTP client to use. Injectable for tests (e.g. with an
            ``httpx.MockTransport``); defaults to a real ``httpx.Client``.
        clock: Monotonic time source in seconds. Injectable for tests.
        ttl: Cache lifetime in seconds for a successfully fetched file.
    """

    def __init__(
        self,
        config: Config,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = SPEC_CACHE_TTL_SECONDS,
    ) -> None:
        self._config = config
        self._client = client if client is not None else httpx.Client(timeout=10.0)
        self._clock = clock
        self._ttl = ttl
        # filename -> (fetched_at, text)
        self._cache: dict[str, tuple[float, str]] = {}

        if config.is_default_source:
            logger.warning(
                "UTM_SPEC_SOURCE_URL is not set; using the shipped default seed "
                "spec at %s. Set UTM_SPEC_SOURCE_URL to point at your own spec "
                "repo for production use.",
                config.spec_source_url,
            )

    def get_text(self, filename: str) -> str:
        """Return the contents of ``filename`` from the spec source.

        Serves from cache when a previous fetch is still within the TTL.
        Raises :class:`SpecSourceError` on any read failure — never returns a
        fallback body.
        """
        cached = self._cache.get(filename)
        if cached is not None and (self._clock() - cached[0]) < self._ttl:
            return cached[1]

        url = file_url(self._config, filename)
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise SpecSourceError(
                f"Couldn't reach the UTM spec source at {url}: {exc}. "
                "The spec source may be unreachable or misconfigured — "
                "contact the admin."
            ) from exc

        if response.status_code != httpx.codes.OK:
            raise SpecSourceError(
                f"Couldn't read the UTM spec at {url}: HTTP {response.status_code}. "
                "The spec source may be misconfigured (wrong URL, missing file, "
                "or private repo) — contact the admin."
            )

        text = response.text
        self._cache[filename] = (self._clock(), text)
        return text

    def get_guidelines(self) -> str:
        """Return the human-readable UTM guide (``GUIDE.md``)."""
        return self.get_text(GUIDE_FILENAME)

    def get_spec(self) -> Spec:
        """Return the parsed, structured spec (``utm-spec.yaml``).

        Fetches (with the same brief TTL cache as any spec file) and parses the
        machine-readable spec. A parse failure is surfaced as
        :class:`SpecSourceError` so callers' existing fail-loud handling catches
        it alongside fetch failures — never a built-in default.
        """
        text = self.get_text(SPEC_FILENAME)
        try:
            return parse_spec(text)
        except SpecParseError as exc:
            raise SpecSourceError(str(exc)) from exc


_sources: dict[str, SpecSource] = {}


def get_source(config: Config) -> SpecSource:
    """Return a process-wide :class:`SpecSource` for ``config``'s source URL.

    Cached per source URL so the brief spec cache persists across tool calls
    within a running server, even though the URL arrives per-call via the tool
    secret (its value is stable across calls).
    """
    source = _sources.get(config.spec_source_url)
    if source is None:
        source = SpecSource(config)
        _sources[config.spec_source_url] = source
    return source
