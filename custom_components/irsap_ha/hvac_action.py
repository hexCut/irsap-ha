"""Derive the climate hvac_action from the IRSAP shadow."""

from homeassistant.components.climate import HVACAction

# When the action has to be inferred from the temperatures, mimic the radiator's
# own hysteresis (tenths of a degree): it keeps heating until the room is more
# than that above the setpoint and starts again once it is more than that below.
# Read from the shadow (`<device>_X_hysteresis`); this is the fallback, the
# value observed on fw 3.22.
INFERRED_HYSTERESIS = 2  # 0.2 °C


def count_zones(desired_payload):
    """Number of radiators (zones) in the environment."""
    return sum(
        1
        for key in desired_payload
        if key.endswith("_NAM") and not key.startswith("E_")
    )


def written_by_device(payload):
    """True if the radiator itself wrote the shadow last.

    The radiator writes with a ``dev-...`` clientId; the app and this
    integration write with an ``app-...`` one.
    """
    return str((payload or {}).get("clientId", "")).startswith("dev-")


def compute_hvac_action(desired_payload, base_key, from_device, previous=None):
    """Return what the radiator is actually doing (issue #20).

    The shadow has no per-radiator relay flag, but:
    - ``E_CLL`` is the environment's heat call: the radiator sets it to 1 while
      it heats and back to 0 once the setpoint is reached. The integration (and
      the app) also write ``E_CLL = 1`` on every setpoint change, so the value
      is used only when the radiator wrote the shadow last (``from_device``)
      and the environment has a single radiator.
    - Otherwise the action is inferred from ``<zone>_CSP`` (the setpoint the
      radiator is applying, ``_MSP`` as fallback) and ``<zone>_TMP``, both in
      tenths of a degree, with the radiator's hysteresis (see
      ``get_hysteresis``). ``previous`` is the
      action reported before.
    """
    if desired_payload.get(f"{base_key}_ENB") != 1:
        return HVACAction.OFF

    e_cll = desired_payload.get("E_CLL")
    if from_device and count_zones(desired_payload) == 1 and e_cll in (0, 1):
        return HVACAction.HEATING if e_cll == 1 else HVACAction.IDLE

    current = desired_payload.get(f"{base_key}_TMP")
    setpoint = get_setpoint(desired_payload, base_key)
    if not isinstance(current, (int, float)) or not isinstance(setpoint, (int, float)):
        return None  # unknown: HA then shows only the HVAC mode

    hysteresis = get_hysteresis(desired_payload, base_key)
    if previous == HVACAction.HEATING:
        if current <= setpoint + hysteresis:
            return HVACAction.HEATING
        return HVACAction.IDLE
    if current < setpoint - hysteresis:
        return HVACAction.HEATING
    return HVACAction.IDLE


def get_setpoint(desired_payload, base_key):
    """Setpoint the radiator is applying, in tenths of a degree, or None."""
    for sp_key in (f"{base_key}_CSP", f"{base_key}_MSP"):
        try:
            return desired_payload[sp_key]["p"]["v"]
        except (KeyError, TypeError):
            continue
    return None


def get_hysteresis(desired_payload, base_key):
    """Hysteresis of the radiator serving a zone, in tenths of a degree.

    The value lives under the device's key, not the zone's: the shadow links
    them through a group, whose ``_PLD`` is the zone and ``_MID`` the device
    (e.g. ``GkV_PLD = "PcC"``, ``GkV_MID = "DRk"`` -> ``DRk_X_hysteresis``).
    With a single ``_X_hysteresis`` in the shadow that one is used; without
    any, ``INFERRED_HYSTERESIS``.
    """
    for key, value in desired_payload.items():
        if key.endswith("_PLD") and value == base_key:
            device = desired_payload.get(f"{key[: -len('_PLD')]}_MID")
            hysteresis = desired_payload.get(f"{device}_X_hysteresis")
            if _is_valid_hysteresis(hysteresis):
                return hysteresis

    values = [
        value for key, value in desired_payload.items() if key.endswith("_X_hysteresis")
    ]
    if len(values) == 1 and _is_valid_hysteresis(values[0]):
        return values[0]
    return INFERRED_HYSTERESIS


def _is_valid_hysteresis(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
