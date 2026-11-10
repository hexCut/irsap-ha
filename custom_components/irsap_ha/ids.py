"""Stable identifiers for devices and entities (issue #52).

Up to 1.6 devices and entities were keyed by the room name (``<zone>_NAM``),
so renaming a room in the IRSAP NOW app created new devices and entities.
They are now keyed by the zone id, the shadow prefix of the room (e.g.
``PTO``), which survives a rename, together with the home's ``envID``: zone ids
are short codes, unique within a home but not across homes, and one
integration can be set up for several homes.
"""

from .const import DOMAIN


def zone_key(env_id, zone):
    """Key of a radiator (zone) across all homes: ``<envID>_<zone>``."""
    return f"{env_id}_{zone}"


def device_identifier(env_id, zone):
    """Device registry identifier of a radiator."""
    return (DOMAIN, zone_key(env_id, zone))


def unique_id(env_id, zone, suffix):
    """Unique ID of one of a radiator's entities: ``<envID>_<zone>_<suffix>``."""
    return f"{zone_key(env_id, zone)}_{suffix}"


def zone_names(desired):
    """``{zone: room name}`` for every radiator in the shadow."""
    return {
        key[: -len("_NAM")]: name
        for key, name in desired.items()
        if key.endswith("_NAM") and not key.startswith("E_") and isinstance(name, str)
    }
