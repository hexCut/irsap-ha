from homeassistant.helpers import device_registry as dr
from .const import DOMAIN

import logging
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from .setup import async_setup as setup_component

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    return await setup_component(hass, config)


async def async_setup_entry(hass, config_entry):
    """Imposta il custom component"""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = {
        "token": config_entry.data["token"],
        "envID": config_entry.data["envID"],
    }

    # Carica prima 'climate' e poi 'sensor'
    await hass.config_entries.async_forward_entry_setups(config_entry, ["climate"])
    await hass.config_entries.async_forward_entry_setups(config_entry, ["sensor"])

    return True


async def async_unload_entry(hass, config_entry):
    """Scarica le entità del custom component"""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, ["climate", "sensor"]
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: config_entries.ConfigEntry, device_id: str
) -> None:
    """Remove a device from the config entry."""
    device_registry = dr.async_get(hass)

    if device_registry.async_get_device({(dr.CONNECTION_NETWORK_MAC, device_id)}):
        device_registry.async_remove_device(device_id)
        _LOGGER.debug(f"Removed device {device_id} from config entry {entry.entry_id}")
    else:
        _LOGGER.warning(
            f"Device {device_id} not found in config entry {entry.entry_id}"
        )
