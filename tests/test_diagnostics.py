"""Diagnostics: useful data in, personal data out."""

import json

from homeassistant.components.diagnostics import REDACTED
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.irsap_ha.diagnostics import redact_shadow

# Personal data and identifiers as they appear in a real shadow
SECRETS = {
    "street": "Via Example 1",
    "lat_lon": "45.00000,9.00000",
    "mac": "20:0a:0d:aa:bb:cc",
    "ip": "192.168.0.79",
    "presence": "03359e32-30c9-4070-a2c6-e0f3e6367250",
    "env": "b5c5c591-92b2-4516-8651-5dce0464bdc9",
}


def _real_shape(shadow):
    shadow["id"] = SECRETS["env"]
    shadow["clientId"] = f"dev-RE_{SECRETS['mac']}#RE"
    shadow["state"]["desired"].update(
        {
            "DRk_SRL": SECRETS["mac"],
            "DRk_CNT": f"RE_{SECRETS['mac']}",
            "DRk_X_ipAddress": SECRETS["ip"],
            "DRk_X_hysteresis": 2,
            "E_ID": SECRETS["env"],
            "E_PRS": [SECRETS["presence"]],
            "E_LOC": {
                "address": {"street": SECRETS["street"], "city": "Somewhere"},
                "latLon": SECRETS["lat_lon"],
            },
        }
    )


async def test_diagnostics_redacts_personal_data(
    hass, hass_client, config_entry, mock_login, mock_get_shadow, shadow
):
    _real_shape(shadow)
    assert await async_setup_component(hass, "diagnostics", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    dump = json.dumps(diag)

    # credentials and token never appear
    for value in ("user@example.com", "secret", "setup-token", "token-1", "env-1"):
        assert value not in dump, value
    for value in SECRETS.values():
        assert value not in dump, value

    # what is useful for debugging is still there
    desired = diag["shadow"]["state"]["desired"]
    assert desired["PTO_NAM"] == "Bagno"
    assert desired["PTO_TMP"] == 215
    assert desired["DRk_X_hysteresis"] == 2
    assert desired["DRk_SRL"] == REDACTED
    assert desired["E_LOC"] == REDACTED
    assert diag["coordinator"]["last_update_success"] is True
    assert diag["coordinator"]["update_interval_seconds"] == 60
    assert diag["token_cached"] is True
    assert diag["entry"]["data"]["password"] == REDACTED


def test_redact_shadow_handles_nested_and_missing():
    assert redact_shadow(None) is None
    assert redact_shadow({"a": [{"X_SRL": "m", "v": 1}]}) == {
        "a": [{"X_SRL": REDACTED, "v": 1}]
    }
