import logging
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration."""
    _LOGGER.debug("Setting up your integration.")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry):
    """Set up the radiators integration from a config entry."""

    # Chiama la funzione setup_climate passando add_entities
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)
    return True
