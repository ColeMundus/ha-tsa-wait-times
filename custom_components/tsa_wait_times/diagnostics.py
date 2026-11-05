"""Allowlisted diagnostics; no raw feed, URLs or schedule details."""

from typing import Any

from homeassistant.core import HomeAssistant

from . import TSAConfigEntry
from .const import CONF_INTERVAL, DEFAULT_INTERVAL


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TSAConfigEntry
) -> dict[str, Any]:
    return {
        "airport": "PDX",
        "poll_minutes": entry.options.get(
            CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        ),
        "last_update_success": entry.runtime_data.last_update_success,
        "source_observation_timestamp_available": False,
    }
