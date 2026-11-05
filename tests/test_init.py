"""Setup, coordinator, reload and unload."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.irsap_ha.const import CONF_SCAN_INTERVAL, DOMAIN
from custom_components.irsap_ha.device_manager import device_manager


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_single_login_and_fetch(
    hass, config_entry, mock_login, mock_get_shadow
):
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.bagno_radiator").state == "heat"
    assert hass.states.get("climate.bagno_radiator").attributes["current_temperature"] == 21.5
    assert hass.states.get("light.bagno_led").state == "on"
    assert hass.states.get("sensor.bagno_ip_address").state == "192.168.0.50"
    # Setup of all three platforms: one login, one GetShadow
    assert mock_login.call_count == 1
    assert mock_get_shadow.call_count == 1


async def test_one_fetch_per_interval_for_all_entities(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    await _setup(hass, config_entry)
    mock_get_shadow.reset_mock()

    shadow["state"]["desired"]["PTO_TMP"] = 230
    shadow["state"]["desired"]["PTO_X_LED_ENB"] = 0
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert mock_get_shadow.call_count == 1  # shared by climate and light
    assert hass.states.get("climate.bagno_radiator").attributes["current_temperature"] == 23.0
    assert hass.states.get("light.bagno_led").state == "off"
    assert mock_login.call_count == 1  # token reused


async def test_scan_interval_option(hass, config_entry, mock_login, mock_get_shadow):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCAN_INTERVAL: 300}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    assert coordinator.update_interval == timedelta(seconds=300)


async def test_polling_disabled_no_timer_but_update_entity_works(
    hass, config_entry, mock_login, mock_get_shadow
):
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, pref_disable_polling=True)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_get_shadow.reset_mock()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
    await hass.async_block_till_done()
    assert mock_get_shadow.call_count == 0

    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {"entity_id": "climate.bagno_radiator"},
        blocking=True,
    )
    assert mock_get_shadow.call_count == 1


async def test_fetch_failure_relogs_once_then_unavailable(
    hass, config_entry, mock_login, mock_get_shadow
):
    await _setup(hass, config_entry)
    mock_get_shadow.side_effect = None
    mock_get_shadow.return_value = None
    mock_get_shadow.reset_mock()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    # cached token, then one forced re-login and retry
    assert mock_get_shadow.call_count == 2
    assert mock_login.call_count == 2
    assert hass.states.get("climate.bagno_radiator").state == "unavailable"


async def test_reload_does_not_leak_devices(
    hass, config_entry, mock_login, mock_get_shadow
):
    await _setup(hass, config_entry)
    assert len(device_manager.get_devices()) == 1

    for interval in (120, 180, 240):
        hass.config_entries.async_update_entry(
            config_entry, options={CONF_SCAN_INTERVAL: interval}
        )
        await hass.async_block_till_done()
        assert config_entry.state is ConfigEntryState.LOADED
        assert len(device_manager.get_devices()) == 1

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    assert coordinator.update_interval == timedelta(seconds=240)
    assert len(hass.states.async_entity_ids("climate")) == 1


async def test_unload_clears_state(hass, config_entry, mock_login, mock_get_shadow):
    await _setup(hass, config_entry)
    assert hass.data[DOMAIN]["token"]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert DOMAIN not in hass.data
    assert device_manager.get_devices() == []
