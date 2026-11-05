"""Airport display wait minutes."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TSAConfigEntry
from .const import COUNTERS
from .entity import TSAEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TSAConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        WaitSensor(entry.runtime_data, key, f"{name} wait")
        for key, name in COUNTERS.items()
    )


class WaitSensor(TSAEntity, SensorEntity):
    """Unknown/closed waits are unavailable, not zero."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.waits[self.key] is not None

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.waits[self.key]
