"""Real HA flows, registry, lifecycle, diagnostics and HTTP client behavior."""

import asyncio
import logging
import socket
from types import SimpleNamespace
from unittest.mock import patch

import probatio as vol
import pytest
import pytest_socket
from conftest import CATALOG, entry_data, page
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tsa_wait_times import async_migrate_entry
from custom_components.tsa_wait_times.client import (
    Feed,
    FeedError,
    parse,
    parse_catalog,
    retry_seconds,
)
from custom_components.tsa_wait_times.config_flow import interval, schema
from custom_components.tsa_wait_times.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.parametrize(
    "value",
    [True, False, "5", 5.2, 0, 1, 4, -1, 1441, None, float("inf"), float("nan")],
)
def test_bad_interval(value):
    with pytest.raises(vol.Invalid):
        interval(value)


@pytest.mark.parametrize("value", [5, 5.0, 1440])
def test_interval(value):
    assert interval(value) == int(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 60),
        ("9" * 400, 3600),
        ("1e309", 3600),
        ("nan", 3600),
        ("-3", 60),
        ("120", 120),
        ("garbage", 60),
        ("Thu, 01 Jan 1970 00:00:00 GMT", 60),
    ],
)
def test_retry(value, expected):
    assert retry_seconds(value) == expected


def test_catalog_exact_paths():
    airports = parse_catalog(
        CATALOG + '<a href="/security-wait-times/XXX/Outside">ignore</a>'
    )
    assert set(airports) == {"AUS", "ATL", "PDX", "DJT"}
    assert airports["DJT"].path.endswith("Donald-J.-Trump-International")
    with pytest.raises(FeedError):
        parse_catalog(
            CATALOG + '<div class="list-group">'
            '<a href="/security-wait-times/PDX/Different">conflict</a></div>'
        )
    with pytest.raises(FeedError):
        parse_catalog("<html>home</html>")


def test_parser(payload, airport):
    result = parse(payload, airport)
    assert result.minutes == 19.7
    assert result.precheck is True
    assert result.hourly == (
        {"time_slot": "1 am - 2 am", "minutes": 7.0},
        {"time_slot": "3 am - 4 am", "minutes": 0.0},
    )
    assert result.checkpoints == (
        {"terminal": "Terminal TEST", "checkpoint": "Checkpoint A", "status": "Open"},
        {"terminal": "Terminal TEST", "checkpoint": "Checkpoint B", "status": "Closed"},
    )
    assert result.fetched_at.tzinfo is not None
    assert (
        parse(
            page(duration="0 minutes and 0 seconds*", precheck="Not Available"), airport
        ).minutes
        == 0
    )
    assert parse(page(precheck="Not Available"), airport).precheck is False


@pytest.mark.parametrize(
    "duration",
    [
        "unknown",
        "",
        "-1 minutes and 0 seconds*",
        "1 minutes and 99 seconds*",
        "19",
        "CANARY",
    ],
)
def test_missing_estimate(airport, duration):
    assert parse(page(duration=duration), airport).minutes is None


@pytest.mark.parametrize(
    "html",
    [
        "<html>homepage</html>",
        page("AUS"),
        '<div id="hourly_predictions"><p>PDX</p></div>',
    ],
)
def test_wrong_airport(html, airport):
    with pytest.raises(FeedError, match="identity"):
        parse(html, airport)


def test_missing_optional_sections(airport):
    result = parse(
        '<div id="hourly_predictions"><p class="lead">PDX : Test</p></div>', airport
    )
    assert result.minutes is None and result.precheck is None
    assert result.checkpoints == result.hourly == ()


async def test_live_directory_form(hass, http):
    http.add(CATALOG)
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    assert form["type"] is FlowResultType.FORM
    assert set(form["data_schema"].schema) == {"airport", "scan_interval"}
    from homeassistant.helpers import config_validation as cv

    fields = vol.to_field_list(
        form["data_schema"], custom_serializer=cv.custom_serializer
    )
    options = next(f for f in fields if f["name"] == "airport")["selector"]["select"][
        "options"
    ]
    assert {o["value"] for o in options} == {"AUS", "ATL", "PDX", "DJT"}
    number = next(f for f in fields if f["name"] == "scan_interval")["selector"][
        "number"
    ]
    assert number["min"] == 5 and number["unit_of_measurement"] == "min"
    second = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    assert second["type"] is FlowResultType.FORM
    assert http.requests == ["/airports"]


async def test_flow_lifecycle(hass, http, payload, seeded):
    http.add(payload)
    result = await hass.config_entries.flow.async_init(
        "tsa_wait_times",
        context={"source": "user"},
        data={"airport": "PDX", "scan_interval": 5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.version == 2 and entry.unique_id == "PDX"
    assert entry.state is ConfigEntryState.LOADED
    assert len(http.requests) == 1
    state = hass.states.get("sensor.tsa_wait_times_pdx_estimated_wait")
    assert state.state == "19.7"
    assert state.attributes["unit_of_measurement"] == "min"
    assert state.attributes["friendly_name"] == "TSA Wait Times PDX Estimated wait"
    assert state.attributes["estimate_type"] == "modeled"
    assert len(state.attributes["hourly_estimates"]) == 2
    assert (
        hass.states.get("binary_sensor.tsa_wait_times_pdx_precheck_available").state
        == "on"
    )
    assert (
        len(
            [s for s in hass.states.async_all() if "tsa_wait_times_pdx_" in s.entity_id]
        )
        == 2
    )
    registry = er.async_get(hass)
    uid = registry.async_get(state.entity_id).unique_id
    registry.async_update_entity(
        state.entity_id, new_entity_id="sensor.custom_wait", name="My wait"
    )
    duplicate = await hass.config_entries.flow.async_init(
        "tsa_wait_times",
        context={"source": "user"},
        data={"airport": "PDX", "scan_interval": 5},
    )
    assert duplicate["reason"] == "already_configured"
    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert options["data_schema"]({"scan_interval": 10}) == {"scan_interval": 10}
    from homeassistant.data_entry_flow import InvalidData

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            options["flow_id"], {"scan_interval": True}
        )
    await hass.config_entries.options.async_configure(
        options["flow_id"], {"scan_interval": 10}
    )
    await hass.async_block_till_done()
    assert entry.options == {"scan_interval": 10}
    assert entry.runtime_data.update_interval.total_seconds() == 600
    assert registry.async_get("sensor.custom_wait").unique_id == uid
    assert (
        hass.states.get("sensor.custom_wait").attributes["friendly_name"] == "My wait"
    )
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostic["airport"] == "PDX" and diagnostic["poll_minutes"] == 10
    assert diagnostic["source_observation_timestamp_available"] is False
    assert set(diagnostic) == {
        "airport",
        "poll_minutes",
        "last_update_success",
        "source",
        "estimate_type",
        "source_observation_timestamp_available",
        "fetched_at",
    }
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.states.get("sensor.custom_wait").state == "unavailable"
    assert len(http.requests) == 1


async def test_two_airport_entries(hass, http, seeded):
    for code in ["AUS", "ATL"]:
        # Aggregate pacing itself has a separate deterministic test.
        seeded.network_after = 0
        http.add(page(code))
        result = await hass.config_entries.flow.async_init(
            "tsa_wait_times",
            context={"source": "user"},
            data={"airport": code, "scan_interval": 5},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert (
            hass.states.get(
                f"sensor.tsa_wait_times_{code.lower()}_estimated_wait"
            ).state
            == "19.7"
        )
    assert len(http.requests) == 2
    assert http.requests[0] != http.requests[1]


async def test_unavailable_refresh(hass, http, payload, seeded):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times", unique_id="PDX", version=2, data=entry_data()
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for body, status in [
        (page(duration="unknown", precheck="unknown"), 200),
        ("CANARY", 500),
    ]:
        seeded.deadlines.clear()
        seeded.last_attempt.clear()
        seeded.network_after = 0
        http.add(body, status=status)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert (
            hass.states.get("sensor.tsa_wait_times_pdx_estimated_wait").state
            == "unavailable"
        )
        assert (
            hass.states.get("binary_sensor.tsa_wait_times_pdx_precheck_available").state
            == "unavailable"
        )


@pytest.mark.parametrize(
    "status,body", [(429, "CANARY"), (503, "CANARY"), (302, "CANARY"), (200, "CANARY")]
)
async def test_failure_backoff(hass, http, seeded, status, body, caplog):
    caplog.set_level(logging.DEBUG)
    http.add(
        body,
        status=status,
        headers={"Retry-After": "1e309", "Location": "https://example.invalid/CANARY"},
    )
    result = await hass.config_entries.flow.async_init(
        "tsa_wait_times",
        context={"source": "user"},
        data={"airport": "PDX", "scan_interval": 5},
    )
    assert result["errors"] == {"base": "cannot_connect"}
    hass.config_entries.flow.async_abort(result["flow_id"])
    result = await hass.config_entries.flow.async_init(
        "tsa_wait_times",
        context={"source": "user"},
        data={"airport": "PDX", "scan_interval": 5},
    )
    assert result["errors"] == {"base": "cannot_connect"}
    entry = MockConfigEntry(
        domain="tsa_wait_times", unique_id="PDX", version=2, data=entry_data()
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(http.requests) == 1 and "CANARY" not in caplog.text
    await hass.config_entries.async_unload(entry.entry_id)


async def test_directory_failure_retry(hass, http):
    http.add("CANARY", status=500)
    for _ in range(2):
        result = await hass.config_entries.flow.async_init(
            "tsa_wait_times", context={"source": "user"}
        )
        assert result["errors"] == {"base": "cannot_connect"}
    assert http.requests == ["/airports"]


async def test_transport_sanitized(hass, http, airport, caplog):
    caplog.set_level(logging.DEBUG)
    feed = Feed(async_get_clientsession(hass))
    with patch.object(
        feed.session, "get", side_effect=TimeoutError("URL_SECRET_CANARY")
    ):
        with pytest.raises(FeedError, match="Unable to read"):
            await feed.fetch(airport)
    assert "URL_SECRET_CANARY" not in caplog.text


def test_external_network_blocked(socket_enabled):
    with pytest.raises(pytest_socket.SocketConnectBlockedError):
        socket.socket().connect(("192.0.2.1", 443))


async def test_pacing_cache_retry(hass, http, payload, airport):
    now = [100.25]
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    feed = Feed(async_get_clientsession(hass))
    clock = SimpleNamespace(monotonic=lambda: now[0])
    api = SimpleNamespace(sleep=sleep)
    with (
        patch("custom_components.tsa_wait_times.client.time", clock),
        patch("custom_components.tsa_wait_times.client.asyncio", api),
    ):
        http.add(CATALOG)
        catalog = await feed.airports()
        assert await feed.airports() is catalog
        http.add(payload)
        first = await feed.fetch(airport)
        assert sleeps == [5] and len(http.requests) == 2
        now[0] = 405.249
        assert await feed.fetch(airport) is first
        now[0] = 405.25
        http.add(payload)
        await feed.fetch(airport)
        now[0] = 705.25
        http.add("", status=429, headers={"Retry-After": "600"})
        with pytest.raises(FeedError):
            await feed.fetch(airport)
        now[0] = 1305.249
        with pytest.raises(FeedError):
            await feed.fetch(airport)
        assert len(http.requests) == 4
        now[0] = 1305.25
        http.add(payload)
        assert (await feed.fetch(airport)).minutes == first.minutes
        http.add(page("ATL"))
        await feed.fetch(catalog["ATL"])
        assert sleeps == [5, 5]
        assert http.requests[-1] == catalog["ATL"].path


async def test_migration_preserves_identity_preferences(hass, http, payload):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times",
        unique_id="PDX",
        version=1,
        data={"airport": "PDX", "scan_interval": 1},
        options={"scan_interval": 1},
        pref_disable_polling=True,
        title="My airport",
    )
    entry.add_to_hass(hass)
    old_data = dict(entry.data)
    old_options = dict(entry.options)
    old_id = entry.entry_id
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2 and entry.unique_id == "PDX" and entry.entry_id == old_id
    assert (
        all(entry.data[k] == v for k, v in old_data.items())
        and entry.options == old_options
    )
    assert entry.title == "My airport" and entry.pref_disable_polling is True
    assert entry.runtime_data.minutes == 5
    assert entry.data["path"] == "/security-wait-times/PDX/Portland-International"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(http.requests) == 1


async def test_migration_rejects_unknown(hass):
    for version, code in [(3, "PDX"), (1, "AUS")]:
        entry = MockConfigEntry(
            domain="tsa_wait_times", version=version, data={"airport": code}
        )
        entry.add_to_hass(hass)
        assert not await async_migrate_entry(hass, entry)


@pytest.mark.parametrize(
    "data",
    [
        {"airport": "XXX", "scan_interval": 5},
        {"airport": "PDX", "scan_interval": "5"},
        {"airport": "PDX", "scan_interval": 1},
    ],
)
async def test_invalid_setup(hass, http, seeded, data):
    # Test schema directly too: Core rejects invalid user submissions before step.
    with pytest.raises(vol.Invalid):
        schema(5, seeded.catalog)(data)
    assert http.requests == []


async def test_retirement_blocks_publication_and_queued_http(
    hass, http, payload, seeded
):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times", version=2, unique_id="PDX", data=entry_data()
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old = entry.runtime_data
    seeded.deadlines.clear()
    seeded.last_attempt.clear()
    seeded.network_after = 0
    http.add(page(duration="44 minutes and 0 seconds*"), blocked=True)
    task = asyncio.create_task(old.async_refresh())
    await http.started.wait()
    queued = asyncio.create_task(seeded.fetch(old.airport, active=lambda: old.active))
    assert await hass.config_entries.async_unload(entry.entry_id)
    http.release.set()
    await task
    with pytest.raises(FeedError, match="retired"):
        await queued
    assert "PDX" not in seeded.snapshots
    assert not old.active and len(http.requests) == 2
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert len(http.requests) == 2


async def test_response_size_limit(hass, http, airport):
    http.add("x" * 2_000_001)
    with pytest.raises(FeedError, match="too large"):
        await Feed(async_get_clientsession(hass)).fetch(airport)
