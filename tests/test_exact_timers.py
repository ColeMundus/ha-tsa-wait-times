"""Exact native coordinator deadlines and Core-owned cancellation."""

from datetime import timedelta
from unittest.mock import patch

import pytest
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


async def setup(hass, http, payload, freezer):
    freezer.move_to("2026-11-05T12:00:00.750000+00:00")
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times",
        unique_id="PDX",
        data={"airport": "PDX", "scan_interval": 1},
    )
    entry.add_to_hass(hass)
    with patch("homeassistant.helpers.update_coordinator.randint", return_value=50000):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 1
    return entry


@pytest.mark.parametrize("manual", [False, True])
async def test_fractional_native_deadline(hass, http, payload, freezer, manual):
    entry = await setup(hass, http, payload, freezer)
    floor = get_feed(hass).not_before
    if manual:
        # A real manual coordinator refresh must not bypass the source floor.
        await entry.runtime_data.async_request_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(http.requests) == 1
        assert get_feed(hass).not_before == floor
    await advance(hass, freezer, 59.3)
    assert len(http.requests) == 1
    await advance(hass, freezer, 0.699)
    assert len(http.requests) == 1
    http.add(payload)
    await advance(hass, freezer, 0.001)
    assert len(http.requests) == 2
    # Prove subsequent intervals do not silently double either.
    http.add(payload)
    await advance(hass, freezer, 60)
    assert len(http.requests) == 3
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("rate_limited", [False, True])
async def test_unload_cancels_clamped_timer(hass, http, payload, freezer, rate_limited):
    entry = await setup(hass, http, payload, freezer)
    if rate_limited:
        http.add({}, status=429, headers={"Retry-After": "3600"})
        await advance(hass, freezer, 60)
    else:
        await advance(hass, freezer, 59.3)
    count = len(http.requests)
    coordinator = entry.runtime_data
    assert coordinator._unsub_refresh is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._unsub_refresh is None
    await advance(hass, freezer, 0.7)
    await advance(hass, freezer, 3600)
    assert len(http.requests) == count


async def test_retry_after_exact_deadline_and_manual_floor(
    hass, http, payload, freezer
):
    entry = await setup(hass, http, payload, freezer)
    http.add({}, status=429, headers={"Retry-After": "120"})
    await advance(hass, freezer, 60)
    assert len(http.requests) == 2
    assert not entry.runtime_data.last_update_success
    floor = get_feed(hass).not_before
    await entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 2
    assert get_feed(hass).not_before == floor
    await advance(hass, freezer, 119.999)
    assert len(http.requests) == 2
    http.add(payload)
    await advance(hass, freezer, 0.001)
    assert len(http.requests) == 3
    assert entry.runtime_data.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)
