"""Exercise real provider HTTP and HA flows, entities and lifecycle."""

import logging
import socket
from unittest.mock import patch

import probatio as vol
import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tsa_wait_times import get_feed
from custom_components.tsa_wait_times.client import (
    Feed,
    FeedError,
    parse,
    retry_seconds,
)
from custom_components.tsa_wait_times.config_flow import interval
from custom_components.tsa_wait_times.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.parametrize(
    "value", [True, False, "5", 1.2, 0, -1, 1441, None, float("inf"), float("nan")]
)
def test_bad_interval(value):
    with pytest.raises(vol.Invalid):
        interval(value)


@pytest.mark.parametrize("value", [1, 5, 5.0, 1440])
def test_interval(value):
    assert interval(value) == int(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 60),
        ("999999999999999999999999999999999999", 3600),
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


@pytest.mark.parametrize(
    "value", [None, True, 5, "", "unknown", "-1", "3.5", "１２", "9999999"]
)
def test_unknown_wait(payload, value):
    payload["WaitTimes"][0]["DisplayText"] = value
    assert parse(payload).waits["NorthGeneral"] is None


def test_closed_missing_extra(payload):
    payload["NorthCheckpointClosed"] = True
    payload["WaitTimes"].append({"CounterName": "FutureCounter", "DisplayText": "99"})
    snapshot = parse(payload)
    assert snapshot.waits["NorthGeneral"] is None
    assert snapshot.waits["SouthGeneral"] == 2
    payload["WaitTimes"] = []
    assert all(value is None for value in parse(payload).waits.values())


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"WaitTimes": []},
        {
            "WaitTimes": [None],
            "NorthCheckpointClosed": False,
            "SouthCheckpointClosed": False,
        },
    ],
)
def test_bad_schema(payload):
    with pytest.raises(FeedError):
        parse(payload)


def test_duplicate(payload):
    payload["WaitTimes"].append(payload["WaitTimes"][0])
    with pytest.raises(FeedError):
        parse(payload)


async def test_flow_lifecycle(hass, http, payload):
    http.add(payload)
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    assert form["type"] is FlowResultType.FORM
    assert set(form["data_schema"].schema) == {"airport", "scan_interval"}
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"airport": "PDX", "scan_interval": 5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(http.requests) == 1
    state = hass.states.get("sensor.tsa_wait_times_pdx_northgeneral")
    assert state.state == "0"
    assert state.attributes["unit_of_measurement"] == "min"
    assert state.attributes["friendly_name"] == "TSA Wait Times PDX North general wait"
    assert hass.states.get("binary_sensor.tsa_wait_times_pdx_north").state == "off"
    assert (
        len(
            [
                s
                for s in hass.states.async_all()
                if s.entity_id.startswith(
                    ("sensor.tsa_wait_times_", "binary_sensor.tsa_wait_times_")
                )
            ]
        )
        == 6
    )
    registry = er.async_get(hass)
    entity = registry.async_get(state.entity_id)
    uid = entity.unique_id
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
    assert options["data_schema"]({"scan_interval": 1}) == {"scan_interval": 1}
    from homeassistant.data_entry_flow import InvalidData

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            options["flow_id"], {"scan_interval": True}
        )
    assert entry.options == {}
    await hass.config_entries.options.async_configure(
        options["flow_id"], {"scan_interval": 1}
    )
    await hass.async_block_till_done()
    assert entry.options == {"scan_interval": 1}
    assert entry.runtime_data.update_interval.total_seconds() == 60
    assert registry.async_get("sensor.custom_wait").unique_id == uid
    assert (
        hass.states.get("sensor.custom_wait").attributes["friendly_name"] == "My wait"
    )
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostic == {
        "airport": "PDX",
        "poll_minutes": 1,
        "last_update_success": True,
        "source_observation_timestamp_available": False,
    }
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.custom_wait").state == "unavailable"
    assert len(http.requests) == 1


async def test_unavailable_refresh(hass, http, payload):
    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times",
        unique_id="PDX",
        data={"airport": "PDX", "scan_interval": 5},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    feed = get_feed(hass)
    feed.not_before = 0
    payload["NorthCheckpointClosed"] = True
    payload["WaitTimes"][2]["DisplayText"] = "N/A"
    http.add(payload)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.tsa_wait_times_pdx_northgeneral").state == "unavailable"
    )
    assert (
        hass.states.get("sensor.tsa_wait_times_pdx_southgeneral").state == "unavailable"
    )
    assert hass.states.get("binary_sensor.tsa_wait_times_pdx_north").state == "on"
    feed.not_before = 0
    http.add({"secret": "CANARY"}, status=500)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert (
        hass.states.get("binary_sensor.tsa_wait_times_pdx_north").state == "unavailable"
    )


@pytest.mark.parametrize(
    "status,payload", [(429, {}), (503, {}), (200, {"invalid": "CANARY"})]
)
async def test_failure_backoff(hass, http, status, payload, caplog):
    caplog.set_level(logging.DEBUG)
    http.add(payload, status=status, headers={"Retry-After": "1e309"})
    result = await hass.config_entries.flow.async_init(
        "tsa_wait_times",
        context={"source": "user"},
        data={"airport": "PDX", "scan_interval": 5},
    )
    assert result["errors"] == {"base": "cannot_connect"}
    hass.config_entries.flow.async_abort(result["flow_id"])
    result2 = await hass.config_entries.flow.async_init(
        "tsa_wait_times",
        context={"source": "user"},
        data={"airport": "PDX", "scan_interval": 5},
    )
    assert result2["errors"] == {"base": "cannot_connect"}
    entry = MockConfigEntry(
        domain="tsa_wait_times", unique_id="PDX", data={"airport": "PDX"}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(http.requests) == 1
    assert "CANARY" not in caplog.text
    assert "/feed" not in caplog.text
    await hass.config_entries.async_unload(entry.entry_id)


async def test_transport_sanitized(hass, http, caplog):
    caplog.set_level(logging.DEBUG)
    feed = Feed(async_get_clientsession(hass))
    with patch.object(
        feed.session, "get", side_effect=TimeoutError("URL_SECRET_CANARY")
    ):
        with pytest.raises(FeedError, match="Unable to read"):
            await feed.fetch()
    assert "URL_SECRET_CANARY" not in caplog.text


def test_external_network_blocked(socket_enabled):
    with pytest.raises(pytest_socket.SocketConnectBlockedError):
        socket.socket().connect(("192.0.2.1", 443))


async def test_exact_request_floor(hass, http, payload):
    from types import SimpleNamespace

    clock = SimpleNamespace(monotonic=lambda: now[0])
    now = [100.25]
    feed = Feed(async_get_clientsession(hass))
    http.add(payload)
    with patch("custom_components.tsa_wait_times.client.time", clock):
        first = await feed.fetch()
        now[0] = 160.249
        assert await feed.fetch() is first
        assert len(http.requests) == 1
        now[0] = 160.25
        http.add(payload)
        await feed.fetch()
        assert len(http.requests) == 2
        now[0] = 220.25
        http.add({}, status=429, headers={"Retry-After": "120"})
        with pytest.raises(FeedError):
            await feed.fetch()
        now[0] = 340.249
        with pytest.raises(FeedError, match="cooldown"):
            await feed.fetch()
        assert len(http.requests) == 3
        now[0] = 340.25
        http.add(payload)
        assert await feed.fetch() == first
        assert len(http.requests) == 4


async def test_native_scheduler_and_unload(hass, http, payload, freezer):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    http.add(payload)
    entry = MockConfigEntry(
        domain="tsa_wait_times",
        unique_id="PDX",
        data={"airport": "PDX", "scan_interval": 5},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(http.requests) == 1
    freezer.tick(timedelta(minutes=4))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(http.requests) == 1
    http.add(payload)
    freezer.tick(timedelta(minutes=1, seconds=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(http.requests) == 2


@pytest.mark.parametrize(
    "data",
    [
        {"airport": "AUS", "scan_interval": 5},
        {"airport": "PDX", "scan_interval": "5"},
        {"airport": "PDX", "scan_interval": 0},
    ],
)
async def test_invalid_setup(hass, http, data):
    result = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}, data=data
    )
    assert result["errors"] == {"base": "invalid_input"}
    assert http.requests == []


def test_form_serialization():
    from homeassistant.helpers import config_validation as cv

    from custom_components.tsa_wait_times.config_flow import schema

    fields = vol.to_field_list(
        schema(5, airport=True), custom_serializer=cv.custom_serializer
    )
    number = next(field for field in fields if field["name"] == "scan_interval")
    assert number["selector"]["number"]["unit_of_measurement"] == "min"
    assert number["selector"]["number"]["min"] == 1
