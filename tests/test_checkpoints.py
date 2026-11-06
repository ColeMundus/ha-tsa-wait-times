"""Native checkpoint entities driven by one loopback airport snapshot."""

from html import escape

from conftest import entry_data, page
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


def checkpoint_page(rows):
    body = page("AUS").split('<div id="precheck_status">')[0]
    body += '<div id="precheck_status"><h4>Available</h4>'
    for terminal, checkpoint, status in rows:
        body += (
            f"<p>{escape(terminal)}</p><ul><li>{escape(checkpoint)} "
            f'<span class="badge">{escape(status)}</span></li></ul>'
        )
    return body + "</div>"


ROWS = [
    ("Terminal MAIN", "Checkpoint 1", "Open"),
    ("Terminal MAIN", "Checkpoint 2", "Open"),
    ("Terminal MAIN", "Main Checkpoint", "Closed"),
]


async def setup_airport(hass, http, rows):
    http.add(checkpoint_page(rows))
    entry = MockConfigEntry(
        domain="tsa_wait_times", unique_id="AUS", version=2, data=entry_data("AUS")
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def checkpoints(hass, entry):
    return [
        entity
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.unique_id not in {"AUS_estimated_wait", "AUS_precheck_available"}
    ]


async def refresh(hass, http, seeded, entry, rows=None, *, body=None, status=200):
    # Exercise the HTTP/parser/coordinator path without waiting five minutes.
    seeded.deadlines.clear()
    seeded.last_attempt.clear()
    seeded.network_after = 0
    http.add(checkpoint_page(rows) if body is None else body, status=status)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_initial_checkpoints_and_existing_contract(hass, http, seeded):
    entry = await setup_airport(hass, http, ROWS)
    entities = checkpoints(hass, entry)
    assert len(entities) == 3
    for entity, (terminal, checkpoint, status) in zip(entities, ROWS, strict=True):
        state = hass.states.get(entity.entity_id)
        assert state.state == ("on" if status == "Open" else "off")
        assert state.attributes["terminal"] == terminal
        assert state.attributes["checkpoint"] == checkpoint
        assert state.attributes["status"] == status
        assert state.attributes["friendly_name"] == (
            f"TSA Wait Times AUS {terminal} {checkpoint} open"
        )
        assert entity.entity_id.startswith("binary_sensor.tsa_wait_times_aus_")
        assert "unit_of_measurement" not in state.attributes
        device = dr.async_get(hass).async_get(entity.device_id)
        assert device.name == "TSA Wait Times AUS"
    registry = er.async_get(hass)
    assert registry.async_get("sensor.tsa_wait_times_aus_estimated_wait").unique_id == (
        "AUS_estimated_wait"
    )
    precheck = hass.states.get("binary_sensor.tsa_wait_times_aus_precheck_available")
    assert registry.async_get(precheck.entity_id).unique_id == "AUS_precheck_available"
    assert precheck.state == "on"
    assert precheck.attributes["checkpoints"] == [
        {"terminal": t, "checkpoint": c, "status": s} for t, c, s in ROWS
    ]
    assert http.requests == [entry_data("AUS")["path"]]


async def test_checkpoint_identity_customization_reload(hass, http, seeded):
    rows = [
        ("Terminal A", "Checkpoint 1", "Open"),
        ("Terminal B", "Checkpoint 1", "Closed"),
        ("Terminal A", "Checkpoint-1", "Open"),
        ("Terminal A", "Checkpoint/1", "Closed"),
    ]
    entry = await setup_airport(hass, http, rows)
    entities = checkpoints(hass, entry)
    assert len(entities) == len({e.unique_id for e in entities}) == 4
    identities = {e.unique_id: e.id for e in entities}
    registry = er.async_get(hass)
    custom = registry.async_update_entity(
        entities[0].entity_id,
        new_entity_id="binary_sensor.my_checkpoint",
        name="My checkpoint",
    )
    await refresh(hass, http, seeded, entry, list(reversed(rows)))
    assert {e.unique_id: e.id for e in checkpoints(hass, entry)} == identities
    old = entry.runtime_data
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {e.unique_id: e.id for e in checkpoints(hass, entry)} == identities
    assert registry.async_get(custom.entity_id).unique_id == custom.unique_id
    state = hass.states.get(custom.entity_id)
    assert state.state == "on"
    assert state.attributes["friendly_name"] == "My checkpoint"
    assert len(http.requests) == 2  # Reload shares the cache; no entity HTTP.
    assert not old._listeners
    current = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not current._listeners
    # A retired coordinator cannot create entities via a leaked discovery callback.
    from custom_components.tsa_wait_times.client import parse

    old.async_set_updated_data(parse(checkpoint_page(ROWS), old.airport))
    await hass.async_block_till_done()
    assert {e.unique_id: e.id for e in checkpoints(hass, entry)} == identities


async def test_later_discovery_missing_unknown_failure_and_recovery(hass, http, seeded):
    entry = await setup_airport(hass, http, ROWS[:1])
    first = checkpoints(hass, entry)[0]
    await refresh(hass, http, seeded, entry, ROWS + [ROWS[0]])
    entities = checkpoints(hass, entry)
    assert len(entities) == 3  # Duplicate rows do not create duplicate entities.
    identities = {e.unique_id: e.id for e in entities}
    await refresh(
        hass, http, seeded, entry, [("Terminal MAIN", "Checkpoint 1", "Closed")]
    )
    assert hass.states.get(first.entity_id).state == "off"
    for entity in entities[1:]:
        assert hass.states.get(entity.entity_id).state == "unavailable"
    await refresh(
        hass, http, seeded, entry, [("Terminal MAIN", "Checkpoint 1", "Unknown")]
    )
    assert all(hass.states.get(e.entity_id).state == "unavailable" for e in entities)
    # Missing sensors remain in the registry through an actual reload as well.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {e.unique_id: e.id for e in checkpoints(hass, entry)} == identities
    assert all(hass.states.get(e.entity_id).state == "unavailable" for e in entities)
    for body, status in [("invalid provider page", 200), ("", 503)]:
        await refresh(hass, http, seeded, entry, body=body, status=status)
        assert all(
            hass.states.get(e.entity_id).state == "unavailable" for e in entities
        )
    await refresh(hass, http, seeded, entry, ROWS)
    assert hass.states.get(first.entity_id).state == "on"
    assert {e.unique_id: e.id for e in checkpoints(hass, entry)} == identities
    assert len(http.requests) == 7


async def test_later_first_checkpoint_when_setup_has_none(hass, http, seeded):
    entry = await setup_airport(hass, http, [])
    assert checkpoints(hass, entry) == []
    await refresh(hass, http, seeded, entry, ROWS)
    assert len(checkpoints(hass, entry)) == 3
    assert len(http.requests) == 2
