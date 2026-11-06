"""Allowlisted operational diagnostics; no HTML or configuration dump."""

from typing import Any

from homeassistant.core import HomeAssistant

from . import TSAConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TSAConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "airport": coordinator.airport.code,
        "poll_minutes": coordinator.minutes,
        "last_update_success": coordinator.last_update_success,
        "source": "TSAWaitTimes.com",
        "estimate_type": "modeled",
        "source_observation_timestamp_available": False,
        "fetched_at": coordinator.data.fetched_at.isoformat(),
    }
