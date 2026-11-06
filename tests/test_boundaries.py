"""Composed and timing regression boundaries for the public website client."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from conftest import CATALOG, entry_data, page
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tsa_wait_times import async_unload_entry
from custom_components.tsa_wait_times.client import Feed, FeedError


async def test_composed_directory_flow_setup(hass, http):
    """Actual directory HTTP → native selection → detail HTTP → real entities."""
    http.add(CATALOG)
    http.add(page("AUS"))
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"airport": "AUS", "scan_interval": 5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert result["result"].version == 2
    assert http.requests == ["/airports", entry_data("AUS")["path"]]
    assert hass.states.get("sensor.tsa_wait_times_aus_estimated_wait").state == "19.7"
    assert (
        hass.states.get("binary_sensor.tsa_wait_times_aus_precheck_available").state
        == "on"
    )


async def test_actual_start_floor_after_late_wake(hass, http, airport, payload):
    now = [100.25]

    async def sleep(delay):
        now[0] += delay + 0.7

    feed = Feed(async_get_clientsession(hass))
    feed.network_after = 105.25
    http.add(payload)
    with (
        patch(
            "custom_components.tsa_wait_times.client.time",
            SimpleNamespace(monotonic=lambda: now[0]),
        ),
        patch(
            "custom_components.tsa_wait_times.client.asyncio",
            SimpleNamespace(sleep=sleep),
        ),
    ):
        await feed.fetch(airport, interval=1)
        assert feed.deadline("PDX") == 405.95
        now[0] = 405.949
        await feed.fetch(airport)
        assert len(http.requests) == 1
        now[0] = 405.95
        http.add(payload)
        await feed.fetch(airport)
        assert len(http.requests) == 2


async def test_retire_during_pacing_never_starts_http(hass, http, airport):
    feed = Feed(async_get_clientsession(hass))
    feed.network_after = float("inf")
    active = [True]

    async def sleep(delay):
        active[0] = False

    with patch(
        "custom_components.tsa_wait_times.client.asyncio", SimpleNamespace(sleep=sleep)
    ):
        with pytest.raises(FeedError, match="retired"):
            await feed.fetch(airport, active=lambda: active[0])
    assert http.requests == []


async def test_shared_429_blocks_other_airport_and_directory(
    hass, http, airport, seeded
):
    from custom_components.tsa_wait_times.client import parse_catalog

    http.add("", status=429, headers={"Retry-After": "1e309"})
    with pytest.raises(FeedError):
        await seeded.fetch(airport)
    with pytest.raises(FeedError):
        await seeded.fetch(parse_catalog(CATALOG)["ATL"])
    seeded.catalog_until = 0
    with pytest.raises(FeedError):
        await seeded.airports()
    assert len(http.requests) == 1


async def test_unchanged_options_data_update_does_not_reload(
    hass, http, seeded, payload
):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times", version=2, unique_id="PDX", data=entry_data()
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old = entry.runtime_data
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "name": "New directory label"}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data is old
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 5}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data is old
    assert len(http.requests) == 1


async def test_migration_does_not_repurpose_or_delete_legacy_registry(
    hass, http, payload
):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times", version=1, unique_id="PDX", data={"airport": "PDX"}
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        "tsa_wait_times",
        "PDX_NorthGeneral",
        config_entry=entry,
        suggested_object_id="custom_legacy_wait",
    )
    registry.async_update_entity(legacy.entity_id, name="My original checkpoint")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(legacy.entity_id).unique_id == "PDX_NorthGeneral"
    assert registry.async_get(legacy.entity_id).name == "My original checkpoint"
    current = registry.async_get("sensor.tsa_wait_times_pdx_estimated_wait")
    assert current.unique_id == "PDX_estimated_wait"
    assert current.id != legacy.id


@pytest.mark.parametrize(
    "outcome", [False, RuntimeError("synthetic"), asyncio.CancelledError()]
)
async def test_failed_unload_restores_active_client(
    hass, http, seeded, payload, outcome
):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times", version=2, unique_id="PDX", data=entry_data()
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock = (
        AsyncMock(return_value=outcome)
        if outcome is False
        else AsyncMock(side_effect=outcome)
    )
    with patch.object(hass.config_entries, "async_unload_platforms", mock):
        if outcome is False:
            assert not await async_unload_entry(hass, entry)
        else:
            with pytest.raises(type(outcome)):
                await async_unload_entry(hass, entry)
    assert entry.runtime_data.active


@pytest.mark.parametrize("directory", [False, True])
async def test_deep_markup_sanitized(hass, http, airport, directory):
    html = "<div>" * 1100 + "CANARY" + "</div>" * 1100
    http.add(html)
    feed = Feed(async_get_clientsession(hass))
    with pytest.raises(FeedError, match="structure"):
        if directory:
            await feed.airports()
        else:
            await feed.fetch(airport)
