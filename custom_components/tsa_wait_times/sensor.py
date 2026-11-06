"""Airport-wide current modeled estimate with hourly website estimates."""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TSAConfigEntry
from .client import BASE_URL
from .entity import TSAEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TSAConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [WaitSensor(entry.runtime_data, "estimated_wait", "Estimated wait")]
    )


class WaitSensor(TSAEntity, SensorEntity):
    """Unknown modeled waits are unavailable, not zero."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 1

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.minutes is not None

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.minutes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "source_url": BASE_URL + self.coordinator.airport.path,
            "fetched_at": data.fetched_at.isoformat(),
            "estimate_type": "modeled",
            "hourly_estimates": list(data.hourly),
        }
