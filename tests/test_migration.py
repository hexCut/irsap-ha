"""Config entry migration 1 -> 2: devices and entities re-keyed by zone id (#52)."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "irsap_ha"

# Second radiator, as on a real install: a room whose name starts with the
# other's ("Bagno camera" / "Bagno"), device linked through a group
BAGNO_CAMERA = {
    "PLX_NAM": "Bagno camera",
    "PLX_TMP": 205,
    "PLX_ENB": 0,
    "PLX_MSP": {"p": {"u": 0, "v": 200, "m": 3}},
    "PLX_CSP": {"p": {"u": 0, "v": 50, "m": 3}},
    "PLX_CLL": 0,
    "GtV_PLD": "PLX",
    "GtV_MID": "DnS",
    "DnS_SRL": "11:22:33:44:55:66",
    "DnS_CNT": "RE_11:22:33:44:55:66",
    "DnS_FWV": "3.22",
    "DnS_TYP": "RE",
    "DnS_LEC": 879,
    "DnS_X_LCA": 7914,
    "DnS_X_CPW": 400,
}

# Registry left by 1.6 (+ #53): (domain, old unique_id) -> (entity_id, device)
OLD_ENTITIES = {
    ("climate", "Bagno_climate"): ("climate.bagno_scaldasalviette", "Bagno"),
    ("light", "Bagno_led"): ("light.bagno_led", "Bagno"),
    ("sensor", "Bagno_hysteresis"): ("sensor.bagno_isteresi", "Bagno"),
    ("sensor", "Bagno_co2"): ("sensor.bagno_co2", "Bagno"),
    ("switch", "Bagno_child_lock_switch"): ("switch.bagno_blocco", "Bagno"),
    ("climate", "Bagno camera_climate"): ("climate.bagno_camera", "Bagno camera"),
    ("sensor", "Bagno camera_energy"): ("sensor.bagno_camera_energia", "Bagno camera"),
    ("sensor", "Bagno camera_power"): ("sensor.bagno_camera_potenza", "Bagno camera"),
    ("sensor", "Bagno camera_heating_time"): (
        "sensor.bagno_camera_tempo",
        "Bagno camera",
    ),
    # Room renamed in the app before updating: no zone has this name any more
    ("climate", "Lavanderia_climate"): ("climate.lavanderia", "Lavanderia"),
}

NEW_UNIQUE_IDS = {
    "climate.bagno_scaldasalviette": "env-1_PTO_climate",
    "light.bagno_led": "env-1_PTO_led",
    "sensor.bagno_isteresi": "env-1_PTO_hysteresis",
    "sensor.bagno_co2": "env-1_PTO_co2",
    "switch.bagno_blocco": "env-1_PTO_child_lock_switch",
    "climate.bagno_camera": "env-1_PLX_climate",
    "sensor.bagno_camera_energia": "env-1_PLX_energy",
    "sensor.bagno_camera_potenza": "env-1_PLX_power",
    "sensor.bagno_camera_tempo": "env-1_PLX_heating_time",
}


def _populate_v1_registry(hass, entry):
    """Devices and entities as 1.6 left them, with user customizations."""
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    area = ar.async_get(hass).async_create("Bagno")
    device_ids = {}
    for room in ("Bagno", "Bagno camera", "Lavanderia"):
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, room)},
            name=room,
            manufacturer="IRSAP",
        )
        device_ids[room] = device.id
    devices.async_update_device(
        device_ids["Bagno"], area_id=area.id, name_by_user="Scaldasalviette"
    )
    for (domain, unique_id), (entity_id, room) in OLD_ENTITIES.items():
        entities.async_get_or_create(
            domain,
            DOMAIN,
            unique_id,
            suggested_object_id=entity_id.split(".", 1)[1],
            config_entry=entry,
            device_id=device_ids[room],
        )
    # User customizations that must survive
    entities.async_update_entity(
        "sensor.bagno_isteresi", name="Isteresi bagno", area_id=area.id
    )
    entities.async_update_entity(
        "sensor.bagno_co2", disabled_by=er.RegistryEntryDisabler.USER
    )
    return device_ids, area.id


def _two_radiators(shadow):
    desired = shadow["state"]["desired"]
    desired["PTO_X_lock"] = 0
    desired.update(BAGNO_CAMERA)


async def test_migrates_devices_and_entities(
    hass, config_entry_v1, mock_login, mock_get_shadow, shadow
):
    _two_radiators(shadow)
    entry = config_entry_v1
    entry.add_to_hass(hass)
    device_ids, area_id = _populate_v1_registry(hass, entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2
    assert entry.state is ConfigEntryState.LOADED

    entities = er.async_get(hass)
    for entity_id, unique_id in NEW_UNIQUE_IDS.items():
        assert entities.async_get(entity_id).unique_id == unique_id, entity_id
    # Customizations kept
    assert entities.async_get("sensor.bagno_isteresi").name == "Isteresi bagno"
    assert (
        entities.async_get("sensor.bagno_co2").disabled_by
        is er.RegistryEntryDisabler.USER
    )
    assert entities.async_get("sensor.bagno_isteresi").area_id == area_id
    # The migrated entities are the ones in use: no duplicates with new ids
    assert hass.states.get("climate.bagno_scaldasalviette") is not None
    assert hass.states.get("climate.bagno_camera") is not None
    assert hass.states.get("climate.bagno") is None
    assert hass.states.get("climate.bagno_camera_2") is None

    devices = dr.async_get(hass)
    bagno = devices.async_get(device_ids["Bagno"])
    assert bagno.identifiers == {(DOMAIN, "env-1_PTO")}
    assert bagno.area_id == area_id
    assert bagno.name_by_user == "Scaldasalviette"
    camera = devices.async_get(device_ids["Bagno camera"])
    assert camera.identifiers == {(DOMAIN, "env-1_PLX")}
    assert (dr.CONNECTION_NETWORK_MAC, "11:22:33:44:55:66") in camera.connections
    # No new device for the two radiators
    assert len(dr.async_entries_for_config_entry(devices, entry.entry_id)) == 3

    # Renamed before updating: left as it was, for the user to remove
    lavanderia = devices.async_get(device_ids["Lavanderia"])
    assert lavanderia.identifiers == {(DOMAIN, "Lavanderia")}
    assert entities.async_get("climate.lavanderia").unique_id == "Lavanderia_climate"


async def test_cloud_down_keeps_version_1(
    hass, config_entry_v1, mock_login, mock_get_shadow
):
    """Without the shadow the rooms can't be mapped: nothing is changed and
    the migration is tried again at the next start."""
    entry = config_entry_v1
    entry.add_to_hass(hass)
    device_ids, _ = _populate_v1_registry(hass, entry)
    mock_get_shadow.side_effect = None
    mock_get_shadow.return_value = None

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.version == 1
    device = dr.async_get(hass).async_get(device_ids["Bagno"])
    assert device.identifiers == {(DOMAIN, "Bagno")}
    entity = er.async_get(hass).async_get("climate.bagno_scaldasalviette")
    assert entity.unique_id == "Bagno_climate"


async def test_same_name_twice_is_not_migrated(
    hass, config_entry_v1, mock_login, mock_get_shadow, shadow
):
    """Two rooms with the same name: their old entities can't be told apart."""
    _two_radiators(shadow)
    shadow["state"]["desired"]["PLX_NAM"] = "Bagno"
    entry = config_entry_v1
    entry.add_to_hass(hass)
    device_ids, _ = _populate_v1_registry(hass, entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2
    device = dr.async_get(hass).async_get(device_ids["Bagno"])
    assert device.identifiers == {(DOMAIN, "Bagno")}
    entity = er.async_get(hass).async_get("climate.bagno_scaldasalviette")
    assert entity.unique_id == "Bagno_climate"


async def test_rename_in_the_app_keeps_the_device(
    hass, config_entry, mock_login, mock_get_shadow, shadow
):
    """A room renamed in the app: the entry reloads, the device takes the new
    name and keeps its entities; nothing new is created."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    device = devices.async_get_device_by_identifier(
        (DOMAIN, "env-1_PTO"), config_entry.entry_id
    )
    before = {
        e.entity_id
        for e in er.async_entries_for_config_entry(entities, config_entry.entry_id)
    }

    shadow["state"]["desired"]["PTO_NAM"] = "Bagno ospiti"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    renamed = devices.async_get(device.id)
    assert renamed.name == "Bagno ospiti"
    assert len(dr.async_entries_for_config_entry(devices, config_entry.entry_id)) == 1
    after = {
        e.entity_id
        for e in er.async_entries_for_config_entry(entities, config_entry.entry_id)
    }
    assert after == before
    assert hass.states.get("climate.bagno").attributes["friendly_name"] == (
        "Bagno ospiti"
    )


async def test_newer_entry_is_not_touched(
    hass, config_entry_v1, mock_login, mock_get_shadow
):
    """An entry from a newer version (downgrade) is not loaded."""
    entry = config_entry_v1
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, version=3)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
