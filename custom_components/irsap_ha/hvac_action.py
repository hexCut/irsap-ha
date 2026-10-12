"""Derive the climate hvac_action from the IRSAP shadow."""

from homeassistant.components.climate import HVACAction


def compute_hvac_action(desired_payload, base_key):
    """Return what the radiator is actually doing (issue #20).

    The shadow has no per-radiator relay flag, but:
    - ``E_CLL`` is the environment's heat call: the radiator sets it to 1 while
      it heats and back to 0 once the setpoint is reached (it overwrites the
      value the app/integration writes). It is authoritative only when the
      environment contains a single radiator.
    - ``<zone>_CSP`` is the setpoint the radiator is currently applying and
      ``<zone>_TMP`` the measured temperature (both in tenths of a degree):
      with more radiators the action is inferred from those two.
    """
    if desired_payload.get(f"{base_key}_ENB") != 1:
        return HVACAction.OFF

    zones = sum(1 for key in desired_payload if key.endswith("_NAM"))
    e_cll = desired_payload.get("E_CLL")
    if zones == 1 and e_cll in (0, 1):
        return HVACAction.HEATING if e_cll == 1 else HVACAction.IDLE

    current = desired_payload.get(f"{base_key}_TMP")
    setpoint = None
    for sp_key in (f"{base_key}_CSP", f"{base_key}_MSP"):
        try:
            setpoint = desired_payload[sp_key]["p"]["v"]
            break
        except (KeyError, TypeError):
            continue

    if not isinstance(current, (int, float)) or not isinstance(setpoint, (int, float)):
        return None  # unknown: HA then shows only the HVAC mode
    return HVACAction.HEATING if current < setpoint else HVACAction.IDLE
