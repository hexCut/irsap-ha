"""Zone -> valve/ambient sensor mapping, on a real captured Smart Valve shadow.

The shadow comes from ``tests/fixtures/diagnostics.json``, a diagnostics
download from a real multi-zone Smart Valve install (credentials and room
UUIDs redacted/anonymized). Using the real shadow, rather than an invented
one, lets us check the zone -> group -> link -> device chain against an
install nobody made up.
"""

import json
from pathlib import Path

import pytest

from custom_components.irsap_ha.topology import (
    device_app_name,
    gateway_id,
    linked_devices,
    zone_devices,
    zone_prefixes,
)

FIXTURE = Path(__file__).parent / "fixtures" / "diagnostics.json"


def _load_desired():
    with FIXTURE.open(encoding="utf-8") as f:
        diagnostics = json.load(f)
    return diagnostics["data"]["shadow"]["state"]["desired"]


DESIRED = _load_desired()

# Five zones, each served by one valve; Cameretta also has an ambient sensor
# ("Termostato"). Seven links point to devices with no keys at all (stale
# pairings from an old setup) and must be ignored.
ZONES = {
    "PLS": "Cameretta",
    "PlS": "Ingresso",
    "Puh": "Camera",
    "PyD": "Bagno",
    "P7+": "Soggiorno",
}
ORPHAN_DEVICE_IDS = ["DfY", "DQd", "DyX", "D66", "DQR", "Dc6", "DJR"]


def test_zone_prefixes_excludes_the_home():
    prefixes = zone_prefixes(DESIRED)
    assert set(prefixes) == set(ZONES)
    for prefix in prefixes:
        assert DESIRED[f"{prefix}_NAM"] == ZONES[prefix]


def test_no_orphan_device_anywhere():
    all_ids = {d["device_id"] for devices in zone_devices(DESIRED).values() for d in devices}
    assert all_ids.isdisjoint(ORPHAN_DEVICE_IDS)


def test_cameretta_has_a_valve_and_a_deduplicated_ambient_sensor():
    """D+g is linked to the Cameretta group twice: must still appear once."""
    devices = {d["device_id"]: d for d in linked_devices(DESIRED, "PLS")}
    assert set(devices) == {"Dc8", "D+g"}

    valve = devices["Dc8"]
    assert valve["kind"] == "valve"
    assert valve["battery_voltage"] == pytest.approx(3.1)
    assert valve["rssi"] == -71
    # The valve regulates on its own measured temperature, not the ambient
    # sensor's: the two differ slightly (19.3 vs 19.5 here).
    assert valve["measured_temperature"] == pytest.approx(19.3)
    assert valve["setpoint_temperature"] == pytest.approx(19.5)
    assert valve["water_temperature"] == pytest.approx(19.0)
    assert valve["anti_whistle"] == 5

    assert valve["app_name"] == "Valvola - 0d45"

    sensor = devices["D+g"]
    assert sensor["kind"] == "ambient_sensor"
    assert sensor["measured_temperature"] == pytest.approx(19.5)
    assert sensor["humidity"] == 68
    assert sensor["co2"] == 400
    assert sensor["voc"] == 0
    assert sensor["voc_level"] == 1
    assert sensor["battery_voltage"] == pytest.approx(2.7)
    assert sensor["app_name"] == "Termostato - 0145"


def test_single_valve_zones_have_distinct_real_values():
    cases = {
        "PlS": ("Dm-", 3.1, -64),
        "Puh": ("D7E", 2.8, -67),
        "PyD": ("D6w", 3.2, -71),
        "P7+": ("DlZ", 3.1, -52),
    }
    for zone, (device_id, battery_voltage, rssi) in cases.items():
        devices = linked_devices(DESIRED, zone)
        assert len(devices) == 1
        valve = devices[0]
        assert valve["device_id"] == device_id
        assert valve["kind"] == "valve"
        assert valve["battery_voltage"] == pytest.approx(battery_voltage)
        assert valve["rssi"] == rssi


def test_camera_has_the_lowest_battery():
    camera_battery = linked_devices(DESIRED, "Puh")[0]["battery_voltage"]
    other_batteries = [
        linked_devices(DESIRED, zone)[0]["battery_voltage"]
        for zone in ("PlS", "PyD", "P7+")
    ]
    assert all(camera_battery < other for other in other_batteries)


def test_device_app_name_prefers_the_app_names_field():
    """E_X_DevNames is keyed by the device id without its leading "D"
    (e.g. "Dm-" -> "m-"). The Ingresso valve was renamed by the user to
    match its zone; the others keep the app's own generic label."""
    assert device_app_name(DESIRED, "Dm-") == "Ingresso"  # trailing space stripped
    assert device_app_name(DESIRED, "D7E") == "Valvola - 73c6"
    assert device_app_name(DESIRED, "Dpc") == "Unità di connessione - f:63"


def test_device_app_name_is_none_when_not_found():
    assert device_app_name(DESIRED, "Dxx") is None
    assert device_app_name({}, "Dm-") is None


def test_gateway_id_finds_the_connection_unit():
    assert gateway_id(DESIRED) == "Dpc"
    assert gateway_id({"PTO_NAM": "Bagno"}) is None


def test_zone_without_links_has_no_devices():
    """A plain Wi-Fi radiator shadow has no W/multi-device links: no crash, no devices."""
    simple = {
        "E_NAM": "Casa",
        "PTO_NAM": "Bagno",
        "PTO_TMP": 215,
        "PTO_SRL": "AA:BB:CC",
    }
    assert zone_prefixes(simple) == ["PTO"]
    assert linked_devices(simple, "PTO") == []
    assert zone_devices(simple) == {"PTO": []}
