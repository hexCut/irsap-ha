"""Radiator settings exposed as switches: child lock, standby, open window.

Verified on a real radiator (fw 3.22): the radiator accepts these values
from the cloud and applies them (it rewrites the shadow itself):
- child lock: +/- on the radiator beep twice and do nothing;
- standby: purple LED, the radiator stops heating and ignores app and keys;
- open window detection: the switch in the IRSAP NOW app follows.
"""

import logging
import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import async_fetch_shadow, async_update_shadow
from .const import APP_CLIENT_ID, DOMAIN, WRITE_SETTLE_TIME
from .shadow import linked_device

_LOGGER = logging.getLogger(__name__)

# (unique_id suffix, name, icon, device key suffix)
SWITCH_TYPES = [
    ("child_lock_switch", "Child Lock", "mdi:lock", "_X_lock"),
    ("standby_switch", "Standby", "mdi:power-sleep", "_X_standby"),
    (
        "open_window_switch",
        "Open Window Detection",
        "mdi:window-open-variant",
        "_X_OpenWindowSensorEnabled",
    ),
]


def device_key(desired, zone, suffix):
    """Shadow key holding a device setting for a zone, or None.

    Follows the zone -> device link; without it, falls back to the only key
    with that suffix when the home has a single one.
    """
    device = linked_device(desired, zone)
    if device is not None and f"{device}{suffix}" in desired:
        return f"{device}{suffix}"
    keys = [key for key in desired if key.endswith(suffix)]
    return keys[0] if len(keys) == 1 else None


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    desired = coordinator.desired

    entities = []
    for key, name in desired.items():
        if not key.endswith("_NAM") or key.startswith("E_"):
            continue
        zone = key[: -len("_NAM")]
        for unique_suffix, label, icon, suffix in SWITCH_TYPES:
            # Only settings this radiator actually reports
            if device_key(desired, zone, suffix) is None:
                continue
            entities.append(
                RadiatorSettingSwitch(
                    coordinator, name, zone, unique_suffix, label, icon, suffix
                )
            )
    async_add_entities(entities)


class RadiatorSettingSwitch(CoordinatorEntity, SwitchEntity):
    """A 0/1 radiator setting stored in the shadow."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, serial, zone, unique_suffix, label, icon, suffix):
        super().__init__(coordinator)
        self._serial = serial
        self._zone = zone
        self._suffix = suffix
        self._attr_name = f"{serial} {label}"
        self._attr_unique_id = f"{serial}_{unique_suffix}"
        self._attr_icon = icon
        self._attr_is_on = self._read(coordinator.desired)
        # Dopo un comando lo shadow può essere ancora quello vecchio
        self._ignore_updates_until = 0.0

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._serial)}}

    def _read(self, desired):
        key = device_key(desired, self._zone, self._suffix)
        value = desired.get(key) if key else None
        return None if value is None else value == 1

    @callback
    def _handle_coordinator_update(self) -> None:
        if time.monotonic() < self._ignore_updates_until:
            return
        self._attr_is_on = self._read(self.coordinator.desired)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._async_write(1)

    async def async_turn_off(self, **kwargs):
        await self._async_write(0)

    async def _async_write(self, value):
        envID = self.coordinator.envID
        token, payload = await async_fetch_shadow(self.hass, envID)
        if payload is None:
            raise HomeAssistantError("IRSAP cloud not reachable")
        desired = payload["state"]["desired"]
        key = device_key(desired, self._zone, self._suffix)
        if key is None:
            raise HomeAssistantError(f"{self._attr_name}: setting not found")

        desired[key] = value
        desired.pop("sk", None)
        payload["timestamp"] = int(time.time() * 1000)
        payload["clientId"] = APP_CLIENT_ID
        ordered = {
            "id": payload.get("id"),
            "clientId": payload["clientId"],
            "timestamp": payload["timestamp"],
            "version": payload.get("version"),
            "state": payload["state"],
        }
        if not await async_update_shadow(self.hass, token, envID, ordered):
            raise HomeAssistantError(f"{self._attr_name}: the IRSAP cloud refused it")

        self._attr_is_on = value == 1
        self._ignore_updates_until = time.monotonic() + WRITE_SETTLE_TIME
        self.async_write_ha_state()
