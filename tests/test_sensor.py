"""Diagnostic sensors follow the coordinator data."""

from datetime import timedelta

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
    assert hass.states.get("sensor.bagno_hysteresis").state == "2"
    # setup reads the coordinator's first refresh, no extra fetch for sensors
    assert mock_get_shadow.call_count == 1

    desired["PTO_SLV"] = -71
    desired["PTO_X_ipAddress"] = "192.168.0.51"
    desired["PTO_X_hysteresis"] = 3
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.bagno_wifi_signal_strength").state == "-71"
    assert hass.states.get("sensor.bagno_ip_address").state == "192.168.0.51"
    assert hass.states.get("sensor.bagno_hysteresis").state == "3"
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
