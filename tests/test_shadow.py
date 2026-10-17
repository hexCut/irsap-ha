"""Pairing zones with their devices in multi-radiator shadows."""

from custom_components.irsap_ha.climate import (
    extract_device_info as climate_devices,
)
from custom_components.irsap_ha.sensor import extract_device_info as sensor_devices
from custom_components.irsap_ha.shadow import device_values, linked_device

# Two radiators. The devices are listed in the opposite order of the zones, so
# pairing by position would swap their values.
TWO = {
    "E_NAM": "Casa",
    "AAA_NAM": "Bagno",
    "AAA_TMP": 230,
    "AAA_ENB": 1,
    "BBB_NAM": "Camera",
    "BBB_TMP": 190,
    "BBB_ENB": 0,
    "BBB_AIQ": 3,
    "AAA_AIQ": None,
    "D2_SRL": "mac-2",
    "D2_CNT": "RE_mac-2",
    "D2_FWV": "2.0",
    "D2_TYP": "RE",
    "D2_SLV": -70,
    "D2_X_ipAddress": "10.0.0.2",
    "D2_X_hysteresis": 3,
    "D2_X_co2Value": 650,
    "D1_SRL": "mac-1",
    "D1_CNT": "RE_mac-1",
    "D1_FWV": "1.0",
    "D1_TYP": "RE",
    "D1_SLV": -50,
    "D1_X_ipAddress": "10.0.0.1",
    "D1_X_hysteresis": 2,
    "D1_X_co2Value": 65535,
    "G1_PLD": "AAA",
    "G1_MID": "D1",
    "G2_PLD": "BBB",
    "G2_MID": "D2",
}


def _by_name(devices):
    return {d["serial"]: d for d in devices}


def test_linked_device():
    assert linked_device(TWO, "AAA") == "D1"
    assert linked_device(TWO, "BBB") == "D2"
    assert linked_device(TWO, "ZZZ") is None
    assert linked_device({"G_PLD": "AAA", "G_MID": None}, "AAA") is None


def test_device_values_only_present_fields():
    assert device_values(TWO, "AAA", {"ip": "_X_ipAddress", "x": "_MISSING"}) == {
        "ip": "10.0.0.1"
    }
    assert device_values(TWO, "ZZZ", {"ip": "_X_ipAddress"}) == {}


def test_climate_pairs_by_link():
    devices = _by_name(climate_devices(TWO))
    assert devices["Bagno"]["ip_address"] == "10.0.0.1"
    assert devices["Bagno"]["mac"] == "mac-1"
    assert devices["Bagno"]["firmware"] == "1.0"
    assert devices["Camera"]["ip_address"] == "10.0.0.2"
    assert devices["Camera"]["mac"] == "mac-2"


def test_sensors_pair_by_link():
    devices = _by_name(sensor_devices(TWO))
    bagno, camera = devices["Bagno"], devices["Camera"]
    assert (bagno["wifi_signal"], camera["wifi_signal"]) == (-50, -70)
    assert (bagno["hysteresis"], camera["hysteresis"]) == (2, 3)
    assert (bagno["co2"], camera["co2"]) == (65535, 650)
    assert (bagno["mac"], camera["mac"]) == ("RE_mac-1", "RE_mac-2")
    # air quality is a zone value
    assert (bagno["aiq"], camera["aiq"]) == (None, 3)


def test_without_links_pairing_is_unchanged():
    """Shadows without group links keep the previous positional pairing."""
    unlinked = {k: v for k, v in TWO.items() if not k.startswith("G")}
    devices = sensor_devices(unlinked)
    # by position: the first zone gets the first device keys (D2), as before
    assert devices[0]["serial"] == "Bagno"
    assert devices[0]["ip_address"] == "10.0.0.2"
    assert climate_devices(unlinked)[0]["ip_address"] == "10.0.0.2"
