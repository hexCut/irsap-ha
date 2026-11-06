"""Map IRSAP Smart Valve devices (valves, ambient sensors) to their zones.

The simple Wi-Fi radiators are one device per zone, linked through a group's
``_MID`` (see ``shadow.linked_device``). Smart Valve installations add a layer:
a zone (``P...``) is served by a group (``G...``, ``_PLD`` pointing to the
zone) whose ``_MID`` always points to the single radio gateway, not to the
actual valve or sensor. The real devices are found through separate link
records (``W...``) whose ``_GID`` points to the group and ``_DID`` to the
device.

No ``homeassistant`` import here: safe to unit-test directly on a shadow
payload.
"""

VALVE_TYPE = "MEH"
AMBIENT_SENSOR_TYPE = "SU"
GATEWAY_TYPE = "SYS"

# Device fields read for a linked valve or ambient sensor (name used by
# callers -> key suffix). Both kinds share most fields; a valve has no
# humidity/CO2/VOC, an ambient sensor has no valve/water temperature.
_COMMON_FIELDS = {
    "measured_temperature": "_X_EnvTemp",
    "battery_voltage": "_X_BatteryVoltage",
    "rssi": "_X_DBLevel",
    "firmware": "_FWV",
    "errors": "_ERR",
    "last_update": "_LUP",
}
_VALVE_FIELDS = {
    **_COMMON_FIELDS,
    "setpoint_temperature": "_X_CalcTemp",
    "water_temperature": "_X_WaterTemp",
    "valve_open": "_X_ValveOpen",
    # Whether open-window detection is enabled, not whether a window is
    # currently detected open: no such per-valve state was found in the
    # fixtures collected so far (only this enable flag and, on the gateway,
    # the shared _X_OpenWindowTime/_X_OpenMinValve thresholds).
    "open_window_enabled": "_X_OpenWind",
    "child_lock": "_X_BlockMode",
    # Calibration offset applied to the measured temperature; probable
    # meaning from CLAUDE.md, not confirmed against real behaviour.
    "temperature_offset": "_X_OffsTemp",
    # Anti-whistle level, 0-100%; already in that scale, no /10 conversion.
    "anti_whistle": "_X_AntiWhistle",
}
_AMBIENT_SENSOR_FIELDS = {
    **_COMMON_FIELDS,
    "humidity": "_X_EnvHumidity",
    "co2": "_X_CO2Value",
    "voc": "_X_VocValue",
    "voc_level": "_X_VocLevel",
    # Air quality index (UBA scale?), meaning not confirmed.
    "aqi_uba": "_X_AqiUba",
}

# Fields reported in tenths of a unit (temperature in tenths of °C, battery
# voltage in tenths of a volt), to convert to the real value.
_TENTHS_FIELDS = (
    "measured_temperature",
    "setpoint_temperature",
    "water_temperature",
    "battery_voltage",
    "temperature_offset",
)


def zone_prefixes(desired):
    """Prefixes of every zone (``P..._NAM``); the home's own ``E_NAM`` is not a zone."""
    return [
        key[: -len("_NAM")]
        for key in desired
        if key.endswith("_NAM") and not key.startswith("E_")
    ]


def _groups_for_zone(desired, zone):
    """Prefixes of the groups serving a zone (``_PLD == zone``)."""
    return [
        key[: -len("_PLD")]
        for key, value in desired.items()
        if key.endswith("_PLD") and value == zone
    ]


def _device_values(desired, device_id, device_type):
    fields = _VALVE_FIELDS if device_type == VALVE_TYPE else _AMBIENT_SENSOR_FIELDS
    kind = "valve" if device_type == VALVE_TYPE else "ambient_sensor"
    values = {
        name: desired[f"{device_id}{suffix}"]
        for name, suffix in fields.items()
        if f"{device_id}{suffix}" in desired
    }
    for name in _TENTHS_FIELDS:
        if name in values:
            values[name] = values[name] / 10
    return {"device_id": device_id, "kind": kind, **values}


def linked_devices(desired, zone):
    """Valves and ambient sensors wired to a zone, deduplicated.

    Follows zone -> group (``_PLD == zone``) -> link (``_GID == group``) ->
    device (``_DID``). A link to a device with no keys in the shadow at all
    (a stale pairing from an old setup) has no ``_TYP`` and is skipped, as is
    any device that isn't a valve or ambient sensor (e.g. the gateway). The
    same device linked more than once to the zone is only returned once.
    """
    seen = set()
    devices = []
    for group in _groups_for_zone(desired, zone):
        for key, value in desired.items():
            if not key.endswith("_GID") or value != group:
                continue
            device_id = desired.get(f"{key[: -len('_GID')]}_DID")
            if not device_id or device_id in seen:
                continue
            device_type = desired.get(f"{device_id}_TYP")
            if device_type not in (VALVE_TYPE, AMBIENT_SENSOR_TYPE):
                continue
            seen.add(device_id)
            devices.append(_device_values(desired, device_id, device_type))
    return devices


def zone_devices(desired):
    """Valves and ambient sensors for every zone, as ``{zone: [devices...]}``."""
    return {zone: linked_devices(desired, zone) for zone in zone_prefixes(desired)}


def gateway_id(desired):
    """Prefix of the radio gateway device (``_TYP == "SYS"``, e.g. ``"Dpc"``), or None."""
    for key, value in desired.items():
        if key.endswith("_TYP") and value == GATEWAY_TYPE:
            return key[: -len("_TYP")]
    return None
