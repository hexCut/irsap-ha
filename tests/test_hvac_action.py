"""hvac_action from the shadow (issue #20)."""

import copy
from unittest.mock import patch

from homeassistant.components.climate import HVACAction
import pytest

from custom_components.irsap_ha.hvac_action import (
    INFERRED_HYSTERESIS,
    compute_hvac_action,
    count_zones,
    get_hysteresis,
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
    """E_CLL can't be attributed to one radiator: infer with the radiator's
    own 0.2 °C hysteresis. Values from a real heat/idle/heat cycle with the
    setpoint at 26.8 °C (fw 3.22)."""
    d = two_zones(E_CLL=1, PcC_CSP={"p": {"v": 268}})
    heating, idle = HVACAction.HEATING, HVACAction.IDLE
    # heating: keeps going up to setpoint + 0.2 °C, stops above it
    assert compute_hvac_action({**d, "PcC_TMP": 270}, "PcC", True, heating) == heating
    assert compute_hvac_action({**d, "PcC_TMP": 271}, "PcC", True, heating) == idle
    # idle: stays idle down to setpoint - 0.2 °C, starts again below it
    assert compute_hvac_action({**d, "PcC_TMP": 266}, "PcC", True, idle) == idle
    assert compute_hvac_action({**d, "PcC_TMP": 265}, "PcC", True, idle) == heating
    # no previous action (startup) inside the band: idle
    assert compute_hvac_action({**d, "PcC_TMP": 267}, "PcC", True) == idle


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


# --- hysteresis from the shadow -----------------------------------------


# Device/group/zone links as in a real shadow (fw 3.22)
LINKS = {
    "DRk_MID": "DRk",
    "DRk_X_hysteresis": 2,
    "GkV_MID": "DRk",
    "GkV_PLD": "PcC",
    "W8p_DID": "DRk",
    "W8p_GID": "GkV",
}


def test_hysteresis_follows_group_link():
    assert get_hysteresis({**SINGLE, **LINKS, "DRk_X_hysteresis": 5}, "PcC") == 5


def test_hysteresis_per_zone_with_two_radiators():
    desired = {
        **two_zones(),
        **LINKS,
        "Xyz_MID": "Xyz",
        "Xyz_X_hysteresis": 4,
        "Grp_MID": "Xyz",
        "Grp_PLD": "ABC",
    }
    assert get_hysteresis(desired, "PcC") == 2
    assert get_hysteresis(desired, "ABC") == 4


def test_hysteresis_single_value_without_links():
    assert get_hysteresis({**SINGLE, "DRk_X_hysteresis": 3}, "PcC") == 3


@pytest.mark.parametrize(
    "extra",
    [
        {},  # no hysteresis in the shadow
        {"DRk_X_hysteresis": None},
        {"DRk_X_hysteresis": True},
        {"DRk_X_hysteresis": -1},
        {"A_X_hysteresis": 3, "B_X_hysteresis": 4},  # ambiguous, no links
    ],
)
def test_hysteresis_fallback(extra):
    assert get_hysteresis({**SINGLE, **extra}, "PcC") == INFERRED_HYSTERESIS


def test_inference_uses_hysteresis_from_shadow():
    """With a 0.5 °C hysteresis the band around 26.8 °C is 26.3–27.3 °C."""
    d = {**two_zones(E_CLL=1, PcC_CSP={"p": {"v": 268}}), **LINKS, "DRk_X_hysteresis": 5}
    heating, idle = HVACAction.HEATING, HVACAction.IDLE
    assert compute_hvac_action({**d, "PcC_TMP": 273}, "PcC", True, heating) == heating
    assert compute_hvac_action({**d, "PcC_TMP": 274}, "PcC", True, heating) == idle
    assert compute_hvac_action({**d, "PcC_TMP": 263}, "PcC", True, idle) == idle
    assert compute_hvac_action({**d, "PcC_TMP": 262}, "PcC", True, idle) == heating
