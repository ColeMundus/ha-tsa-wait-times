"""TSA Wait Times integration."""

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import Feed, FeedError, Snapshot
from .const import CONF_INTERVAL, DEFAULT_INTERVAL, DOMAIN

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
type TSAConfigEntry = ConfigEntry[WaitCoordinator]


def get_feed(hass: HomeAssistant) -> Feed:
    """Retain only public source pacing/cache across entry lifetimes."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = Feed(async_get_clientsession(hass))
    feed: Feed = hass.data[DOMAIN]
    return feed


class WaitCoordinator(DataUpdateCoordinator[Snapshot]):
    """One source read for all six entities."""

    def __init__(self, hass: HomeAssistant, entry: TSAConfigEntry) -> None:
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                minutes=entry.options.get(
                    CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                )
            ),
        )
        self.feed = get_feed(hass)

    @callback
    def _schedule_refresh(self) -> None:
        """Clamp Core's rounded/jittered timer to the retained source deadline."""
        if self._update_interval_seconds is not None and not (
            self.config_entry and self.config_entry.pref_disable_polling
        ):
            # Core 2026.10 schedules at int(loop.time()) + jitter + interval.
            # Supply its one-shot interval override rather than owning another
            # timer/task: Core retains unload/shutdown cancellation and dispatch.
            remaining = self.feed.not_before - time.monotonic()
            now = self.hass.loop.time()
            floor_interval = remaining + (now - int(now)) - self._microsecond
            self._retry_after = max(
                self._retry_after
                if self._retry_after is not None
                else self._update_interval_seconds,
                floor_interval,
            )
        super()._schedule_refresh()

    async def _async_update_data(self) -> Snapshot:
        try:
            return await self.feed.fetch()
        except FeedError as err:
            raise UpdateFailed(str(err)) from None


async def async_setup_entry(hass: HomeAssistant, entry: TSAConfigEntry) -> bool:
    """Set up using the HA-owned HTTP session."""
    coordinator = WaitCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass: HomeAssistant, entry: TSAConfigEntry) -> None:
    """Apply changed options through Core's normal reload lifecycle."""
    effective = entry.options.get(
        CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
    )
    if entry.runtime_data.update_interval != timedelta(minutes=effective):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TSAConfigEntry) -> bool:
    """Unload platforms (Core owns coordinator timer cancellation)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
