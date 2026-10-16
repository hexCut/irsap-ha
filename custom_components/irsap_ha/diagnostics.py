"""Diagnostics for the IRSAP integration ("Download diagnostics" in the UI)."""

from homeassistant.components.diagnostics import REDACTED

from .const import DOMAIN

# Keys removed from the config entry
ENTRY_TO_REDACT = {"username", "password", "token", "envID"}

# Keys removed from the cloud shadow, wherever they appear:
# - the home's address and coordinates, the users present, the environment and
#   shadow ids, and the client id (it contains the radiator's MAC address)
SHADOW_KEYS_TO_REDACT = {"E_LOC", "E_PRS", "E_ID", "id", "clientId"}
# - per-device identifiers: MAC address, connection id, local IP address
SHADOW_SUFFIXES_TO_REDACT = ("_SRL", "_CNT", "_X_ipAddress")


def redact_shadow(data):
    """Return a copy of the shadow with personal data and identifiers redacted."""
    if isinstance(data, dict):
        return {
            key: (
                REDACTED
                if key in SHADOW_KEYS_TO_REDACT
                or (isinstance(key, str) and key.endswith(SHADOW_SUFFIXES_TO_REDACT))
                else redact_shadow(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_shadow(item) for item in data]
    return data


def _redact_entry(mapping):
    return {
        key: REDACTED if key in ENTRY_TO_REDACT else value
        for key, value in mapping.items()
    }


async def async_get_config_entry_diagnostics(hass, config_entry):
    """Return diagnostics for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})
    coordinator = entry_data.get("coordinator")

    diagnostics = {
        "entry": {
            "data": _redact_entry(config_entry.data),
            "options": _redact_entry(config_entry.options),
            "pref_disable_polling": config_entry.pref_disable_polling,
        },
        "token_cached": bool(hass.data.get(DOMAIN, {}).get("token")),
    }

    if coordinator is not None:
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
        }
        diagnostics["shadow"] = redact_shadow(coordinator.data)

    return diagnostics
