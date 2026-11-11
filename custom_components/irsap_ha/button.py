"""Identify button: makes the radiator's LED blink.

Verified on a real radiator (RE, fw 3.22), issue #62: writing
``<device>_X_identify = 1`` makes the LED blink (1 s on, 1 s off); the
radiator stops by itself after about 5 minutes and sets the value back to 0,
so the button only writes 1.
"""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import async_write_device_setting, serialize_writes
from .const import DOMAIN
from .ids import device_identifier, unique_id
from .shadow import device_key

IDENTIFY_SUFFIX = "_X_identify"


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    desired = coordinator.desired
    async_add_entities(
        IdentifyButton(coordinator, name, key[: -len("_NAM")])
        for key, name in desired.items()
        if key.endswith("_NAM")
        and not key.startswith("E_")
        # Only radiators that report the key
        and device_key(desired, key[: -len("_NAM")], IDENTIFY_SUFFIX) is not None
    )


class IdentifyButton(CoordinatorEntity, ButtonEntity):
    """Make the radiator's LED blink for about 5 minutes."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, coordinator, serial, zone):
        super().__init__(coordinator)
        self._zone = zone
        self._log_name = f"{serial} identify"
        self._attr_unique_id = unique_id(coordinator.envID, zone, "identify")

    @property
    def device_info(self):
        return {"identifiers": {device_identifier(self.coordinator.envID, self._zone)}}

    @serialize_writes
    async def async_press(self) -> None:
        await async_write_device_setting(
            self.hass,
            self.coordinator.envID,
            self._zone,
            IDENTIFY_SUFFIX,
            1,
            self._log_name,
        )
