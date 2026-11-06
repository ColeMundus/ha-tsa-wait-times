"""TSAWaitTimes.com integration lifecycle and shared polling."""

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PATH, Airport, Feed, FeedError, Snapshot
from .const import (
    CONF_AIRPORT,
    CONF_INTERVAL,
    CONF_NAME,
    CONF_PATH,
    DEFAULT_INTERVAL,
    DOMAIN,
)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
type TSAConfigEntry = ConfigEntry[WaitCoordinator]


def get_feed(hass: HomeAssistant) -> Feed:
    """Share public catalog, cache and pacing across all entry/flow lifetimes."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = Feed(async_get_clientsession(hass))
    feed: Feed = hass.data[DOMAIN]
    return feed


class WaitCoordinator(DataUpdateCoordinator[Snapshot]):
    """One modeled estimate snapshot per airport."""

    def __init__(self, hass: HomeAssistant, entry: TSAConfigEntry) -> None:
        self.airport = Airport(
            entry.data[CONF_AIRPORT], entry.data[CONF_NAME], entry.data[CONF_PATH]
        )
        self.minutes = max(
            5,
            entry.options.get(
                CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
            ),
        )
        self.active = True
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=self.minutes),
        )
        self.feed = get_feed(hass)

    @callback
    def _schedule_refresh(self) -> None:
        """Clamp Core 2026.10's rounded/jittered timer to source deadlines."""
        if self._update_interval_seconds is not None and not (
            self.config_entry and self.config_entry.pref_disable_polling
        ):
            remaining = self.feed.deadline(self.airport.code) - time.monotonic()
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
            return await self.feed.fetch(
                self.airport, self.minutes, active=lambda: self.active
            )
        except FeedError as err:
            raise UpdateFailed(str(err)) from None


async def async_setup_entry(hass: HomeAssistant, entry: TSAConfigEntry) -> bool:
    """Set up with the HA-owned HTTP session."""
    match = PATH.fullmatch(entry.data.get(CONF_PATH, ""))
    if not match or match[1] != entry.data.get(CONF_AIRPORT):
        return False
    coordinator = WaitCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass: HomeAssistant, entry: TSAConfigEntry) -> None:
    """Only effective option changes reload; data writes must not loop."""
    effective = max(
        5,
        entry.options.get(
            CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        ),
    )
    if entry.runtime_data.minutes != effective:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TSAConfigEntry) -> bool:
    """Retire in-flight/queued refreshes; Core cancels its owned timer."""
    coordinator = entry.runtime_data
    coordinator.active = False
    try:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except BaseException:
        coordinator.active = True
        raise
    if not unloaded:
        coordinator.active = True
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: TSAConfigEntry) -> bool:
    """Replace the legacy PDX provider without changing config-entry identity."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        if entry.data.get(CONF_AIRPORT) != "PDX":
            return False
        data = {
            **entry.data,
            CONF_PATH: "/security-wait-times/PDX/Portland-International",
            CONF_NAME: "Portland International",
        }
        # Preserve preferences and entry unique_id; enforce the new source floor
        # in runtime instead of rewriting a user's legacy interval preference.
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
