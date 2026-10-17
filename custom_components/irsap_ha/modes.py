"""Operating modes of an IRSAP zone, as stored in the shadow.

Observed on a real radiator (fw 3.22):

- ``<zone>_ENB``: 1 on, 0 off (antifreeze, ``CSP`` = 5 °C).
- ``<zone>_MOD``: 1 manual, 2 schedule.
- ``E_SCH``: the home's schedules, each with an id ``k``; ``<zone>_WSC`` is the
  id of the schedule assigned to the zone (the app's "Assign room"). Removing
  the schedule removes ``_WSC`` and the radiator goes back to manual.
- ``<zone>_MSP``: the manual setpoint; kept, but not applied, in schedule mode.
- ``<zone>_TSP``: the temporary setpoint. In schedule mode, +/- on the radiator
  sets it until the next schedule change (``e``); ``e`` in 1970 means "none".
- ``<zone>_CSP``: the setpoint the radiator is applying, whatever the mode.
- ``E_CLL`` / ``E_CPC``: the heat call, managed by the radiator itself (1 while
  it heats, 0 once the setpoint is reached). Written from outside it stays as
  written until the relay switches, so it is never written here.

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


def zone_schedule(desired, zone):
    """Id of the schedule assigned to the zone, if it exists in ``E_SCH``."""
    schedule_id = desired.get(f"{zone}_WSC")
    if not schedule_id:
        return None
    for schedule in desired.get("E_SCH") or []:
        if isinstance(schedule, dict) and schedule.get("k") == schedule_id:
            return schedule_id
    return None


def zone_mode(desired, zone):
    return desired.get(f"{zone}_MOD")


def preset_for(desired, zone):
    """Preset to show for the zone: schedule or manual."""
    if zone_mode(desired, zone) == MODE_SCHEDULE and zone_schedule(desired, zone):
        return PRESET_SCHEDULE
    return PRESET_MANUAL


def preset_modes(desired, zone):
    """Presets the zone can switch to: schedule only with a schedule assigned."""
    if zone_schedule(desired, zone):
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
    the manual setpoint. ``CSP`` is updated only while the radiator is on (off,
    it holds the antifreeze value); the heat call is left to the radiator.
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
    if desired.get(f"{zone}_ENB") == 1:
        _set_value(desired, f"{zone}_CSP", tenths)


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
        if not zone_schedule(desired, zone):
            raise ValueError("no schedule assigned to this room in the IRSAP NOW app")
        msp = _value(desired, f"{zone}_MSP")
        _cancel_temporary(desired, zone, msp if msp is not None else 0)
        desired[f"{zone}_MOD"] = MODE_SCHEDULE
    else:
        raise ValueError(f"unknown preset {preset}")
