"""Identify button (#62)."""

from unittest.mock import patch

from homeassistant.components.button import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest

IDENTIFY = "button.bagno_identify"


def _with_device(shadow, **values):
    shadow["state"]["desired"].update(
        {"DRk_X_identify": 0, "GkV_PLD": "PTO", "GkV_MID": "DRk", **values}
    )


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_identify_button(hass, config_entry, mock_login, mock_get_shadow, shadow):
    _with_device(shadow)
    await _setup(hass, config_entry)

    state = hass.states.get(IDENTIFY)
    assert state is not None
    assert state.attributes["device_class"] == ButtonDeviceClass.IDENTIFY
    entry = er.async_get(hass).async_get(IDENTIFY)
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.unique_id == "env-1_PTO_identify"


async def test_press_writes_identify(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    _with_device(shadow, OTH_X_identify=0)
    await _setup(hass, config_entry)

    with patch(
        "custom_components.irsap_ha.api.async_update_shadow", return_value=True
    ) as update:
        await hass.services.async_call(
            "button", "press", {"entity_id": IDENTIFY}, blocking=True
        )
    sent = update.call_args.args[3]["state"]["desired"]
    assert sent["DRk_X_identify"] == 1
    # only this radiator's device
    assert sent["OTH_X_identify"] == 0
    assert update.call_args.args[3]["clientId"].startswith("app-")


async def test_not_created_without_identify(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    await _setup(hass, config_entry)
    assert hass.states.get(IDENTIFY) is None


async def test_press_failure_raises(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    _with_device(shadow)
    await _setup(hass, config_entry)
    assert hass.states.get(IDENTIFY) is not None
    with (
        patch(
            "custom_components.irsap_ha.api.async_update_shadow", return_value=False
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": IDENTIFY}, blocking=True
        )
