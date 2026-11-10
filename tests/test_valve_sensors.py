"""Diagnostic entities for Smart Valve valves and ambient sensors (Termostato)."""

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.irsap_ha.const import DOMAIN

# A Smart Valve zone ("Cameretta"): one valve (Dv1) and one ambient sensor
# (Ds1), both wired through group Gsc and gateway Dpc ("Unità di Connessione").
# Ds1 is linked twice (dedup case) and one link is orphaned (device with no
# keys at all, a stale pairing).
VALVE_ZONE = {
    "Cam_NAM": "Cameretta",
    "Cam_TMP": 207,
    "Cam_ENB": 1,
    "Gsc_PLD": "Cam",
    "Gsc_MID": "Dpc",
    "Wv1_GID": "Gsc",
    "Wv1_DID": "Dv1",
    "Ws1_GID": "Gsc",
    "Ws1_DID": "Ds1",
    "Ws1b_GID": "Gsc",
    "Ws1b_DID": "Ds1",  # duplicate link to the same ambient sensor
    "Worph_GID": "Gsc",
    "Worph_DID": "Dorphan",  # stale link: Dorphan has no keys at all
    "Dpc_TYP": "SYS",
    "Dpc_FWV": "1.24",
    "Dpc_LUP": "2026-11-06T09:40:46.275Z",
    "Dpc_X_RF_Power": 13,
    "Dpc_ERR": [],
    "Dv1_TYP": "MEH",
    "Dv1_FWV": "1.25",
    "Dv1_X_BatteryVoltage": 30,
    "Dv1_X_DBLevel": -75,
    "Dv1_X_ValveOpen": 0,
    "Dv1_X_WaterTemp": 210,
    "Dv1_X_OpenWind": 1,
    "Dv1_X_EnvTemp": 208,
    "Dv1_X_CalcTemp": 207,
    "Dv1_X_BlockMode": 1,
    "Dv1_X_AntiWhistle": 5,
    "Dv1_LUP": "2026-11-06T09:40:46.275Z",
    "Dv1_ERR": [],
    "Ds1_TYP": "SU",
    "Ds1_FWV": "1.15",
    "Ds1_X_BatteryVoltage": 27,
    "Ds1_X_DBLevel": -64,
    "Ds1_X_EnvHumidity": 58,
    "Ds1_X_CO2Value": 400,
    "Ds1_X_VocValue": 0,
    "Ds1_X_VocLevel": 1,
    "Ds1_X_EnvTemp": 207,
    "Ds1_LUP": "2026-11-06T09:40:46.275Z",
    "Ds1_ERR": [],
}

VALVE = "sensor.cameretta_valvola_battery_voltage"
VALVE_RSSI = "sensor.cameretta_valvola_rssi"
VALVE_OPEN = "sensor.cameretta_valvola_valve_opening"
VALVE_WATER_TEMP = "sensor.cameretta_valvola_water_temperature"
VALVE_OPEN_WINDOW = "sensor.cameretta_valvola_open_window_enabled"
VALVE_TEMPERATURE = "sensor.cameretta_valvola_temperature"
VALVE_LAST_UPDATE = "sensor.cameretta_valvola_last_update"
VALVE_SETPOINT = "sensor.cameretta_valvola_setpoint_temperature"
VALVE_CHILD_LOCK = "sensor.cameretta_valvola_child_lock"
VALVE_ANTI_WHISTLE = "sensor.cameretta_valvola_anti_whistle"
TERMOSTATO_TEMPERATURE = "sensor.cameretta_termostato_temperature"
TERMOSTATO_LAST_UPDATE = "sensor.cameretta_termostato_last_update"
TERMOSTATO_BATTERY = "sensor.cameretta_termostato_battery_voltage"
TERMOSTATO_HUMIDITY = "sensor.cameretta_termostato_humidity"
TERMOSTATO_CO2 = "sensor.cameretta_termostato_carbon_dioxide"  # device_class default name, like Co2Sensor
TERMOSTATO_VOC = "sensor.cameretta_termostato_voc"
TERMOSTATO_VOC_LEVEL = "sensor.cameretta_termostato_voc_level"


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_valve_and_ambient_sensor_entities(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"].update(VALVE_ZONE)
    await _setup(hass, config_entry)

    valve_battery = hass.states.get(VALVE)
    assert valve_battery.state == "3.0"
    assert valve_battery.attributes["unit_of_measurement"] == "V"
    assert valve_battery.attributes["device_class"] == "voltage"

    assert hass.states.get(VALVE_RSSI).state == "-75"
    assert hass.states.get(VALVE_OPEN).state == "0"
    assert hass.states.get(VALVE_WATER_TEMP).state == "21.0"
    assert hass.states.get(VALVE_OPEN_WINDOW).state == "Enabled"
    # Each physical device reports its own measured temperature (distinct
    # from the zone's official temperature, shown on the climate entity)
    assert hass.states.get(VALVE_TEMPERATURE).state == "20.8"
    assert hass.states.get(TERMOSTATO_TEMPERATURE).state == "20.7"
    assert hass.states.get(VALVE_LAST_UPDATE).state not in (None, "unknown")
    assert hass.states.get(TERMOSTATO_LAST_UPDATE).state not in (None, "unknown")
    assert hass.states.get(VALVE_SETPOINT).state == "20.7"
    assert hass.states.get(VALVE_CHILD_LOCK).state == "Enabled"
    anti_whistle = hass.states.get(VALVE_ANTI_WHISTLE)
    assert anti_whistle.state == "5"
    assert anti_whistle.attributes["unit_of_measurement"] == "%"

    termostato_battery = hass.states.get(TERMOSTATO_BATTERY)
    assert termostato_battery.state == "2.7"
    assert hass.states.get(TERMOSTATO_HUMIDITY).state == "58"
    co2 = hass.states.get(TERMOSTATO_CO2)
    assert co2.state == "400"
    assert co2.attributes["unit_of_measurement"] == "ppm"
    assert hass.states.get(TERMOSTATO_VOC).state == "0"
    assert hass.states.get(TERMOSTATO_VOC_LEVEL).state == "1"

    # The plain Wi-Fi radiator already in the base shadow is unaffected (looked
    # up by unique_id, not a guessed entity_id slug, since the dev branch's
    # entity-naming rework can change the friendly name / auto-generated slug)
    registry = er.async_get(hass)
    wifi_entity_id = registry.async_get_entity_id("sensor", DOMAIN, "Bagno_wifi_signal")
    assert wifi_entity_id is not None
    assert hass.states.get(wifi_entity_id) is not None


async def test_error_sensors_by_unique_id(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"].update(VALVE_ZONE)
    await _setup(hass, config_entry)

    registry = er.async_get(hass)

    valve_error_id = registry.async_get_entity_id("sensor", DOMAIN, "Dv1_errors")
    assert valve_error_id is not None
    assert hass.states.get(valve_error_id).state == "No errors"

    gateway_rf_id = registry.async_get_entity_id("sensor", DOMAIN, "Dpc_rf_power")
    assert gateway_rf_id is not None
    assert hass.states.get(gateway_rf_id).state == "13"

    gateway_error_id = registry.async_get_entity_id("sensor", DOMAIN, "Dpc_errors")
    assert gateway_error_id is not None
    assert hass.states.get(gateway_error_id).state == "No errors"


async def test_valve_and_termostato_are_separate_devices_via_the_gateway(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"].update(VALVE_ZONE)
    await _setup(hass, config_entry)

    device_registry = dr.async_get(hass)
    gateway = device_registry.async_get_device_by_identifier((DOMAIN, "Dpc"), config_entry.entry_id)
    valve = device_registry.async_get_device_by_identifier((DOMAIN, "Dv1"), config_entry.entry_id)
    termostato = device_registry.async_get_device_by_identifier((DOMAIN, "Ds1"), config_entry.entry_id)

    assert gateway is not None and gateway.name == "Unità di Connessione"
    assert valve is not None and valve.name == "Cameretta Valvola"
    assert termostato is not None and termostato.name == "Cameretta Termostato"
    assert valve.via_device_id == gateway.id
    assert termostato.via_device_id == gateway.id
    assert valve.id != termostato.id


async def test_gateway_has_its_own_last_update_sensor(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """The gateway gets its own Last Update, alongside (not instead of) the
    per-device ones: useful to compare and spot a device lagging behind."""
    shadow["state"]["desired"].update(VALVE_ZONE)
    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, "Dpc_last_update")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state not in (None, "unknown")


async def test_duplicate_link_does_not_duplicate_entities(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """Ds1 is linked twice in VALVE_ZONE: must still produce one entity."""
    shadow["state"]["desired"].update(VALVE_ZONE)
    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    matches = [
        entry
        for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id)
        if entry.unique_id == "Ds1_humidity"
    ]
    assert len(matches) == 1


async def test_orphan_link_creates_no_entity(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    shadow["state"]["desired"].update(VALVE_ZONE)
    await _setup(hass, config_entry)

    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device_by_identifier((DOMAIN, "Dorphan"), config_entry.entry_id)
        is None
    )


async def test_plain_wifi_radiator_shadow_creates_no_linked_devices(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """The base shadow (one Wi-Fi radiator, no groups/links) must not gain a
    gateway device or any valve/Termostato entity."""
    await _setup(hass, config_entry)

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(
        device_registry, config_entry.entry_id
    ):
        assert device.name != "Unità di Connessione"
    assert hass.states.get(VALVE) is None
    assert hass.states.get(TERMOSTATO_BATTERY) is None
