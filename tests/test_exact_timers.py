"""Exact native coordinator deadlines and Core-owned cancellation."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from conftest import entry_data
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)

from custom_components.tsa_wait_times import get_feed


async def advance(hass, freezer, seconds):
    """Fire exact timers, including coordinator background refresh tasks."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed_exact(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)


async def setup(hass, http, payload, freezer, seeded):
    freezer.move_to("2026-11-05T12:00:00.750000+00:00")
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times",
        unique_id="PDX",
        version=2,
        data=entry_data(),
    )
    entry.add_to_hass(hass)
    with patch("homeassistant.helpers.update_coordinator.randint", return_value=50000):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 1
    return entry


@pytest.mark.parametrize("manual", [False, True])
async def test_fractional_native_deadline(hass, http, payload, freezer, seeded, manual):
    entry = await setup(hass, http, payload, freezer, seeded)
    floor = get_feed(hass).deadline("PDX")
    if manual:
        # A real manual coordinator refresh must not bypass the source floor.
        await entry.runtime_data.async_request_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(http.requests) == 1
        assert get_feed(hass).deadline("PDX") == floor
    await advance(hass, freezer, 299.3)
    assert len(http.requests) == 1
    await advance(hass, freezer, 0.699)
    assert len(http.requests) == 1
    http.add(payload)
    await advance(hass, freezer, 0.001)
    assert len(http.requests) == 2
    # Prove subsequent intervals do not silently double either.
    http.add(payload)
    await advance(hass, freezer, 300)
    assert len(http.requests) == 3
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("rate_limited", [False, True])
async def test_unload_cancels_clamped_timer(
    hass, http, payload, freezer, seeded, rate_limited
):
    entry = await setup(hass, http, payload, freezer, seeded)
    if rate_limited:
        http.add("", status=429, headers={"Retry-After": "3600"})
        await advance(hass, freezer, 300)
    else:
        await advance(hass, freezer, 299.3)
    count = len(http.requests)
    coordinator = entry.runtime_data
    assert coordinator._unsub_refresh is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._unsub_refresh is None
    await advance(hass, freezer, 0.7)
    await advance(hass, freezer, 3600)
    assert len(http.requests) == count


async def test_retry_after_exact_deadline_and_manual_floor(
    hass, http, payload, freezer, seeded
):
    entry = await setup(hass, http, payload, freezer, seeded)
    http.add("", status=429, headers={"Retry-After": "600"})
    await advance(hass, freezer, 300)
    assert len(http.requests) == 2
    assert not entry.runtime_data.last_update_success
    floor = get_feed(hass).deadline("PDX")
    await entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 2
    assert get_feed(hass).deadline("PDX") == floor
    await advance(hass, freezer, 599.999)
    assert len(http.requests) == 2
    http.add(payload)
    await advance(hass, freezer, 0.001)
    assert len(http.requests) == 3
    assert entry.runtime_data.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_reload_reduction_retains_exact_floor(
    hass, http, payload, freezer, seeded
):
    entry = await setup(hass, http, payload, freezer, seeded)
    # Increase to ten minutes, then reduce after an elapsed minute. Reload uses
    # cached data and must not erase the already-established ten-minute floor.
    form = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        form["flow_id"], {"scan_interval": 10}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 1
    await advance(hass, freezer, 60)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        form["flow_id"], {"scan_interval": 5}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.minutes == 5
    assert len(http.requests) == 1
    await advance(hass, freezer, 539.999)
    assert len(http.requests) == 1
    http.add(payload)
    await advance(hass, freezer, 0.001)
    assert len(http.requests) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
