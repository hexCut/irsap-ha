"""Zone -> valve/ambient sensor mapping, on a synthetic Smart Valve shadow."""

import pytest

from custom_components.irsap_ha.topology import (
    gateway_id,
    linked_devices,
    zone_devices,
    zone_prefixes,
)

# A synthetic (not literally captured) two-zone Smart Valve shadow, built to
# exercise every case found on a real multi-zone install: a zone with a valve
# plus an ambient sensor (the sensor linked twice, a dedup case), a stale link
# to a device with no keys at all (an old pairing), and a second zone with
# just a single valve to prove zones don't cross-contaminate.
SHADOW = {
    "E_NAM": "Casa",
    # Camera: valve Dv1 + ambient sensor Ds1 (linked twice), one stale link
    "Cam_NAM": "Camera",
    "Gc_PLD": "Cam",
    "Gc_MID": "Dpc",
    "Wv1_GID": "Gc",
    "Wv1_DID": "Dv1",
    "Ws1_GID": "Gc",
    "Ws1_DID": "Ds1",
    "Ws1b_GID": "Gc",
    "Ws1b_DID": "Ds1",  # duplicate link to the same ambient sensor
    "Worph_GID": "Gc",
    "Worph_DID": "Dorphan",  # stale link: Dorphan has no keys at all
    # Bagno: a single valve Dv2, to prove zone isolation
    "Bag_NAM": "Bagno",
    "Gb_PLD": "Bag",
    "Gb_MID": "Dpc",
    "Wv2_GID": "Gb",
    "Wv2_DID": "Dv2",
    # Gateway ("Unità di Connessione")
    "Dpc_TYP": "SYS",
    "Dpc_FWV": "1.24",
    # Valve Dv1 (Camera)
    "Dv1_TYP": "MEH",
    "Dv1_FWV": "1.25",
    "Dv1_X_BatteryVoltage": 30,
    "Dv1_X_DBLevel": -75,
    "Dv1_X_EnvTemp": 208,
    "Dv1_X_CalcTemp": 207,
    "Dv1_X_WaterTemp": 210,
    "Dv1_X_ValveOpen": 0,
    "Dv1_X_OpenWind": 1,
    "Dv1_X_BlockMode": 1,
    "Dv1_X_OffsTemp": -5,
    "Dv1_X_AntiWhistle": 5,
    "Dv1_LUP": "2026-11-06T09:40:46.275Z",
    "Dv1_ERR": [],
    # Ambient sensor Ds1 (Camera)
    "Ds1_TYP": "SU",
    "Ds1_FWV": "1.15",
    "Ds1_X_BatteryVoltage": 27,
    "Ds1_X_DBLevel": -64,
    "Ds1_X_EnvTemp": 207,
    "Ds1_X_EnvHumidity": 58,
    "Ds1_X_CO2Value": 400,
    "Ds1_X_VocValue": 0,
    "Ds1_X_VocLevel": 1,
    "Ds1_X_AqiUba": 0,
    "Ds1_LUP": "2026-11-06T09:40:46.275Z",
    "Ds1_ERR": [],
    # Valve Dv2 (Bagno) - distinct values, to catch any cross-zone mixup
    "Dv2_TYP": "MEH",
    "Dv2_FWV": "1.25",
    "Dv2_X_BatteryVoltage": 28,
    "Dv2_X_DBLevel": -66,
    "Dv2_X_EnvTemp": 194,
    "Dv2_X_CalcTemp": 194,
    "Dv2_X_WaterTemp": 191,
    "Dv2_X_ValveOpen": 0,
    "Dv2_X_OpenWind": 1,
    "Dv2_LUP": "2026-11-06T09:50:46.275Z",
}

ZONES = {
    "Cam": ("Camera", ["Dv1", "Ds1"]),
    "Bag": ("Bagno", ["Dv2"]),
}
ORPHAN_DEVICE_IDS = ["Dorphan"]


def test_zone_prefixes_excludes_the_home():
    prefixes = zone_prefixes(SHADOW)
    assert set(prefixes) == set(ZONES)
    for prefix in prefixes:
        assert SHADOW[f"{prefix}_NAM"] == ZONES[prefix][0]


@pytest.mark.parametrize("zone, expected", ZONES.items(), ids=lambda v: v if isinstance(v, str) else "")
def test_each_zone_has_its_real_devices_only(zone, expected):
    _name, device_ids = expected
    devices = linked_devices(SHADOW, zone)
    got_ids = [d["device_id"] for d in devices]
    assert set(got_ids) == set(device_ids)
    assert len(got_ids) == len(device_ids)  # deduplicated, no repeats
    for orphan in ORPHAN_DEVICE_IDS:
        assert orphan not in got_ids


def test_camera_has_a_valve_and_a_deduplicated_ambient_sensor():
    devices = {d["device_id"]: d for d in linked_devices(SHADOW, "Cam")}
    assert set(devices) == {"Dv1", "Ds1"}

    valve = devices["Dv1"]
    assert valve["kind"] == "valve"
    assert valve["battery_voltage"] == pytest.approx(3.0)
    assert valve["rssi"] == -75
    assert valve["setpoint_temperature"] == pytest.approx(20.7)
    assert valve["water_temperature"] == pytest.approx(21.0)
    assert valve["open_window_enabled"] == 1
    assert valve["child_lock"] == 1
    assert valve["temperature_offset"] == pytest.approx(-0.5)
    assert valve["anti_whistle"] == 5
    assert valve["last_update"] == SHADOW["Dv1_LUP"]

    sensor = devices["Ds1"]
    assert sensor["kind"] == "ambient_sensor"
    assert sensor["humidity"] == 58
    assert sensor["co2"] == 400
    assert sensor["voc_level"] == 1
    assert sensor["aqi_uba"] == 0
    assert sensor["battery_voltage"] == pytest.approx(2.7)
    assert sensor["last_update"] == SHADOW["Ds1_LUP"]


def test_single_valve_zone_has_real_values():
    valve = linked_devices(SHADOW, "Bag")[0]
    assert valve["device_id"] == "Dv2"
    assert valve["kind"] == "valve"
    assert valve["battery_voltage"] == pytest.approx(2.8)
    assert valve["measured_temperature"] == pytest.approx(19.4)


def test_no_orphan_device_anywhere():
    all_ids = {d["device_id"] for devices in zone_devices(SHADOW).values() for d in devices}
    assert all_ids.isdisjoint(ORPHAN_DEVICE_IDS)


def test_gateway_id_finds_the_connection_unit():
    assert gateway_id(SHADOW) == "Dpc"
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
