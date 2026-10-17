"""Operating modes of an IRSAP zone, as stored in the shadow.

Observed on a real radiator (fw 3.22):

- ``<zone>_ENB``: 1 on, 0 off (antifreeze, ``CSP`` = 5 °C).
- ``<zone>_MOD``: 1 manual, 2 schedule (only meaningful with a schedule in
  ``E_SCH``).
- ``<zone>_MSP``: the manual setpoint; kept, but not applied, in schedule mode.
- ``<zone>_TSP``: the temporary setpoint. In schedule mode, +/- on the radiator
  sets it until the next schedule change (``e``); ``e`` in 1970 means "none".
- ``<zone>_CSP``: the setpoint the radiator is applying, whatever the mode.

All values are in tenths of a degree.
"""

from datetime import datetime, timedelta, timezone

MODE_MANUAL = 1
MODE_SCHEDULE = 2

PRESET_MANUAL = "manual"
PRESET_SCHEDULE = "schedule"

NO_EXPIRY = "1970-01-01T00:00:00.000Z"
# A temporary setpoint without a schedule change to end at lasts this long
TEMPORARY_FALLBACK = timedelta(hours=24)
# CSP expiries further away than this mean "no expiry" (the radiator uses 2106)
MAX_SCHEDULE_STEP = timedelta(days=8)


def _value(desired, key):
    entry = desired.get(key)
    if isinstance(entry, dict):
        value = (entry.get("p") or {}).get("v")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_time(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def has_schedule(desired):
    """True if the home has at least one schedule."""
    return bool(desired.get("E_SCH"))


def zone_mode(desired, zone):
    return desired.get(f"{zone}_MOD")


def preset_for(desired, zone):
    """Preset to show for the zone: schedule or manual."""
    if zone_mode(desired, zone) == MODE_SCHEDULE and has_schedule(desired):
        return PRESET_SCHEDULE
    return PRESET_MANUAL


def preset_modes(desired):
    """Presets the zone can switch to."""
    if has_schedule(desired):
        return [PRESET_MANUAL, PRESET_SCHEDULE]
    return [PRESET_MANUAL]


def temporary_until(desired, zone, now):
    """End of the temporary setpoint, if one is active in schedule mode."""
    if preset_for(desired, zone) != PRESET_SCHEDULE:
        return None
    tsp = desired.get(f"{zone}_TSP")
    if not isinstance(tsp, dict):
        return None
    end = _parse_time(tsp.get("e"))
    if end is None or end <= now:
        return None
    return end


def applied_setpoint(desired, zone):
    """Target temperature in °C: what the radiator applies when it is on,
    the manual setpoint when it is off (CSP is then the 5 °C antifreeze)."""
    if desired.get(f"{zone}_ENB") == 1:
        csp = _value(desired, f"{zone}_CSP")
        if csp is not None:
            return csp / 10
    msp = _value(desired, f"{zone}_MSP")
    return msp / 10 if msp is not None else None


def _next_schedule_change(desired, zone, now):
    csp = desired.get(f"{zone}_CSP")
    end = _parse_time(csp.get("e")) if isinstance(csp, dict) else None
    if end is not None and now < end <= now + MAX_SCHEDULE_STEP:
        return end
    return now + TEMPORARY_FALLBACK


def _set_value(desired, key, tenths):
    entry = desired.get(key)
    if isinstance(entry, dict) and isinstance(entry.get("p"), dict):
        entry["p"]["v"] = tenths


def _cancel_temporary(desired, zone, tenths):
    if f"{zone}_TSP" in desired:
        desired[f"{zone}_TSP"] = {
            "p": {"u": 0, "v": tenths, "m": 3, "k": "TEMPORARY"},
            "e": NO_EXPIRY,
        }


def apply_setpoint(desired, zone, temperature, now):
    """Change the target like the radiator's own +/- buttons do.

    In schedule mode the new value is a temporary setpoint until the next
    schedule change (the manual setpoint is left alone); otherwise it becomes
    the manual setpoint. The heat call (E_CLL/E_CPC) is raised only when the
    radiator is on: with the radiator off nothing would ever clear it.
    """
    tenths = int(round(temperature * 10))
    if preset_for(desired, zone) == PRESET_SCHEDULE:
        desired[f"{zone}_TSP"] = {
            "p": {"u": 0, "v": tenths, "m": 3, "k": "TEMPORARY"},
            "e": _format_time(_next_schedule_change(desired, zone, now)),
        }
    else:
        _set_value(desired, f"{zone}_MSP", tenths)
        _cancel_temporary(desired, zone, tenths)
        desired[f"{zone}_MOD"] = MODE_MANUAL
    _set_value(desired, f"{zone}_CSP", tenths)

    if desired.get(f"{zone}_ENB") == 1:
        for key in ("E_CLL", "E_CPC"):
            if key in desired:
                desired[key] = 1


def apply_preset(desired, zone, preset):
    """Switch the zone to manual or schedule mode, cancelling any temporary
    setpoint. Manual keeps the temperature currently applied."""
    if preset == PRESET_MANUAL:
        target = applied_setpoint(desired, zone)
        if target is not None:
            _set_value(desired, f"{zone}_MSP", int(round(target * 10)))
        msp = _value(desired, f"{zone}_MSP")
        _cancel_temporary(desired, zone, msp if msp is not None else 0)
        desired[f"{zone}_MOD"] = MODE_MANUAL
    elif preset == PRESET_SCHEDULE:
        if not has_schedule(desired):
            raise ValueError("no schedule configured in the IRSAP NOW app")
        msp = _value(desired, f"{zone}_MSP")
        _cancel_temporary(desired, zone, msp if msp is not None else 0)
        desired[f"{zone}_MOD"] = MODE_SCHEDULE
    else:
        raise ValueError(f"unknown preset {preset}")
