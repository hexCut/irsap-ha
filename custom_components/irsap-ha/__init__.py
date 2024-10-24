import logging
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    # "Set up the integration."
    _LOGGER.debug("Setting up your integration")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry):
    # "Set up the radiators integration from a config entry."
    _LOGGER.debug("Setting up entry: %s", entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "sensor"])

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    # "Unload a config entry."
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)

    # Rimuovi i dispositivi associati all'entrata di configurazione
    # Puoi aggiungere la logica per rimuovere i dispositivi se necessario
    # Ad esempio, puoi interagire con il device registry
    device_registry = dr.async_get(hass)
    devices = device_registry.async_entries_for_config_entry(entry.entry_id)

    for device in devices:
        device_registry.async_remove_device(device.id)

    return True


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
