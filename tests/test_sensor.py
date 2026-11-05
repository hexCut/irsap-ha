"""Diagnostic sensors follow the coordinator data."""

from datetime import timedelta

from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_sensors_refresh_from_coordinator(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    desired = shadow["state"]["desired"]
    desired["PTO_SLV"] = -60
    desired["PTO_X_hysteresis"] = 2
    await _setup(hass, config_entry)

    assert hass.states.get("sensor.bagno_wifi_signal_strength").state == "-60"
    assert hass.states.get("sensor.bagno_ip_address").state == "192.168.0.50"
    assert hass.states.get("sensor.bagno_hysteresis").state == "0.2"
    # setup reads the coordinator's first refresh, no extra fetch for sensors
    assert mock_get_shadow.call_count == 1

    desired["PTO_SLV"] = -71
    desired["PTO_X_ipAddress"] = "192.168.0.51"
    desired["PTO_X_hysteresis"] = 3
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.bagno_wifi_signal_strength").state == "-71"
    assert hass.states.get("sensor.bagno_ip_address").state == "192.168.0.51"
    assert hass.states.get("sensor.bagno_hysteresis").state == "0.3"
    assert mock_get_shadow.call_count == 2  # still one fetch per tick for everything


async def test_update_entity_on_sensor_refreshes(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, pref_disable_polling=True)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_get_shadow.reset_mock()

    shadow["state"]["desired"]["PTO_X_ipAddress"] = "192.168.0.99"
    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {"entity_id": "sensor.bagno_ip_address"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert mock_get_shadow.call_count == 1
    assert hass.states.get("sensor.bagno_ip_address").state == "192.168.0.99"


async def test_sensor_keeps_values_if_radiator_missing(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"]["PTO_SLV"] = -60
    await _setup(hass, config_entry)

    # a refresh without the radiator (e.g. partial shadow) keeps the last values
    shadow["state"]["desired"] = {"E_NAM": "Casa"}
    coordinator = hass.data["irsap_ha"][config_entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bagno_wifi_signal_strength").state == "-60"


# --- per-model sensors --------------------------------------------------

VOC = "sensor.bagno_voc"
CO2 = "sensor.bagno_co2"
AIQ = "sensor.bagno_air_quality"


async def test_model_without_air_sensors(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """VOC/CO2 at 65535 and AIQ null (a towel warmer, fw 3.22): created
    disabled, so they don't show up, and no 65535 anywhere."""
    desired = shadow["state"]["desired"]
    desired.update({"PTO_X_vocValue": 65535, "PTO_X_co2Value": 65535, "PTO_AIQ": None})
    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    for entity_id in (VOC, CO2, AIQ):
        entry = registry.async_get(entity_id)
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, entity_id
        assert hass.states.get(entity_id) is None


async def test_model_with_air_sensors(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """A radiator that measures CO2/VOC/air quality keeps all three, with units."""
    desired = shadow["state"]["desired"]
    desired.update({"PTO_X_vocValue": 120, "PTO_X_co2Value": 650, "PTO_AIQ": 2})
    await _setup(hass, config_entry)

    co2 = hass.states.get(CO2)
    assert co2.state == "650"
    assert co2.attributes["unit_of_measurement"] == "ppm"
    assert co2.attributes["device_class"] == "carbon_dioxide"
    assert hass.states.get(VOC).state == "120"
    assert hass.states.get(AIQ).state == "2"

    # a transient 65535 (e.g. sensor warming up) is "unknown", not 65535
    desired["PTO_X_co2Value"] = 65535
    coordinator = hass.data["irsap_ha"][config_entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(CO2).state == "unknown"


async def test_existing_unsupported_sensor_is_disabled_then_re_enabled(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """Upgrade path: an enabled CO2 sensor from an older version gets disabled,
    and comes back on its own once the radiator reports a real value."""
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    unique_id = "Bagno_co2"
    registry.async_get_or_create(
        "sensor",
        "irsap_ha",
        unique_id,
        suggested_object_id="bagno_co2",
        config_entry=config_entry,
    )
    shadow["state"]["desired"]["PTO_X_co2Value"] = 65535
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(CO2).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    shadow["state"]["desired"]["PTO_X_co2Value"] = 640
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(CO2).disabled_by is None


async def test_sensor_disabled_by_user_stays_disabled(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "irsap_ha",
        "Bagno_co2",
        suggested_object_id="bagno_co2",
        config_entry=config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    shadow["state"]["desired"]["PTO_X_co2Value"] = 640
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(CO2).disabled_by is er.RegistryEntryDisabler.USER


async def test_units_and_categories(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    desired = shadow["state"]["desired"]
    desired.update(
        {
            "PTO_SLV": -55,
            "PTO_X_hysteresis": 2,
            "PTO_X_temperatureSensorOffset": -5,
            "PTO_X_OpenWindowSensorOffTime": 30,
        }
    )
    await _setup(hass, config_entry)

    wifi = hass.states.get("sensor.bagno_wifi_signal_strength")
    assert wifi.state == "-55"
    assert wifi.attributes["unit_of_measurement"] == "dBm"
    assert wifi.attributes["device_class"] == "signal_strength"
    assert (
        hass.states.get("sensor.bagno_hysteresis").attributes["unit_of_measurement"]
        == "°C"
    )
    assert hass.states.get("sensor.bagno_temperature_offset").state == "-0.5"
    window = hass.states.get("sensor.bagno_open_window_offset")
    assert window.state == "30"
    assert window.attributes["unit_of_measurement"] == "min"

    registry = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if entry.domain == "sensor":
            assert entry.entity_category is EntityCategory.DIAGNOSTIC, entry.entity_id


async def test_missing_numeric_values_are_unknown(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """A model that doesn't report Wi-Fi or hysteresis at all doesn't crash."""
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.bagno_wifi_signal_strength").state == "unknown"
    assert hass.states.get("sensor.bagno_hysteresis").state == "unknown"


async def test_sensor_re_enabled_as_soon_as_reported(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """CO2 at 65535 at startup (warming up), then a real value: re-enabled
    without waiting for a restart."""
    shadow["state"]["desired"]["PTO_X_co2Value"] = 65535
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get(CO2).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    shadow["state"]["desired"]["PTO_X_co2Value"] = 610
    coordinator = hass.data["irsap_ha"][config_entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get(CO2).disabled_by is None
