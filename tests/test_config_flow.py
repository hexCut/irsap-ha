"""Config and options flow."""

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.irsap_ha.api import API_URL, async_list_environments
from custom_components.irsap_ha.const import CONF_SCAN_INTERVAL, DOMAIN


async def test_options_interval(hass, config_entry, mock_login, mock_get_shadow):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"username": "user@example.com", "password": "secret", CONF_SCAN_INTERVAL: 120.0},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 120}


async def test_options_new_credentials(hass, config_entry, mock_login, mock_get_shadow):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    with patch(
        "custom_components.irsap_ha.config_flow._sync_login_with_srp", return_value=None
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"username": "new@example.com", "password": "bad", CONF_SCAN_INTERVAL: 60},
        )
    assert result["errors"] == {"base": "invalid_credentials"}

    with patch(
        "custom_components.irsap_ha.config_flow._sync_login_with_srp",
        return_value="tok",
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"username": "new@example.com", "password": "good", CONF_SCAN_INTERVAL: 60},
        )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.data["username"] == "new@example.com"
    assert config_entry.data["password"] == "good"


# --- choosing the home (environment) ------------------------------------

CREDENTIALS = {"username": "user@example.com", "password": "secret"}


async def _start_user_flow(hass, environments):
    with (
        patch(
            "custom_components.irsap_ha.config_flow._sync_login_with_srp",
            return_value="tok",
        ),
        patch(
            "custom_components.irsap_ha.config_flow.async_list_environments",
            return_value=environments,
        ),
        patch("custom_components.irsap_ha.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )


async def test_single_home_is_used_directly(hass):
    result = await _start_user_flow(hass, [{"envId": "env-1", "envName": "Casa"}])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["data"] == {**CREDENTIALS, "token": "tok", "envID": "env-1"}


async def test_choose_between_homes(hass):
    homes = [
        {"envId": "env-1", "envName": "Casa"},
        {"envId": "env-2", "envName": "Mare"},
    ]
    result = await _start_user_flow(hass, homes)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "environment"

    with patch("custom_components.irsap_ha.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"envID": "env-2"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com (Mare)"
    assert result["data"]["envID"] == "env-2"


@pytest.mark.parametrize("environments", [[], None])
async def test_no_home(hass, environments):
    result = await _start_user_flow(hass, environments)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "envid_failed"}


async def test_list_environments(hass, aioclient_mock):
    aioclient_mock.post(
        API_URL,
        json={
            "data": {
                "listEnvironments": {
                    "environments": [
                        {"envId": "env-1", "envName": "Casa", "userRole": "OWNER"},
                        {"envId": "env-2", "envName": None, "userRole": "GUEST"},
                        {"envName": "broken"},
                    ]
                }
            }
        },
    )
    assert await async_list_environments(hass, "tok") == [
        {"envId": "env-1", "envName": "Casa"},
        {"envId": "env-2", "envName": "env-2"},
    ]


async def test_list_environments_http_error(hass, aioclient_mock):
    aioclient_mock.post(API_URL, status=401, text="Unauthorized")
    assert await async_list_environments(hass, "tok") is None
