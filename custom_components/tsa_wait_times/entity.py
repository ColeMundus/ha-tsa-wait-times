"""Shared service identity."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WaitCoordinator
from .client import BASE_URL
from .const import DOMAIN


class TSAEntity(CoordinatorEntity[WaitCoordinator]):
    """Stable airport-derived entity identity and service-prefixed defaults."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WaitCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        airport = coordinator.airport
        self.key = key
        self._attr_unique_id = f"{airport.code}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, airport.code)},
            name=f"TSA Wait Times {airport.code}",
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="TayTech / TSAWaitTimes.com",
            configuration_url=BASE_URL + airport.path,
        )

    @property
    def suggested_object_id(self) -> str:
        return self.key
