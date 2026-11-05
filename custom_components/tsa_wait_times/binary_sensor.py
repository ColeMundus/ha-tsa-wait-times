"""Checkpoint closure indicators."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TSAConfigEntry
from .entity import TSAEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TSAConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ClosedSensor(entry.runtime_data, side, f"{side} checkpoint closed")
        for side in ("North", "South")
    )


class ClosedSensor(TSAEntity, BinarySensorEntity):
    """On means closed as reported by the airport."""

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.closed[self.key]
