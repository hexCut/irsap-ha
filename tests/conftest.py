"""Shared fixtures: a fake IRSAP cloud with one radiator."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irsap_ha.const import DOMAIN

SHADOW = {
    "id": "shadow-id",
    "version": 7,
    "state": {
        "desired": {
            "E_NAM": "Casa",
            "PTO_NAM": "Bagno",
            "PTO_TMP": 215,
            "PTO_MSP": {"p": {"u": 0, "v": 200, "m": 3}},
            "PTO_CSP": {"p": {"u": 0, "v": 200, "m": 3}},
            "PTO_ENB": 1,
            "PTO_SRL": "AA:BB:CC:DD:EE:FF",
            "PTO_FWV": "1.2.3",
            "PTO_TYP": "Radiator",
            "PTO_X_ipAddress": "192.168.0.50",
            "PTO_X_LED_CSP": {"p": {"v": 1}},
            "PTO_X_LED_ENB": 1,
            "PTO_X_LED_MSP": {"p": {"u": 1, "v": {"h": 120, "s": 100, "v": 50}, "m": 4}},
        }
    },
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_jwks_download():
    """Never download Cognito's public keys in tests; start with no cache."""
    from custom_components.irsap_ha import auth

    auth._jwks_cache = None
    response = MagicMock()
    response.json.return_value = {"keys": []}
    with patch.object(auth.requests, "get", return_value=response):
        yield
    auth._jwks_cache = None


@pytest.fixture(autouse=True)
def clear_device_manager():
    from custom_components.irsap_ha.device_manager import device_manager

    device_manager.clear()
    yield
    device_manager.clear()


@pytest.fixture
def config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "token": "setup-token",
            "envID": "env-1",
        },
    )


@pytest.fixture
def mock_login():
    """Patch the blocking SRP login; each call returns a new token."""
    counter = {"n": 0}

    def _login(username, password):
        counter["n"] += 1
        return f"token-{counter['n']}"

    with patch(
        "custom_components.irsap_ha.auth.login_with_srp", side_effect=_login
    ) as mock:
        yield mock


@pytest.fixture
def shadow():
    return copy.deepcopy(SHADOW)


@pytest.fixture
def mock_get_shadow(shadow):
    async def _get(hass, token, envID):
        return copy.deepcopy(shadow)

    with patch(
        "custom_components.irsap_ha.api.async_get_shadow", side_effect=_get
    ) as mock:
        yield mock


@pytest.fixture
def mock_update_shadow():
    mock = AsyncMock(return_value=True)
    with (
        patch("custom_components.irsap_ha.climate.async_update_shadow", new=mock),
        patch("custom_components.irsap_ha.light.async_update_shadow", new=mock),
    ):
        yield mock
