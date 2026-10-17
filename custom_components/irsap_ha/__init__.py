from homeassistant.helpers import device_registry as dr
from .const import DOMAIN

import logging
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from .api import WRITE_DATA_KEYS
from .auth import AUTH_DATA_KEYS, store_credentials
from .coordinator import IrsapCoordinator
from .device_manager import device_manager
from .setup import async_setup as setup_component

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["climate", "sensor", "light"]


async def async_setup(hass: HomeAssistant, config: dict):
    return await setup_component(hass, config)


async def async_setup_entry(hass, config_entry):
    """Imposta il custom component"""
    hass.data.setdefault(DOMAIN, {})
    store_credentials(
        hass, config_entry.data["username"], config_entry.data["password"]
    )
    # I dispositivi vengono registrati di nuovo dalla piattaforma climate
    device_manager.clear()

    # Un solo GetShadow per intervallo, condiviso da tutte le entità
    coordinator = IrsapCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][config_entry.entry_id] = {
        "envID": config_entry.data["envID"],
        "coordinator": coordinator,
    }

    # Carica prima 'climate' e poi 'sensor'
    await hass.config_entries.async_forward_entry_setups(config_entry, ["climate"])
    await hass.config_entries.async_forward_entry_setups(config_entry, ["sensor"])
    await hass.config_entries.async_forward_entry_setups(config_entry, ["light"])

    # Ricarica l'integrazione quando cambiano le opzioni (es. intervallo di aggiornamento)
    config_entry.async_on_unload(config_entry.add_update_listener(_async_reload_entry))

    return True


async def _async_reload_entry(hass: HomeAssistant, config_entry) -> None:
    """Reload the integration after its options change."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass, config_entry):
    """Scarica le entità del custom component"""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        data = hass.data[DOMAIN]
        data.pop(config_entry.entry_id, None)
        # Credenziali, token e ultima scrittura: al prossimo setup si riparte da zero
        for key in AUTH_DATA_KEYS + WRITE_DATA_KEYS:
            data.pop(key, None)
        if not data:
            hass.data.pop(DOMAIN)
        # Evita che un reload accumuli RadiatorDevice duplicati con token vecchi
        device_manager.clear()
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
