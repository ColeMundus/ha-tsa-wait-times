"""Shared entity identity."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WaitCoordinator
from .const import DOMAIN


class TSAEntity(CoordinatorEntity[WaitCoordinator]):
    """One device, stable provider-derived unique IDs, branded default IDs."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WaitCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"PDX_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "PDX")},
            name="TSA Wait Times PDX",
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Port of Portland",
            configuration_url="https://www.flypdx.com/",
        )

    @property
    def suggested_object_id(self) -> str:
        return self.key.lower()
