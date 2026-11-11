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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import async_write_device_setting, serialize_writes
from .const import DOMAIN, WRITE_SETTLE_TIME
from .hvac_action import written_by_device
from .ids import device_identifier, unique_id
from .shadow import device_key

_LOGGER = logging.getLogger(__name__)

# (unique_id suffix, translation key, icon, device key suffix)
SWITCH_TYPES = [
    ("child_lock_switch", "child_lock", "mdi:lock", "_X_lock"),
    ("standby_switch", "standby", "mdi:power-sleep", "_X_standby"),
    (
        "open_window_switch",
        "open_window_detection",
        "mdi:window-open-variant",
        "_X_OpenWindowSensorEnabled",
    ),
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    desired = coordinator.desired

    entities = []
    for key, name in desired.items():
        if not key.endswith("_NAM") or key.startswith("E_"):
            continue
        zone = key[: -len("_NAM")]
        for unique_suffix, translation_key, icon, suffix in SWITCH_TYPES:
            # Only settings this radiator actually reports
            if device_key(desired, zone, suffix) is None:
                continue
            entities.append(
                RadiatorSettingSwitch(
                    coordinator,
                    name,
                    zone,
                    unique_suffix,
                    translation_key,
                    icon,
                    suffix,
                )
            )
    async_add_entities(entities)


class RadiatorSettingSwitch(CoordinatorEntity, SwitchEntity):
    """A 0/1 radiator setting stored in the shadow."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self, coordinator, serial, zone, unique_suffix, translation_key, icon, suffix
    ):
        super().__init__(coordinator)
        self._serial = serial
        self._zone = zone
        self._suffix = suffix
        self._attr_translation_key = translation_key
        self._log_name = f"{serial} {translation_key}"
        self._attr_unique_id = unique_id(coordinator.envID, zone, unique_suffix)
        self._attr_icon = icon
        self._attr_is_on = self._read(coordinator.desired)
        # Dopo un comando lo shadow può essere ancora quello vecchio
        self._ignore_updates_until = 0.0

    @property
    def device_info(self):
        return {"identifiers": {device_identifier(self.coordinator.envID, self._zone)}}

    def _read(self, desired):
        key = device_key(desired, self._zone, self._suffix)
        value = desired.get(key) if key else None
        return None if value is None else value == 1

    @callback
    def _handle_coordinator_update(self) -> None:
        if time.monotonic() < self._ignore_updates_until:
            return
        desired = self.coordinator.desired
        self._attr_is_on = self._read(desired)
        key = device_key(desired, self._zone, self._suffix)
        _LOGGER.debug(
            f"{self._log_name}: {key}={desired.get(key) if key else None} "
            f"written_by="
            f"{'device' if written_by_device(self.coordinator.data) else 'app'}"
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._async_write(1)

    async def async_turn_off(self, **kwargs):
        await self._async_write(0)

    @serialize_writes
    async def _async_write(self, value):
        await async_write_device_setting(
            self.hass,
            self.coordinator.envID,
            self._zone,
            self._suffix,
            value,
            self._log_name,
        )
        self._attr_is_on = value == 1
        self._ignore_updates_until = time.monotonic() + WRITE_SETTLE_TIME
        self.async_write_ha_state()
