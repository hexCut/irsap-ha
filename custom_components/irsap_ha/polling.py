"""Configurable polling for IRSAP entities that read the cloud."""

from datetime import timedelta
import logging

from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def get_scan_interval(config_entry) -> timedelta:
    """Return the update interval chosen in the integration options."""
    seconds = DEFAULT_SCAN_INTERVAL
    if config_entry is not None:
        seconds = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    return timedelta(seconds=int(seconds))


class ConfigurablePollingMixin:
    """Poll the entity on the interval set in the options flow.

    Home Assistant's built-in polling uses a fixed per-platform SCAN_INTERVAL,
    so the entity opts out of it (``should_poll = False``) and schedules its own
    timer instead. Runs never overlap: if the cloud is slow and the previous
    update is still in progress, the tick is skipped.

    The integration's "Enable polling for changes" system option is honoured:
    when it is turned off, no timer is started and updates only happen through
    ``homeassistant.update_entity``.
    """

    _attr_should_poll = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._irsap_update_running = False

        config_entry = getattr(self.platform, "config_entry", None)
        if config_entry is not None and config_entry.pref_disable_polling:
            _LOGGER.debug(
                "Polling disabled in system options, not scheduling updates for %s",
                self.entity_id,
            )
            return

        interval = get_scan_interval(config_entry)
        _LOGGER.debug("Updating %s every %s", self.entity_id, interval)
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._async_scheduled_update,
                interval,
                name=f"IRSAP update {self.entity_id}",
                cancel_on_shutdown=True,
            )
        )

    async def _async_scheduled_update(self, _now=None) -> None:
        if self._irsap_update_running:
            _LOGGER.debug(
                "Previous update of %s still running, skipping this one",
                self.entity_id,
            )
            return
        self._irsap_update_running = True
        try:
            await self.async_update_ha_state(force_refresh=True)
        finally:
            self._irsap_update_running = False
