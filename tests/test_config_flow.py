"""Options flow."""

from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.irsap_ha.const import CONF_SCAN_INTERVAL


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
