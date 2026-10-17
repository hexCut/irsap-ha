"""LED on/off."""

from unittest.mock import patch


async def _no_sleep(*args):
    return None


async def test_led_on_off(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with patch("custom_components.irsap_ha.light.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "light", "turn_off", {"entity_id": "light.bagno_led"}, blocking=True
        )
    assert mock_update_shadow.call_args.args[3]["state"]["desired"]["PTO_X_LED_ENB"] == 0
    assert hass.states.get("light.bagno_led").state == "off"

    with patch("custom_components.irsap_ha.light.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "light", "turn_on", {"entity_id": "light.bagno_led"}, blocking=True
        )
    assert mock_update_shadow.call_args.args[3]["state"]["desired"]["PTO_X_LED_ENB"] == 1
    assert hass.states.get("light.bagno_led").state == "on"
    assert mock_login.call_count == 1
