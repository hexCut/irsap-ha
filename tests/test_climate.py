"""Write paths use the cached token and keep the new state."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.irsap_ha.const import WRITE_SETTLE_TIME

ENTITY = "climate.bagno_radiator"


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _no_sleep(*args):
    return None


async def test_set_temperature_uses_cached_token(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow
):
    await _setup(hass, config_entry)
    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY, "temperature": 24},
            blocking=True,
        )

    assert mock_login.call_count == 1  # no new SRP login for the command
    token = mock_update_shadow.call_args.args[1]
    sent = mock_update_shadow.call_args.args[3]
    assert token == "token-1"
    assert sent["state"]["desired"]["PTO_MSP"]["p"]["v"] == 240
    assert hass.states.get(ENTITY).attributes["temperature"] == 24


async def test_set_hvac_mode_and_settle_time(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow
):
    await _setup(hass, config_entry)
    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY, "hvac_mode": "off"},
            blocking=True,
        )
    sent = mock_update_shadow.call_args.args[3]
    assert sent["state"]["desired"]["PTO_ENB"] == 0
    assert hass.states.get(ENTITY).state == "off"
    assert mock_login.call_count == 1

    # The cloud still reports ENB=1: a refresh right after the command is ignored
    coordinator = hass.data["irsap_ha"][config_entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "off"

    # ...but once the settle time is over the cloud state wins again
    with patch(
        "custom_components.irsap_ha.climate.time.monotonic",
        return_value=10**9 + WRITE_SETTLE_TIME,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "heat"


async def test_write_retries_with_new_token(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow, shadow
):
    await _setup(hass, config_entry)
    calls = {"n": 0}

    async def flaky(hass_, token, envID):
        calls["n"] += 1
        return None if token == "token-1" else shadow

    mock_get_shadow.side_effect = flaky
    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY, "temperature": 22},
            blocking=True,
        )
    assert mock_login.call_count == 2
    assert mock_update_shadow.call_args.args[1] == "token-2"


async def test_missing_temperature_keeps_last_value(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    await _setup(hass, config_entry)
    del shadow["state"]["desired"]["PTO_TMP"]
    for i in range(3):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61 * (i + 1)))
        await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["current_temperature"] == 21.5
    from homeassistant.components import persistent_notification

    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert "radiator_Bagno Radiator_temperature_warning" in notifications


async def test_set_temperature_keeps_hvac_mode_off(
    hass, config_entry, mock_login, mock_get_shadow, mock_update_shadow, shadow
):
    """A setpoint change on a radiator that is off doesn't turn it on in HA."""
    shadow["state"]["desired"]["PTO_ENB"] = 0
    await _setup(hass, config_entry)
    assert hass.states.get(ENTITY).state == "off"

    with patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY, "temperature": 24},
            blocking=True,
        )

    sent = mock_update_shadow.call_args.args[3]
    assert sent["state"]["desired"]["PTO_ENB"] == 0  # the write leaves _ENB alone
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes["temperature"] == 24
