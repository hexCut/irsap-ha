"""Helpers to navigate the IRSAP shadow."""


def linked_device(desired_payload, zone):
    """Prefix of the device serving a zone, or None.

    Zone values (name, temperature, setpoint, `_ENB`, `_AIQ`) live under the
    zone's prefix, device values (MAC, firmware, Wi-Fi, IP, hysteresis…) under
    the device's. The shadow links them through a group whose ``_PLD`` is the
    zone and ``_MID`` the device, e.g. ``GkV_PLD = "PcC"``, ``GkV_MID = "DRk"``.
    """
    for key, value in desired_payload.items():
        if key.endswith("_PLD") and value == zone:
            device = desired_payload.get(f"{key[: -len('_PLD')]}_MID")
            if isinstance(device, str) and device:
                return device
    return None


def device_values(desired_payload, zone, fields):
    """Read device fields for a zone through its linked device.

    ``fields`` maps the name used by the integration to the key suffix, e.g.
    ``{"firmware": "_FWV"}``. Returns only the fields present under the linked
    device; an empty dict when the zone has no linked device, so callers keep
    their previous values.
    """
    device = linked_device(desired_payload, zone)
    if device is None:
        return {}
    return {
        name: desired_payload[f"{device}{suffix}"]
        for name, suffix in fields.items()
        if f"{device}{suffix}" in desired_payload
    }
