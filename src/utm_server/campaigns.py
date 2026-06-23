"""Read the campaign registry from its Google Sheet — fresh, schema-defended.

The ``utm_campaign`` registry lives in a human-editable Google Sheet (high
churn), so reads behave very differently from the slow-changing Git spec:

* **Read fresh, no cache.** Newly added campaigns must appear immediately, so
  every :meth:`CampaignRegistry.list_campaigns` call re-reads the Sheet.
* **Shared service credential.** The Sheet is read with a server-side Google
  *service-account* credential (an Arcade secret), so end users need no direct
  Sheet/Google access. The credential is minted into a self-signed-JWT bearer
  token locally (no network round-trip, no per-user OAuth).
* **Defensive schema validation on every read.** Because a human can reshape the
  Sheet at any time, the header row is verified against
  :data:`EXPECTED_HEADERS` and each data row is checked. On any mismatch the read
  **fails loud** with a specific, row-numbered, admin-facing message and returns
  no campaigns — it never silently guesses column meanings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

import httpx
from google.oauth2 import service_account

from .config import SheetConfig

#: The exact, ordered header row the campaign Sheet must expose. Validated on
#: every read; the registry refuses to interpret a Sheet that doesn't match.
EXPECTED_HEADERS: tuple[str, ...] = ("campaign", "description", "added_by", "added_at")

#: Read-only Sheets scope — the service credential never needs write access here.
GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

#: Google Sheets API v4 base; the spreadsheet ID and A1 range are appended.
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

#: A callable that returns a fresh bearer token for the Sheets API.
TokenProvider = Callable[[], str]


class CampaignSheetError(Exception):
    """The campaign Sheet could not be read or did not match the expected schema.

    The message is intended to surface directly to the user/agent: it names the
    specific failure (and the offending row, for schema problems) and tells them
    to contact the admin.
    """


@dataclass(frozen=True)
class Campaign:
    """One row of the campaign registry."""

    campaign: str
    description: str
    added_by: str
    added_at: str


class _NoNetworkRequest:
    """Transport stub for self-signed-JWT refresh, which performs no I/O.

    google-auth's ``Credentials.refresh`` requires a transport ``Request``, but a
    self-signed JWT (``with_always_use_jwt_access``) is minted locally and never
    hits the network, so this is never actually invoked.
    """

    def __call__(self, *args, **kwargs):  # pragma: no cover - never invoked
        raise RuntimeError("self-signed JWT refresh must not make network calls")


def build_service_account_token_provider(sa_json: str) -> TokenProvider:
    """Build a :data:`TokenProvider` from a Google service-account key JSON.

    The credential is parsed once and a locally-signed (self-signed JWT) bearer
    token is minted on demand — no token-exchange network call, no ``requests``
    dependency. A malformed credential fails loud (the tool surfaces it).
    """
    try:
        info = json.loads(sa_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CampaignSheetError(
            "The campaign Sheet service-account credential "
            "(UTM_CAMPAIGN_SA_JSON) is not valid JSON — contact the admin."
        ) from exc

    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[GOOGLE_SHEETS_READONLY_SCOPE]
        ).with_always_use_jwt_access(True)
    except (ValueError, KeyError) as exc:
        raise CampaignSheetError(
            "The campaign Sheet service-account credential "
            "(UTM_CAMPAIGN_SA_JSON) is malformed (missing fields or bad private "
            "key) — contact the admin."
        ) from exc

    def provider() -> str:
        if not creds.valid:
            creds.refresh(_NoNetworkRequest())
        return creds.token

    return provider


class CampaignRegistry:
    """Reads the campaign registry Sheet fresh, with defensive schema checks.

    Args:
        config: Resolved pointers-only Sheet configuration (ID + range).
        token_provider: Returns a bearer token for the Sheets API. Injectable for
            tests; built from the service-account secret in production.
        client: HTTP client to use. Injectable for tests (e.g. with an
            ``httpx.MockTransport``); defaults to a real ``httpx.Client``.
    """

    def __init__(
        self,
        config: SheetConfig,
        token_provider: TokenProvider,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._client = client if client is not None else httpx.Client(timeout=10.0)

    def list_campaigns(self) -> list[Campaign]:
        """Return the registry's campaigns, read fresh from the Sheet.

        Raises :class:`CampaignSheetError` on any transport failure, non-2xx
        response, or schema mismatch — never returns a partial or guessed list.
        """
        token = self._token_provider()
        url = (
            f"{SHEETS_API_BASE}/{quote(self._config.sheet_id, safe='')}"
            f"/values/{quote(self._config.sheet_range, safe='')}"
        )
        try:
            response = self._client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise CampaignSheetError(
                f"Couldn't reach the campaign Sheet at {url}: {exc}. "
                "The Sheet may be unreachable or misconfigured — contact the admin."
            ) from exc

        if response.status_code != httpx.codes.OK:
            raise CampaignSheetError(
                f"Couldn't read the campaign Sheet (HTTP {response.status_code}). "
                "The Sheet ID/range may be wrong, or the Sheet may not be shared "
                "with the service account — contact the admin."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise CampaignSheetError(
                "The campaign Sheet returned an unexpected (non-JSON) response — "
                "contact the admin."
            ) from exc

        return _parse_campaigns(payload)


def _parse_campaigns(payload: dict) -> list[Campaign]:
    """Validate the Sheets API payload against the schema and build campaigns.

    Fails loud (with the offending sheet row number) on any header/column
    mismatch rather than guessing what a column means.
    """
    rows = payload.get("values") or []
    if not rows:
        raise CampaignSheetError(
            "The campaign Sheet returned no rows (expected at least a header row "
            f"with columns {list(EXPECTED_HEADERS)}). Check the configured "
            "tab/range — contact the admin."
        )

    start_row = _start_row(payload.get("range", ""))

    header = [str(cell).strip().lower() for cell in rows[0]]
    if header != list(EXPECTED_HEADERS):
        raise CampaignSheetError(
            "The campaign Sheet headers don't match the expected schema: expected "
            f"{list(EXPECTED_HEADERS)} but found {header} (header at row {start_row}). "
            f"Fix the header row (row {start_row}) to match exactly — contact the admin."
        )

    campaigns: list[Campaign] = []
    for offset, raw_row in enumerate(rows[1:], start=1):
        sheet_row = start_row + offset
        cells = [str(cell).strip() for cell in raw_row]

        if not any(cells):
            continue  # tolerate blank spacer rows in a human-edited Sheet

        if len(cells) > len(EXPECTED_HEADERS):
            raise CampaignSheetError(
                f"The campaign Sheet row {sheet_row} has {len(cells)} columns but "
                f"the schema has {len(EXPECTED_HEADERS)} ({list(EXPECTED_HEADERS)}). "
                f"Fix row {sheet_row} — contact the admin."
            )

        # Sheets trims trailing empty cells, so pad short rows back to width.
        cells += [""] * (len(EXPECTED_HEADERS) - len(cells))

        name = cells[0]
        if not name:
            raise CampaignSheetError(
                f"The campaign Sheet row {sheet_row} is missing a campaign name in "
                f"column A. Fix row {sheet_row} — contact the admin."
            )

        campaigns.append(
            Campaign(
                campaign=name,
                description=cells[1],
                added_by=cells[2],
                added_at=cells[3],
            )
        )

    return campaigns


def _start_row(range_str: str) -> int:
    """Best-effort first row number of an A1 range (e.g. ``Campaigns!A2:D10`` -> 2).

    Used only to make schema errors point at the right sheet row. Falls back to
    ``1`` for ranges without an explicit start row (e.g. ``Campaigns!A:D``).
    """
    a1 = range_str.split("!", 1)[-1]
    match = re.search(r"[0-9]+", a1)
    return int(match.group()) if match else 1


_registries: dict[tuple[str, str], CampaignRegistry] = {}


def get_registry(config: SheetConfig, sa_json: str) -> CampaignRegistry:
    """Return a process-wide :class:`CampaignRegistry` for ``config``.

    Cached per (sheet ID, range) so the HTTP client and minted service-account
    token are reused across tool calls. Note: only the *registry object* is
    cached — campaign data is always read fresh on each ``list_campaigns`` call.
    """
    key = (config.sheet_id, config.sheet_range)
    registry = _registries.get(key)
    if registry is None:
        registry = CampaignRegistry(config, build_service_account_token_provider(sa_json))
        _registries[key] = registry
    return registry
