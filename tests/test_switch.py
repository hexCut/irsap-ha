"""Child lock / standby / open window detection switches."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.irsap_ha.switch import device_key

LOCK = "switch.bagno_child_lock"
STANDBY = "switch.bagno_standby"
WINDOW = "switch.bagno_open_window_detection"


def _with_device(shadow, **values):
    shadow["state"]["desired"].update(
        {
            "DRk_X_lock": 0,
            "DRk_X_standby": 0,
            "DRk_X_OpenWindowSensorEnabled": 1,
            "GkV_PLD": "PTO",
            "GkV_MID": "DRk",
            **values,
        }
    )


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def test_device_key():
    desired = {"GkV_PLD": "PTO", "GkV_MID": "DRk", "DRk_X_lock": 0, "OTH_X_lock": 1}
    assert device_key(desired, "PTO", "_X_lock") == "DRk_X_lock"
    # no link: the only key with that suffix, if there is just one
    assert device_key({"DRk_X_lock": 0}, "PTO", "_X_lock") == "DRk_X_lock"
    assert device_key({"A_X_lock": 0, "B_X_lock": 1}, "PTO", "_X_lock") is None
    assert device_key({}, "PTO", "_X_lock") is None


async def test_switch_states(hass, config_entry, mock_login, mock_get_shadow, shadow):
    _with_device(shadow)
    await _setup(hass, config_entry)
    assert hass.states.get(LOCK).state == "off"
    assert hass.states.get(STANDBY).state == "off"
    assert hass.states.get(WINDOW).state == "on"

    registry = er.async_get(hass)
    assert registry.async_get(LOCK).entity_category is EntityCategory.CONFIG

    # changed from the app or the radiator: followed on the next refresh
    shadow["state"]["desired"]["DRk_X_lock"] = 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(LOCK).state == "on"


async def test_turn_on_writes_the_device_key(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    _with_device(shadow)
    await _setup(hass, config_entry)

    with patch(
        "custom_components.irsap_ha.switch.async_update_shadow", return_value=True
    ) as update:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LOCK}, blocking=True
        )
    sent = update.call_args.args[3]
    assert sent["state"]["desired"]["DRk_X_lock"] == 1
    assert sent["clientId"].startswith("app-")
    assert "sk" not in sent["state"]["desired"]
    assert hass.states.get(LOCK).state == "on"

    # the shadow still says 0 for a moment: not reverted during the settle time
    coordinator = hass.data["irsap_ha"][config_entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(LOCK).state == "on"


async def test_settings_the_radiator_does_not_report_are_not_created(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"].update({"DRk_X_lock": 0})  # no standby/window keys
    await _setup(hass, config_entry)
    assert hass.states.get(LOCK) is not None
    assert hass.states.get(STANDBY) is None
    assert hass.states.get(WINDOW) is None


async def test_write_failure_raises(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    _with_device(shadow)
    await _setup(hass, config_entry)
    with (
        patch(
            "custom_components.irsap_ha.switch.async_update_shadow", return_value=False
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": STANDBY}, blocking=True
        )
    assert hass.states.get(STANDBY).state == "off"
