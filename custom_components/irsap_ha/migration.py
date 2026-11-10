"""Config entry migrations.

Version 1 -> 2 (issue #52): devices and entities keyed by the room name
(``(DOMAIN, "Bagno")``, ``Bagno_climate``) are re-keyed by home and zone id
(``(DOMAIN, "<envID>_PTO")``, ``<envID>_PTO_climate``, see ``ids.py``). Only
identifiers and unique IDs change: the registry entries are updated in place,
so entity_ids, names, areas, icons and disabled states are kept.

The room names are mapped to zone ids with the current shadow. A room renamed
in the app before updating no longer matches its old devices and entities:
they are left as they are, and the logs say which ones to remove by hand.
"""

import logging

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .ids import device_identifier, unique_id, zone_names

_LOGGER = logging.getLogger(__name__)


def _zones_by_name(desired):
    """``{room name: zone}``; names shared by several zones are left out,
    since their devices and entities can't be told apart."""
    by_name = {}
    for zone, name in zone_names(desired).items():
        by_name.setdefault(name, []).append(zone)
    ambiguous = sorted(name for name, zones in by_name.items() if len(zones) > 1)
    if ambiguous:
        _LOGGER.warning(
            "Several radiators are named %s: their devices and entities are not "
            "migrated, remove the old ones by hand",
            ", ".join(ambiguous),
        )
    return {name: zones[0] for name, zones in by_name.items() if len(zones) == 1}


async def async_migrate_v1_to_v2(hass, config_entry, desired):
    """Re-key the entry's devices and entities from room name to zone id."""
    env_id = config_entry.data["envID"]
    zones = _zones_by_name(desired)

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
    in_use = {i for device in devices for i in device.identifiers}
    unmatched_devices = []
    for device in devices:
        identifiers = set()
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier in zones:
                identifiers.add(device_identifier(env_id, zones[identifier]))
            else:
                identifiers.add((domain, identifier))
        if identifiers == device.identifiers:
            if any(domain == DOMAIN for domain, _ in device.identifiers):
                unmatched_devices.append(device.name)
            continue
        new_ids = identifiers - device.identifiers
        if new_ids & in_use:
            _LOGGER.warning(
                "Device %s not migrated: a device with its new identifier exists",
                device.name,
            )
            continue
        device_registry.async_update_device(device.id, new_identifiers=identifiers)
        in_use |= new_ids

    entity_registry = er.async_get(hass)
    # Longest names first: "Bagno camera_..." must not be read as "Bagno" + "camera_..."
    names = sorted(zones, key=len, reverse=True)
    unmatched_entities = []

    @callback
    def _migrate_entity(entry):
        for name in names:
            prefix = f"{name}_"
            if entry.unique_id.startswith(prefix):
                new_unique_id = unique_id(
                    env_id, zones[name], entry.unique_id[len(prefix) :]
                )
                if entity_registry.async_get_entity_id(
                    entry.domain, DOMAIN, new_unique_id
                ):
                    _LOGGER.warning(
                        "%s not migrated: %s is already used",
                        entry.entity_id,
                        new_unique_id,
                    )
                    return None
                return {"new_unique_id": new_unique_id}
        unmatched_entities.append(entry.entity_id)
        return None

    await er.async_migrate_entries(hass, config_entry.entry_id, _migrate_entity)

    if unmatched_devices or unmatched_entities:
        _LOGGER.warning(
            "Not in the IRSAP cloud any more (room renamed or removed before this "
            "update?), left as they are, remove them by hand if unused: "
            "devices %s, entities %s",
            unmatched_devices,
            unmatched_entities,
        )
