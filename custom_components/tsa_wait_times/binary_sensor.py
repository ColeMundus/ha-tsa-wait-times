"""TSA PreCheck availability and the website's checkpoint status list."""

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TSAConfigEntry
from .entity import TSAEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TSAConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            PrecheckSensor(
                entry.runtime_data, "precheck_available", "TSA PreCheck available"
            )
        ]
    )


class PrecheckSensor(TSAEntity, BinarySensorEntity):
    """On means the website reports PreCheck available, not a measured wait."""

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.precheck is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.precheck

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "checkpoints": list(self.coordinator.data.checkpoints),
            "fetched_at": self.coordinator.data.fetched_at.isoformat(),
        }
