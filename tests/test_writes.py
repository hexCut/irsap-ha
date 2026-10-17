"""Commands run one at a time and don't undo each other.

Each command reads the whole shadow, changes its own zone and writes the whole
shadow back. The fake cloud below records the writes but, like a slow cloud,
doesn't apply them, so a command started while another is in flight would read
the old shadow and its write would revert the other zone.
"""

import asyncio
import copy
from unittest.mock import patch

import pytest

from custom_components.irsap_ha import api
from custom_components.irsap_ha.const import DOMAIN

REAL_SLEEP = asyncio.sleep

TWO_ZONES = {
    "id": "shadow-id",
    "version": 7,
    "state": {
        "desired": {
            "E_NAM": "Casa",
            "AAA_NAM": "Bagno",
            "AAA_TMP": 210,
            "AAA_ENB": 1,
            "AAA_MSP": {"p": {"u": 0, "v": 200, "m": 3}},
            "AAA_CSP": {"p": {"u": 0, "v": 200, "m": 3}},
            "BBB_NAM": "Camera",
            "BBB_TMP": 190,
            "BBB_ENB": 1,
            "BBB_MSP": {"p": {"u": 0, "v": 200, "m": 3}},
            "BBB_CSP": {"p": {"u": 0, "v": 200, "m": 3}},
        }
    },
}


class FakeCloud:
    """GetShadow returns ``self.shadow``; UpdateShadow only records."""

    def __init__(self):
        self.shadow = copy.deepcopy(TWO_ZONES)
        self.writes = []
        self.active = 0
        self.max_active = 0
        self.fail = False

    async def get(self, hass, token, envID):
        await REAL_SLEEP(0)
        return copy.deepcopy(self.shadow)

    async def update(self, hass, token, envID, payload):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await REAL_SLEEP(0.01)
        self.active -= 1
        if self.fail:
            return False
        self.writes.append(copy.deepcopy(payload))
        return True


async def _no_sleep(*args):
    return None


class _FastAsyncio:
    """climate's view of asyncio, without its 1 s pause before each command
    (patching asyncio.sleep itself would also stop Home Assistant's loop)."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    sleep = staticmethod(_no_sleep)


@pytest.fixture
async def cloud(hass, config_entry, mock_login):
    fake = FakeCloud()
    with (
        patch("custom_components.irsap_ha.api.async_get_shadow", side_effect=fake.get),
        patch(
            "custom_components.irsap_ha.climate.async_update_shadow",
            side_effect=fake.update,
        ),
        patch("custom_components.irsap_ha.climate.asyncio", _FastAsyncio()),
    ):
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        yield fake


async def _set_temperature(hass, entity_id, temperature):
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "temperature": temperature},
        blocking=True,
    )


def _msp(payload, zone):
    return payload["state"]["desired"][f"{zone}_MSP"]["p"]["v"]


async def test_concurrent_commands_dont_undo_each_other(hass, cloud):
    """'Set every radiator' from an automation: both changes must survive."""
    await asyncio.gather(
        _set_temperature(hass, "climate.bagno_radiator", 25),
        _set_temperature(hass, "climate.camera_radiator", 22),
    )

    assert len(cloud.writes) == 2
    assert cloud.max_active == 1  # never two writes in flight
    last = cloud.writes[-1]
    assert _msp(last, "AAA") == 250
    assert _msp(last, "BBB") == 220


async def test_builds_on_cloud_once_it_has_moved_on(hass, cloud):
    """When the cloud returns a newer version (our write applied, or a change
    made in the app), the next command starts from the cloud, not from our
    copy."""
    await _set_temperature(hass, "climate.bagno_radiator", 25)

    cloud.shadow["version"] = 8
    cloud.shadow["state"]["desired"]["AAA_MSP"]["p"]["v"] = 250
    cloud.shadow["state"]["desired"]["BBB_MSP"]["p"]["v"] = 180  # from the app

    await _set_temperature(hass, "climate.bagno_radiator", 26)

    last = cloud.writes[-1]
    assert last["version"] == 8
    assert _msp(last, "AAA") == 260
    assert _msp(last, "BBB") == 180


async def test_own_write_forgotten_after_settle_time(hass, cloud):
    await _set_temperature(hass, "climate.bagno_radiator", 25)

    # as if WRITE_SETTLE_TIME had passed since the first write
    with patch.object(api, "WRITE_SETTLE_TIME", -1):
        await _set_temperature(hass, "climate.camera_radiator", 22)

    # the cloud never applied the first write, and it's too old to reuse
    last = cloud.writes[-1]
    assert _msp(last, "AAA") == 200
    assert _msp(last, "BBB") == 220


async def test_failed_write_is_not_reused(hass, cloud):
    cloud.fail = True
    await _set_temperature(hass, "climate.bagno_radiator", 25)
    cloud.fail = False

    await _set_temperature(hass, "climate.camera_radiator", 22)

    assert len(cloud.writes) == 1
    assert _msp(cloud.writes[0], "AAA") == 200
    assert _msp(cloud.writes[0], "BBB") == 220


async def test_refreshes_still_read_the_cloud(hass, cloud, config_entry):
    """Only commands build on the last write: the coordinator shows what the
    cloud reports."""
    await _set_temperature(hass, "climate.bagno_radiator", 25)

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    assert coordinator.desired["AAA_MSP"]["p"]["v"] == 200


async def test_unload_forgets_lock_and_last_write(hass, cloud, config_entry):
    await _set_temperature(hass, "climate.bagno_radiator", 25)
    assert "last_write" in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    for key in api.WRITE_DATA_KEYS:
        assert key not in hass.data.get(DOMAIN, {})
