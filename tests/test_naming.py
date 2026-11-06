"""Entity names: Home Assistant composes them from the device name and a
translated entity name, and keeps the entity_ids of existing installs."""

import pytest

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _friendly(hass, entity_id):
    return hass.states.get(entity_id).attributes["friendly_name"]


async def test_names_in_english(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"]["PTO_X_lock"] = 0
    await _setup(hass, config_entry)

    # the climate entity is the device's main feature: it takes the device name
    assert _friendly(hass, "climate.bagno") == "Bagno"
    assert _friendly(hass, "sensor.bagno_hysteresis") == "Bagno Hysteresis"
    assert _friendly(hass, "switch.bagno_child_lock") == "Bagno Child lock"
    assert _friendly(hass, "light.bagno_led") == "Bagno LED"
    # standard device class, no name of its own: Home Assistant names it
    assert _friendly(hass, "sensor.bagno_signal_strength") == "Bagno Signal strength"


async def test_names_follow_the_language(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"]["PTO_X_lock"] = 0
    hass.config.language = "it"
    await _setup(hass, config_entry)
    registry = er.async_get(hass)

    def by_unique_id(domain, unique_id):
        # new entity_ids follow the language too (sensor.bagno_isteresi)
        return registry.async_get_entity_id(domain, "irsap_ha", unique_id)

    hysteresis = by_unique_id("sensor", "Bagno_hysteresis")
    assert hysteresis == "sensor.bagno_isteresi"
    assert _friendly(hass, hysteresis) == "Bagno Isteresi"
    assert (
        _friendly(hass, by_unique_id("switch", "Bagno_child_lock_switch"))
        == "Bagno Blocco bambini"
    )
    assert (
        _friendly(hass, by_unique_id("sensor", "Bagno_temperature_offset"))
        == "Bagno Compensazione della temperatura"
    )


async def test_names_follow_a_renamed_device(
    hass, config_entry, mock_login, mock_get_shadow
):
    await _setup(hass, config_entry)
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier(
        ("irsap_ha", "Bagno"), config_entry.entry_id
    )
    devices.async_update_device(device.id, name_by_user="Scaldasalviette")
    await hass.async_block_till_done()

    assert _friendly(hass, "climate.bagno") == "Scaldasalviette"
    assert _friendly(hass, "sensor.bagno_hysteresis") == "Scaldasalviette Hysteresis"


async def test_upgrade_keeps_entity_ids(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """Entities created by an older version keep their entity_id: only the
    friendly name changes."""
    shadow["state"]["desired"]["PTO_X_lock"] = 0
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = {
        ("climate", "Bagno_climate"): "bagno_radiator",
        ("sensor", "Bagno_wifi_signal"): "bagno_wifi_signal_strength",
        ("switch", "Bagno_child_lock_switch"): "bagno_child_lock",
    }
    for (domain, unique_id), object_id in old.items():
        registry.async_get_or_create(
            domain,
            "irsap_ha",
            unique_id,
            suggested_object_id=object_id,
            config_entry=config_entry,
        )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _friendly(hass, "climate.bagno_radiator") == "Bagno"
    assert (
        _friendly(hass, "sensor.bagno_wifi_signal_strength") == "Bagno Signal strength"
    )
    assert _friendly(hass, "switch.bagno_child_lock") == "Bagno Child lock"
    assert hass.states.get("climate.bagno") is None


@pytest.mark.parametrize("language", ["en", "it"])
async def test_no_two_entities_share_a_name(
    hass, config_entry, mock_login, mock_get_shadow, shadow, language
):
    """Until 1.7 the read-only status sensors sit next to the switches that
    replace them: they need names of their own."""
    shadow["state"]["desired"].update(
        {"PTO_X_lock": 0, "PTO_X_standby": 0, "PTO_X_OpenWindowSensorEnabled": 1}
    )
    hass.config.language = language
    await _setup(hass, config_entry)

    names = [state.attributes["friendly_name"] for state in hass.states.async_all()]
    assert len(names) == len(set(names)), sorted(names)
