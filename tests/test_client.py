"""Tests for akamai/client.py — mocks requests.Session."""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

# Reset the module-level singleton before each test
import akamai_api.client as client_module


@pytest.fixture(autouse=True)
def reset_singleton():
    client_module._client_instance = None
    yield
    client_module._client_instance = None


def _make_mock_session(status_code: int = 200, json_data=None):
    session = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Error", response=response
        )
    else:
        response.raise_for_status.return_value = None
    session.get.return_value = response
    session.post.return_value = response
    return session


@patch("akamai_api.client.EdgeGridAuth")
@patch("akamai_api.client.EdgeRc")
@patch("akamai_api.client.get_account_config")
def _make_client(mock_config, mock_edgerc, mock_auth, session=None):
    mock_config.return_value = MagicMock(
        base_url="https://host.example.com",
        reporting_base_url="https://host.example.com/reporting-api/v2",
    )
    c = client_module.AkamaiClient()
    if session is not None:
        c.session = session
    return c


# ── list_account_switch_keys ──────────────────────────────────

def test_list_accounts_parses_response():
    accounts = [{"accountSwitchKey": "1-ABC", "accountName": "Acme", "accountId": "1-XYZ"}]
    session = _make_mock_session(json_data=accounts)
    with (
        patch("akamai_api.client.EdgeGridAuth"),
        patch("akamai_api.client.EdgeRc"),
        patch("akamai_api.client.get_account_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            base_url="https://host",
            reporting_base_url="https://host/reporting-api/v2",
        )
        c = client_module.AkamaiClient()
        c.session = session
        result = c.list_account_switch_keys()

    assert result == accounts
    session.get.assert_called_once()
    url = session.get.call_args[0][0]
    assert "account-switch-keys" in url


def test_list_accounts_passes_search_param():
    session = _make_mock_session(json_data=[])
    with (
        patch("akamai_api.client.EdgeGridAuth"),
        patch("akamai_api.client.EdgeRc"),
        patch("akamai_api.client.get_account_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            base_url="https://host",
            reporting_base_url="https://host/reporting-api/v2",
        )
        c = client_module.AkamaiClient()
        c.session = session
        c.list_account_switch_keys(search="Acme")

    kwargs = session.get.call_args[1]
    assert kwargs.get("params", {}).get("search") == "Acme"


# ── fetch_traffic ─────────────────────────────────────────────

def test_fetch_traffic_includes_account_switch_key():
    session = _make_mock_session(json_data={"data": []})
    with (
        patch("akamai_api.client.EdgeGridAuth"),
        patch("akamai_api.client.EdgeRc"),
        patch("akamai_api.client.get_account_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            base_url="https://host",
            reporting_base_url="https://host/reporting-api/v2",
        )
        c = client_module.AkamaiClient()
        c.session = session
        c.fetch_traffic({}, "2025-01-01T00:00:00Z", "2025-01-15T00:00:00Z", "1-SWITCH")

    params = session.post.call_args[1]["params"]
    assert params.get("accountSwitchKey") == "1-SWITCH"


def test_fetch_traffic_omits_account_switch_key_when_empty():
    session = _make_mock_session(json_data={"data": []})
    with (
        patch("akamai_api.client.EdgeGridAuth"),
        patch("akamai_api.client.EdgeRc"),
        patch("akamai_api.client.get_account_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            base_url="https://host",
            reporting_base_url="https://host/reporting-api/v2",
        )
        c = client_module.AkamaiClient()
        c.session = session
        c.fetch_traffic({}, "2025-01-01T00:00:00Z", "2025-01-15T00:00:00Z", "")

    params = session.post.call_args[1]["params"]
    assert "accountSwitchKey" not in params


def test_fetch_traffic_raises_on_4xx():
    session = _make_mock_session(status_code=403)
    with (
        patch("akamai_api.client.EdgeGridAuth"),
        patch("akamai_api.client.EdgeRc"),
        patch("akamai_api.client.get_account_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            base_url="https://host",
            reporting_base_url="https://host/reporting-api/v2",
        )
        c = client_module.AkamaiClient()
        c.session = session
        with pytest.raises(requests.HTTPError):
            c.fetch_traffic({}, "2025-01-01T00:00:00Z", "2025-01-15T00:00:00Z")


# ── Singleton ─────────────────────────────────────────────────

def test_get_client_returns_singleton():
    with (
        patch("akamai_api.client.EdgeGridAuth"),
        patch("akamai_api.client.EdgeRc"),
        patch("akamai_api.client.get_account_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            base_url="https://host",
            reporting_base_url="https://host/reporting-api/v2",
        )
        c1 = client_module.get_client()
        c2 = client_module.get_client()

    assert c1 is c2
