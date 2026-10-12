"""Shared data update coordinator for the IRSAP integration."""

from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import async_fetch_shadow
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def get_scan_interval(config_entry) -> timedelta:
    """Return the update interval chosen in the integration options."""
    seconds = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    return timedelta(seconds=int(seconds))


class IrsapCoordinator(DataUpdateCoordinator):
    """Fetch the environment shadow once per interval for all entities.

    ``data`` is the decoded GetShadow payload; every climate and light entity
    reads its own device from ``data["state"]["desired"]``. When the
    integration's "Enable polling for changes" system option is off, Home
    Assistant does not schedule refreshes and ``homeassistant.update_entity``
    triggers one instead.
    """

    def __init__(self, hass, config_entry):
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=get_scan_interval(config_entry),
        )
        self.envID = config_entry.data["envID"]

    async def _async_update_data(self):
        _token, payload = await async_fetch_shadow(self.hass, self.envID)
        if payload is None:
            raise UpdateFailed("Unable to retrieve data from the IRSAP cloud")
        return payload

    @property
    def desired(self):
        """The ``state.desired`` part of the last payload."""
        return (self.data or {}).get("state", {}).get("desired", {})
