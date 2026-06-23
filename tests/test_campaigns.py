"""Tests for the campaign-registry read path: fresh reads + schema defense."""

import json

import httpx
import pytest

from utm_server.campaigns import (
    EXPECTED_HEADERS,
    Campaign,
    CampaignRegistry,
    CampaignSheetError,
    _start_row,
    build_service_account_token_provider,
)
from utm_server.config import SheetConfig


def make_config(sheet_id="sheet123", sheet_range="Campaigns!A:D") -> SheetConfig:
    return SheetConfig(sheet_id=sheet_id, sheet_range=sheet_range)


def make_registry(handler, config=None) -> CampaignRegistry:
    """Build a CampaignRegistry over a MockTransport with a stub token provider."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CampaignRegistry(config or make_config(), token_provider=lambda: "fake-token", client=client)


def values_response(values, *, sheet_range="Campaigns!A1:D10") -> httpx.Response:
    return httpx.Response(200, json={"range": sheet_range, "majorDimension": "ROWS", "values": values})


HEADER = list(EXPECTED_HEADERS)


def test_list_campaigns_happy_path():
    rows = [
        HEADER,
        ["2026-q2_agent-launch", "Q2 agent launch", "u_1", "2026-04-01"],
        ["2026-q3_growth", "Growth push", "u_2", "2026-07-01"],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        # Hits the Sheets API v4 values endpoint with a bearer token.
        assert "sheets.googleapis.com/v4/spreadsheets/sheet123/values/" in str(request.url)
        assert request.headers["Authorization"] == "Bearer fake-token"
        return values_response(rows)

    campaigns = make_registry(handler).list_campaigns()
    assert campaigns == [
        Campaign("2026-q2_agent-launch", "Q2 agent launch", "u_1", "2026-04-01"),
        Campaign("2026-q3_growth", "Growth push", "u_2", "2026-07-01"),
    ]


def test_range_is_url_encoded_in_request():
    def handler(request: httpx.Request) -> httpx.Response:
        # The "!" and ":" of the A1 range must be percent-encoded, not raw.
        assert "Campaigns%21A%3AD" in str(request.url)
        return values_response([HEADER])

    make_registry(handler).list_campaigns()


def test_blank_spacer_rows_are_skipped():
    rows = [
        HEADER,
        ["2026-q2_agent-launch", "Q2 agent launch", "u_1", "2026-04-01"],
        ["", "", "", ""],  # human-left blank row
        [],  # entirely empty row
        ["2026-q3_growth", "Growth push", "u_2", "2026-07-01"],
    ]
    campaigns = make_registry(lambda r: values_response(rows)).list_campaigns()
    assert [c.campaign for c in campaigns] == ["2026-q2_agent-launch", "2026-q3_growth"]


def test_short_rows_are_padded():
    # Sheets trims trailing empty cells; a campaign with no added_at comes back short.
    rows = [HEADER, ["2026-q2_agent-launch", "Q2 launch"]]
    (campaign,) = make_registry(lambda r: values_response(rows)).list_campaigns()
    assert campaign == Campaign("2026-q2_agent-launch", "Q2 launch", "", "")


def test_header_cells_are_trimmed_and_lowercased():
    rows = [[" Campaign ", "Description", "Added_By", "ADDED_AT"], ["c1", "d", "u", "t"]]
    (campaign,) = make_registry(lambda r: values_response(rows)).list_campaigns()
    assert campaign.campaign == "c1"


def test_malformed_header_fails_loud_with_row_number():
    rows = [["name", "desc", "who", "when"], ["c1", "d", "u", "t"]]

    def handler(request):
        return values_response(rows, sheet_range="Campaigns!A1:D2")

    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(handler).list_campaigns()
    message = str(excinfo.value)
    assert "headers don't match" in message
    assert "row 1" in message
    assert "admin" in message


def test_extra_column_in_header_fails_loud():
    rows = [HEADER + ["surprise"], ["c1", "d", "u", "t", "x"]]
    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(lambda r: values_response(rows)).list_campaigns()
    assert "headers don't match" in str(excinfo.value)


def test_extra_columns_in_data_row_fails_loud_with_row_number():
    rows = [HEADER, ["c1", "d", "u", "t"], ["c2", "d", "u", "t", "oops"]]

    def handler(request):
        return values_response(rows, sheet_range="Campaigns!A1:E3")

    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(handler).list_campaigns()
    message = str(excinfo.value)
    assert "row 3" in message  # header row 1, c1 row 2, the bad row is sheet row 3
    assert "admin" in message


def test_missing_campaign_name_fails_loud_with_row_number():
    rows = [HEADER, ["", "orphan description", "u_1", "2026-04-01"]]
    # A blank first cell with other cells populated is malformed, not a spacer row.
    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(lambda r: values_response(rows)).list_campaigns()
    message = str(excinfo.value)
    assert "row 2" in message
    assert "campaign name" in message


def test_row_numbers_respect_a_non_default_start_row():
    rows = [HEADER, ["c1", "d", "u", "t", "oops"]]

    def handler(request):
        return values_response(rows, sheet_range="Campaigns!A5:E6")

    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(handler).list_campaigns()
    assert "row 6" in str(excinfo.value)  # header at row 5, bad data row at row 6


def test_empty_sheet_fails_loud():
    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(lambda r: httpx.Response(200, json={"range": "Campaigns!A:D"})).list_campaigns()
    assert "no rows" in str(excinfo.value)
    assert "admin" in str(excinfo.value)


def test_http_error_fails_loud():
    def handler(request):
        return httpx.Response(403, text="forbidden")

    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(handler).list_campaigns()
    message = str(excinfo.value)
    assert "403" in message
    assert "service account" in message
    assert "admin" in message


def test_transport_error_fails_loud():
    def handler(request):
        raise httpx.ConnectError("name resolution failed")

    with pytest.raises(CampaignSheetError) as excinfo:
        make_registry(handler).list_campaigns()
    message = str(excinfo.value)
    assert "unreachable" in message or "reach" in message
    assert "admin" in message


def test_read_is_always_fresh_not_cached():
    bodies = iter([
        [HEADER, ["c1", "d", "u", "t"]],
        [HEADER, ["c1", "d", "u", "t"], ["c2", "d", "u", "t"]],
    ])

    def handler(request):
        return values_response(next(bodies))

    registry = make_registry(handler)
    assert len(registry.list_campaigns()) == 1
    assert len(registry.list_campaigns()) == 2  # second read sees the new row


def _make_service_account_info() -> dict:
    """A syntactically valid service-account key with a throwaway RSA private key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {
        "type": "service_account",
        "project_id": "test",
        "private_key_id": "kid1",
        "private_key": pem,
        "client_email": "svc@test.iam.gserviceaccount.com",
        "client_id": "123",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_token_provider_mints_a_token_without_network():
    provider = build_service_account_token_provider(json.dumps(_make_service_account_info()))
    # Self-signed JWT is minted locally; no transport call is made.
    token = provider()
    assert isinstance(token, str) and token


def test_token_provider_rejects_non_json_credential():
    with pytest.raises(CampaignSheetError) as excinfo:
        build_service_account_token_provider("not json")
    assert "not valid JSON" in str(excinfo.value)
    assert "admin" in str(excinfo.value)


def test_token_provider_rejects_malformed_credential():
    with pytest.raises(CampaignSheetError) as excinfo:
        build_service_account_token_provider(json.dumps({"type": "service_account"}))
    assert "malformed" in str(excinfo.value)
    assert "admin" in str(excinfo.value)


@pytest.mark.parametrize(
    "range_str,expected",
    [
        ("Campaigns!A1:D10", 1),
        ("Campaigns!A5:D9", 5),
        ("Campaigns!A:D", 1),  # no explicit start row -> default
        ("A2:D", 2),
        ("", 1),
    ],
)
def test_start_row_parsing(range_str, expected):
    assert _start_row(range_str) == expected
