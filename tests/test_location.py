"""Local location suggestions exercised through native Home Assistant setup."""

from unittest.mock import patch

import probatio as vol
import pytest
from conftest import entry_data, page
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tsa_wait_times.airports import COORDINATES, nearest_airport


def airport_field(form):
    return next(
        field
        for field in vol.to_field_list(
            form["data_schema"], custom_serializer=cv.custom_serializer
        )
        if field["name"] == "airport"
    )


async def test_nearby_default_is_editable(hass, http, seeded):
    hass.config.latitude = 30.27
    hass.config.longitude = -97.74
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    field = airport_field(form)
    assert field["default"] == "AUS"
    assert {o["value"] for o in field["selector"]["select"]["options"]} == {
        "AUS",
        "ATL",
        "PDX",
        "DJT",
    }
    assert http.requests == []
    assert not hass.config_entries.async_entries("tsa_wait_times")


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (None, 0),
        (0, None),
        (float("nan"), 0),
        (0, float("inf")),
        (91, 0),
        (-91, 0),
        (0, 181),
        (0, -181),
        (True, 0),
        ("30", 0),
    ],
)
async def test_invalid_location_leaves_manual_form(
    hass, http, seeded, latitude, longitude
):
    hass.config.latitude = latitude
    hass.config.longitude = longitude
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    assert "default" not in airport_field(form)
    assert len(airport_field(form)["selector"]["select"]["options"]) == 4
    assert http.requests == []


@pytest.mark.parametrize("configured", [("AUS",), ("AUS", "ATL", "PDX", "DJT")])
async def test_existing_airports_not_suggested(hass, http, seeded, configured):
    hass.config.latitude, hass.config.longitude = 30.27, -97.74
    for code in configured:
        MockConfigEntry(
            domain="tsa_wait_times", unique_id=code, version=2, data=entry_data(code)
        ).add_to_hass(hass)
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    field = airport_field(form)
    if len(configured) == 1:
        assert field["default"] == "ATL"
    else:
        assert "default" not in field
    assert len(field["selector"]["select"]["options"]) == 4


async def test_override_retained_on_error_and_saved_without_location(
    hass, http, seeded
):
    hass.config.latitude, hass.config.longitude = 30.27, -97.74
    form = await hass.config_entries.flow.async_init(
        "tsa_wait_times", context={"source": "user"}
    )
    http.add("unavailable", status=503)
    failed = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"airport": "ATL", "scan_interval": 10}
    )
    assert failed["errors"] == {"base": "cannot_connect"}
    assert airport_field(failed)["default"] == "ATL"
    assert failed["data_schema"]({"airport": "ATL"})["scan_interval"] == 10
    seeded.deadlines.clear()
    seeded.last_attempt.clear()
    seeded.network_after = 0
    http.add(page("ATL"))
    result = await hass.config_entries.flow.async_configure(
        failed["flow_id"], {"airport": "ATL", "scan_interval": 10}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **entry_data("ATL", 10),
        "name": seeded.catalog["ATL"].name,
    }
    await hass.async_block_till_done()
    assert http.requests == [seeded.catalog["ATL"].path] * 2


async def test_unmapped_airport_still_selectable(hass, http, seeded):
    with patch.dict(COORDINATES, {}, clear=True):
        form = await hass.config_entries.flow.async_init(
            "tsa_wait_times", context={"source": "user"}
        )
        assert "default" not in airport_field(form)
        http.add(page("AUS"))
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"airport": "AUS", "scan_interval": 5}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()


def test_local_ranking_edges():
    with patch.dict(
        COORDINATES,
        {
            "AAA": (0, -179),
            "BBB": (0, 170),
            "CCC": (0, -179),
        },
        clear=True,
    ):
        assert nearest_airport(0, 179, ["BBB", "AAA"]) == "AAA"
        assert nearest_airport(0, -179, ["CCC", "AAA"]) == "AAA"
        assert nearest_airport(0, 0, ["BBB", "AAA"]) == "BBB"
        assert nearest_airport(90, 180, ["AAA"]) == "AAA"
        assert nearest_airport(-90, -180, ["AAA"]) == "AAA"
        assert nearest_airport(0, 0, ["UNKNOWN"]) is None
        assert nearest_airport(0, 0, []) is None


def test_reference_is_compact_and_valid():
    import math
    from pathlib import Path

    assert len(COORDINATES) == 250
    assert "PFN" not in COORDINATES
    assert "DJT" in COORDINATES
    assert Path("custom_components/tsa_wait_times/airports.py").stat().st_size < 20000
    for code, (latitude, longitude) in COORDINATES.items():
        assert len(code) == 3 and code.isupper()
        assert math.isfinite(latitude) and -90 <= latitude <= 90
        assert math.isfinite(longitude) and -180 <= longitude <= 180


async def test_zero_location_only_suggests_live_candidates(hass, http, seeded):
    hass.config.latitude, hass.config.longitude = 0, 0
    # Even a closer reference airport cannot be suggested if absent from the catalog.
    seeded.catalog = {"ATL": seeded.catalog["ATL"]}
    with patch.dict(COORDINATES, {"ATL": (10, 10), "AUS": (0, 0)}, clear=True):
        form = await hass.config_entries.flow.async_init(
            "tsa_wait_times", context={"source": "user"}
        )
        assert airport_field(form)["default"] == "ATL"
        assert http.requests == []
