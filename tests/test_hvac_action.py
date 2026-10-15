"""hvac_action from the shadow (issue #20)."""

import copy
from unittest.mock import patch

from homeassistant.components.climate import HVACAction
import pytest

from custom_components.irsap_ha.hvac_action import (
    compute_hvac_action,
    count_zones,
    written_by_device,
)

# Shape of a real single-radiator shadow (fw 3.22), trimmed to the keys used
SINGLE = {
    "E_NAM": "Casa",
    "E_CLL": 1,
    "PcC_NAM": "Bagno",
    "PcC_ENB": 1,
    "PcC_TMP": 264,
    "PcC_CSP": {"p": {"k": "CURRENT", "m": 3, "u": 0, "v": 300}},
    "PcC_MSP": {"p": {"k": "MANUAL", "m": 3, "u": 0, "v": 300}},
}


def single(**changes):
    desired = copy.deepcopy(SINGLE)
    desired.update(changes)
    return desired


def two_zones(**changes):
    desired = single(**changes)
    desired.update({"ABC_NAM": "Camera", "ABC_ENB": 1, "ABC_TMP": 200})
    return desired


def test_count_zones_ignores_environment_name():
    assert count_zones(SINGLE) == 1
    assert count_zones(two_zones()) == 2


def test_written_by_device():
    assert written_by_device({"clientId": "dev-RE_20:0a:0d:a2:68:bc#RE"})
    assert not written_by_device({"clientId": "app-now2-1.9.38-2143-ios-x"})
    assert not written_by_device({})
    assert not written_by_device(None)


@pytest.mark.parametrize(("e_cll", "expected"), [(1, HVACAction.HEATING), (0, HVACAction.IDLE)])
def test_single_zone_uses_e_cll_from_device(e_cll, expected):
    # TMP < CSP would say "heating": E_CLL from the radiator wins
    assert compute_hvac_action(single(E_CLL=e_cll), "PcC", True) == expected


def test_single_zone_ignores_e_cll_written_by_app():
    """Right after a command E_CLL=1 is our own write: infer from TMP/CSP."""
    desired = single(E_CLL=1, PcC_TMP=264, PcC_CSP={"p": {"v": 250}})
    assert compute_hvac_action(desired, "PcC", False) == HVACAction.IDLE


def test_off():
    assert compute_hvac_action(single(PcC_ENB=0), "PcC", True) == HVACAction.OFF
    assert compute_hvac_action(single(PcC_ENB=None), "PcC", False) == HVACAction.OFF


def test_multi_zone_inferred_with_hysteresis():
    """E_CLL can't be attributed to one radiator: infer with hysteresis."""
    d = two_zones(E_CLL=1, PcC_CSP={"p": {"v": 250}})
    # 0.1 °C below the setpoint: not enough to start heating from idle
    assert compute_hvac_action({**d, "PcC_TMP": 249}, "PcC", True, HVACAction.IDLE) == HVACAction.IDLE
    # 0.3 °C below: heating
    assert compute_hvac_action({**d, "PcC_TMP": 247}, "PcC", True, HVACAction.IDLE) == HVACAction.HEATING
    # once heating, keeps heating until the setpoint is reached
    assert compute_hvac_action({**d, "PcC_TMP": 249}, "PcC", True, HVACAction.HEATING) == HVACAction.HEATING
    assert compute_hvac_action({**d, "PcC_TMP": 250}, "PcC", True, HVACAction.HEATING) == HVACAction.IDLE
    # no previous action (startup) inside the band: idle
    assert compute_hvac_action({**d, "PcC_TMP": 249}, "PcC", True) == HVACAction.IDLE


def test_multi_zone_falls_back_to_msp():
    d = two_zones()
    del d["PcC_CSP"]
    d["PcC_MSP"] = {"p": {"v": 300}}
    assert compute_hvac_action(d, "PcC", True) == HVACAction.HEATING


@pytest.mark.parametrize(
    "changes",
    [
        {"PcC_TMP": None},
        {"PcC_CSP": None, "PcC_MSP": None},
        {"PcC_CSP": {"p": {}}, "PcC_MSP": {}},
    ],
)
def test_missing_values(changes):
    assert compute_hvac_action(two_zones(**changes), "PcC", True) is None
    # single zone, shadow written by the app and no temperatures: unknown too
    assert compute_hvac_action(single(**changes), "PcC", False) is None


# --- entity -------------------------------------------------------------

ENTITY = "climate.bagno_radiator"


async def _no_sleep(*args):
    return None


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entity_reports_action_from_device_shadow(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["clientId"] = "dev-RE_00:00:00:00:00:00#RE"
    shadow["state"]["desired"]["E_CLL"] = 0
    await _setup(hass, config_entry)
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "idle"

    coordinator = hass.data["irsap_ha"][config_entry.entry_id]["coordinator"]
    # 21.5 °C is above the 20 °C setpoint, but E_CLL from the radiator decides
    shadow["state"]["desired"]["E_CLL"] = 1
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "heating"

    shadow["state"]["desired"]["PTO_ENB"] = 0
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes["hvac_action"] == "off"


async def test_entity_action_after_commands(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow, shadow
):
    shadow["state"]["desired"]["PTO_ENB"] = 0
    await _setup(hass, config_entry)
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "off"

    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": ENTITY, "hvac_mode": "heat"},
            blocking=True,
        )
    # current 21.5 °C, target 20 °C: setpoint already reached
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "idle"

    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 25},
            blocking=True,
        )
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "heating"

    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": ENTITY, "hvac_mode": "off"},
            blocking=True,
        )
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "off"
