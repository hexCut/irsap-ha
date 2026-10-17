"""Snapshot of everything the integration shows to the user.

For a few shadows, every entity created by the integration is recorded with
its registry entry (unique id, category, enabled or not), its state and
attributes, and its device. The result is compared with
``tests/snapshots/test_snapshots.ambr``.

If a change alters what users see (a unit, a name, an attribute, an entity
added, removed or disabled), these tests fail. When the change is intended,
regenerate the snapshots and commit them with the change:

    pytest tests/test_snapshots.py --snapshot-update

and list the difference under "Breaking / visible changes" in the PR.
"""

import copy
from unittest.mock import patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension

from custom_components.irsap_ha.const import DOMAIN

from .conftest import SHADOW


def _towel_warmer():
    """One towel warmer, firmware 3.22: no air sensors, device linked to the
    zone through a group, status LED only (as reported on #21, #22, #25, #27)."""
    shadow = copy.deepcopy(SHADOW)
    shadow["clientId"] = "dev-RE_aa:bb:cc:dd:ee:ff#RE"
    # status LED only, not a controllable light: no light entity (#21)
    shadow["state"]["desired"].pop("PTO_X_LED_CSP")
    shadow["state"]["desired"].pop("PTO_X_LED_MSP")
    shadow["state"]["desired"].update(
        {
            "E_CLL": 0,
            "PTO_MOD": 1,
            "GkV_PLD": "PTO",
            "GkV_MID": "DRk",
            "DRk_CNT": "RE_aa:bb:cc:dd:ee:ff",
            "DRk_FWV": "3.22",
            "DRk_TYP": "RE",
            "DRk_SLV": -61,
            "DRk_LUP": "2026-10-14T18:50:51.000Z",
            "DRk_X_filPiloteEnabled": 0,
            "DRk_X_filPiloteStatus": 0,
            "DRk_X_standby": 0,
            "DRk_X_OpenWindowSensorEnabled": 1,
            "DRk_X_OpenWindowDetected": 0,
            "DRk_X_OpenWindowSensorOffTime": 30,
            "DRk_X_temperatureSensorOffset": 0,
            "DRk_X_hysteresis": 2,
            "DRk_X_vocValue": 65535,
            "DRk_X_co2Value": 65535,
            "DRk_X_lock": 0,
            "PTO_AIQ": None,
        }
    )
    return shadow


def _two_radiators():
    """Two radiators, devices listed in the opposite order of the zones, one
    with air sensors and one switched off."""
    shadow = copy.deepcopy(SHADOW)
    desired = {
        "E_NAM": "Casa",
        "E_CLL": 1,
        "AAA_NAM": "Bagno",
        "AAA_TMP": 230,
        "AAA_ENB": 1,
        "AAA_MSP": {"p": {"u": 0, "v": 240, "m": 3}},
        "AAA_CSP": {"p": {"u": 0, "v": 240, "m": 3}},
        "AAA_AIQ": None,
        "BBB_NAM": "Camera",
        "BBB_TMP": 190,
        "BBB_ENB": 0,
        "BBB_MSP": {"p": {"u": 0, "v": 200, "m": 3}},
        "BBB_CSP": {"p": {"u": 0, "v": 50, "m": 3}},
        "BBB_AIQ": 3,
        "D2_CNT": "RE_mac-2",
        "D2_FWV": "2.0",
        "D2_TYP": "RE",
        "D2_SLV": -70,
        "D2_X_ipAddress": "10.0.0.2",
        "D2_X_hysteresis": 3,
        "D2_X_co2Value": 650,
        "D2_X_vocValue": 120,
        "D1_CNT": "RE_mac-1",
        "D1_FWV": "1.0",
        "D1_TYP": "RE",
        "D1_SLV": -50,
        "D1_X_ipAddress": "10.0.0.1",
        "D1_X_hysteresis": 2,
        "D1_X_co2Value": 65535,
        "D1_X_vocValue": 65535,
        "G1_PLD": "AAA",
        "G1_MID": "D1",
        "G2_PLD": "BBB",
        "G2_MID": "D2",
    }
    shadow["clientId"] = "dev-RE_mac-1#RE"
    shadow["state"]["desired"] = desired
    return shadow


SHADOWS = {
    "default": lambda: copy.deepcopy(SHADOW),
    "towel_warmer": _towel_warmer,
    "two_radiators": _two_radiators,
}


def _describe(hass, entry):
    """Everything about the entry's entities that a user can see."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entities = []
    for reg in sorted(
        er.async_entries_for_config_entry(entity_registry, entry.entry_id),
        key=lambda e: e.entity_id,
    ):
        device = device_registry.async_get(reg.device_id) if reg.device_id else None
        state = hass.states.get(reg.entity_id)
        entities.append(
            {
                "entity_id": reg.entity_id,
                "unique_id": reg.unique_id,
                "entity_category": reg.entity_category,
                "disabled_by": reg.disabled_by,
                "device": None
                if device is None
                else {
                    "name": device.name,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "sw_version": device.sw_version,
                },
                "state": None if state is None else state.state,
                "attributes": None if state is None else dict(state.attributes),
            }
        )
    return entities


@pytest.mark.parametrize("name", list(SHADOWS))
async def test_entities(hass, config_entry, mock_login, snapshot, name):
    async def _get(hass, token, envID):
        return SHADOWS[name]()

    with patch("custom_components.irsap_ha.api.async_get_shadow", side_effect=_get):
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        assert _describe(hass, config_entry) == snapshot

    assert DOMAIN in hass.data


def test_snapshots_use_home_assistant_extension(snapshot):
    """Snapshots must be read from tests/snapshots/ with HA's serializer,
    whatever order the pytest plugins were installed in (see conftest)."""
    assert snapshot.extension_class is HomeAssistantSnapshotExtension
