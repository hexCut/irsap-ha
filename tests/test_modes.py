"""Manual / schedule / temporary modes, with values from a real radiator."""

from datetime import datetime, timezone
import copy
from unittest.mock import patch

import pytest

from custom_components.irsap_ha import modes

NOW = datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc)
MIDNIGHT = "2026-10-17T22:00:00.000Z"  # next schedule change, local midnight
NO_END = "2106-02-07T06:28:15.000Z"

# Shadow snapshots captured on fw 3.22 during the tests for this PR
MANUAL_ON = {
    "E_NAM": "Casa",
    "PcC_NAM": "Bagno",
    "E_SCH": [],
    "E_CLL": 0,
    "E_CPC": 0,
    "PcC_ENB": 1,
    "PcC_MOD": 1,
    "PcC_MSP": {"p": {"k": "MANUAL", "m": 3, "u": 0, "v": 270}},
    "PcC_TSP": {
        "p": {"u": 0, "v": 260, "m": 3, "k": "TEMPORARY"},
        "e": modes.NO_EXPIRY,
    },
    "PcC_CSP": {"p": {"k": "CURRENT", "m": 3, "u": 0, "v": 270}, "e": NO_END},
}
# Schedule as created in the app: one slot from 00:00 with the ECO preset,
# assigned to the room through <zone>_WSC
SCHEDULE_ID = "3db92aa6-1116-4dd2-9f2f-0386ae8d1892"
SCHEDULE_ENTRY = {
    "w": [[{"t": 0, "s": "1#ECO"}] for _ in range(7)],
    "n": "",
    "m": 1,
    "k": SCHEDULE_ID,
}
SCHEDULE = {
    **copy.deepcopy(MANUAL_ON),
    "E_SCH": [SCHEDULE_ENTRY],
    "PcC_WSC": SCHEDULE_ID,
    "PcC_MOD": 2,
    "PcC_CSP": {"p": {"k": "CURRENT", "m": 3, "u": 0, "v": 180}, "e": MIDNIGHT},
}
TEMPORARY = {
    **copy.deepcopy(SCHEDULE),
    "PcC_TSP": {"p": {"k": "TEMPORARY", "m": 3, "u": 0, "v": 190}, "e": MIDNIGHT},
    "PcC_CSP": {"p": {"k": "CURRENT", "m": 3, "u": 0, "v": 190}, "e": MIDNIGHT},
}
OFF = {
    **copy.deepcopy(MANUAL_ON),
    "PcC_ENB": 0,
    "PcC_CSP": {"p": {"k": "CURRENT", "m": 3, "u": 0, "v": 50}, "e": NO_END},
}


def test_reading_modes():
    assert modes.preset_for(MANUAL_ON, "PcC") == "manual"
    assert modes.preset_for(SCHEDULE, "PcC") == "schedule"
    assert modes.preset_for(TEMPORARY, "PcC") == "schedule"
    assert modes.preset_modes(MANUAL_ON, "PcC") == ["manual"]
    assert modes.preset_modes(SCHEDULE, "PcC") == ["manual", "schedule"]
    # MOD=2 left over without any schedule is shown as manual
    assert modes.preset_for({**MANUAL_ON, "PcC_MOD": 2}, "PcC") == "manual"


def test_schedule_is_per_room():
    """E_SCH lists the home's schedules; only a room whose _WSC points to one
    of them gets the schedule preset."""
    two_rooms = {
        **copy.deepcopy(SCHEDULE),
        "ABC_NAM": "Camera",
        "ABC_MOD": 1,
        "ABC_ENB": 1,
    }
    assert modes.preset_modes(two_rooms, "PcC") == ["manual", "schedule"]
    assert modes.preset_modes(two_rooms, "ABC") == ["manual"]
    with pytest.raises(ValueError):
        modes.apply_preset(two_rooms, "ABC", "schedule")
    # a _WSC pointing to a schedule that no longer exists
    stale = {**copy.deepcopy(SCHEDULE), "E_SCH": []}
    assert modes.preset_for(stale, "PcC") == "manual"
    assert modes.preset_modes(stale, "PcC") == ["manual"]


def test_applied_setpoint():
    assert modes.applied_setpoint(MANUAL_ON, "PcC") == 27.0
    assert modes.applied_setpoint(SCHEDULE, "PcC") == 18.0  # not the 27 manual one
    assert modes.applied_setpoint(TEMPORARY, "PcC") == 19.0
    assert modes.applied_setpoint(OFF, "PcC") == 27.0  # not the 5 °C antifreeze


def test_temporary_until():
    assert modes.temporary_until(TEMPORARY, "PcC", NOW) == datetime(
        2026, 10, 17, 22, 0, tzinfo=timezone.utc
    )
    assert modes.temporary_until(SCHEDULE, "PcC", NOW) is None
    assert modes.temporary_until(MANUAL_ON, "PcC", NOW) is None


def test_setpoint_in_manual_mode():
    desired = copy.deepcopy(MANUAL_ON)
    modes.apply_setpoint(desired, "PcC", 24, NOW)
    assert desired["PcC_MOD"] == 1
    assert desired["PcC_MSP"]["p"]["v"] == 240
    assert desired["PcC_CSP"]["p"]["v"] == 240
    assert desired["PcC_TSP"]["e"] == modes.NO_EXPIRY
    # the heat call is the radiator's: never written
    assert (desired["E_CLL"], desired["E_CPC"]) == (0, 0)


def test_setpoint_in_schedule_mode_is_temporary_until_next_change():
    """Like the radiator's +/- buttons: temporary until the next schedule
    change, manual setpoint untouched, still in schedule mode."""
    desired = copy.deepcopy(SCHEDULE)
    modes.apply_setpoint(desired, "PcC", 19, NOW)
    assert desired["PcC_MOD"] == 2
    assert desired["PcC_TSP"] == {
        "p": {"u": 0, "v": 190, "m": 3, "k": "TEMPORARY"},
        "e": MIDNIGHT,
    }
    assert desired["PcC_MSP"]["p"]["v"] == 270
    assert desired["PcC_CSP"]["p"]["v"] == 190


def test_one_schedule_one_radiator_is_still_schedule_mode():
    """The previous code compared len(E_SCH) with the _NAM count, which also
    counted E_NAM: with one schedule and one radiator it switched to manual."""
    desired = copy.deepcopy(SCHEDULE)
    assert len(desired["E_SCH"]) == 1
    modes.apply_setpoint(desired, "PcC", 21, NOW)
    assert desired["PcC_MOD"] == 2


def test_temporary_without_known_schedule_change_lasts_24h():
    desired = copy.deepcopy(SCHEDULE)
    desired["PcC_CSP"]["e"] = NO_END
    modes.apply_setpoint(desired, "PcC", 21, NOW)
    assert desired["PcC_TSP"]["e"] == "2026-10-18T09:05:00.000Z"


def test_setpoint_while_off():
    """E_CLL=1 written from outside stays until the relay switches: with the
    radiator off the IRSAP app showed a heating flame. CSP keeps the
    antifreeze value while off."""
    desired = copy.deepcopy(OFF)
    modes.apply_setpoint(desired, "PcC", 26, NOW)
    assert (desired["E_CLL"], desired["E_CPC"]) == (0, 0)
    assert desired["PcC_MSP"]["p"]["v"] == 260
    assert desired["PcC_CSP"]["p"]["v"] == 50


def test_preset_manual_keeps_the_applied_temperature():
    desired = copy.deepcopy(TEMPORARY)
    modes.apply_preset(desired, "PcC", "manual")
    assert desired["PcC_MOD"] == 1
    assert desired["PcC_MSP"]["p"]["v"] == 190
    assert desired["PcC_TSP"]["e"] == modes.NO_EXPIRY


def test_preset_schedule_cancels_temporary():
    desired = copy.deepcopy(TEMPORARY)
    desired["PcC_MOD"] = 1
    modes.apply_preset(desired, "PcC", "schedule")
    assert desired["PcC_MOD"] == 2
    assert desired["PcC_TSP"]["e"] == modes.NO_EXPIRY


def test_preset_schedule_needs_a_schedule():
    with pytest.raises(ValueError):
        modes.apply_preset(copy.deepcopy(MANUAL_ON), "PcC", "schedule")


# --- entity -------------------------------------------------------------

ENTITY = "climate.bagno_radiator"


async def _no_sleep(*args):
    return None


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _schedule_shadow(shadow, temporary=False):
    desired = shadow["state"]["desired"]
    desired.update(
        {
            "E_SCH": [SCHEDULE_ENTRY],
            "PTO_WSC": SCHEDULE_ID,
            "PTO_MOD": 2,
            "PTO_ENB": 1,
            "PTO_MSP": {"p": {"k": "MANUAL", "m": 3, "u": 0, "v": 270}},
            "PTO_TSP": {
                "p": {"u": 0, "v": 190 if temporary else 260, "m": 3, "k": "TEMPORARY"},
                "e": "2099-01-01T00:00:00.000Z" if temporary else modes.NO_EXPIRY,
            },
            "PTO_CSP": {
                "p": {"k": "CURRENT", "m": 3, "u": 0, "v": 190 if temporary else 180},
                "e": "2099-01-01T00:00:00.000Z",
            },
        }
    )


async def test_entity_in_schedule_mode(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    _schedule_shadow(shadow, temporary=True)
    await _setup(hass, config_entry)
    state = hass.states.get(ENTITY)
    assert state.attributes["preset_mode"] == "schedule"
    assert state.attributes["preset_modes"] == ["manual", "schedule"]
    assert state.attributes["temperature"] == 19.0  # applied, not the 27 manual
    assert state.attributes["temporary_until"].startswith("2099-01-01")


async def test_entity_switches_preset(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow, shadow
):
    _schedule_shadow(shadow, temporary=True)
    await _setup(hass, config_entry)

    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": ENTITY, "preset_mode": "manual"},
            blocking=True,
        )
    sent = mock_update_shadow.call_args.args[3]["state"]["desired"]
    assert sent["PTO_MOD"] == 1
    assert sent["PTO_MSP"]["p"]["v"] == 190
    state = hass.states.get(ENTITY)
    assert state.attributes["preset_mode"] == "manual"
    assert state.attributes["temperature"] == 19.0


async def test_entity_schedule_preset_unavailable_without_schedule(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow
):
    from homeassistant.exceptions import ServiceValidationError

    await _setup(hass, config_entry)
    assert hass.states.get(ENTITY).attributes["preset_modes"] == ["manual"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": ENTITY, "preset_mode": "schedule"},
            blocking=True,
        )
    mock_update_shadow.assert_not_called()
