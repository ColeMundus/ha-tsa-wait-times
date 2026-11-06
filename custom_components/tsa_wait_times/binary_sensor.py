"""TSA PreCheck availability and individual checkpoint open status."""

import hashlib
import json
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TSAConfigEntry, WaitCoordinator
from .entity import TSAEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TSAConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [PrecheckSensor(coordinator, "precheck_available", "TSA PreCheck available")]
    )
    known: set[tuple[str, str]] = set()

    @callback
    def discover_checkpoints() -> None:
        if not coordinator.active or not coordinator.last_update_success:
            return
        entities = []
        for row in coordinator.data.checkpoints:
            identity = (row["terminal"], row["checkpoint"])
            if identity not in known:
                known.add(identity)
                entities.append(CheckpointSensor(coordinator, *identity))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(discover_checkpoints))
    discover_checkpoints()


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


class CheckpointSensor(TSAEntity, BinarySensorEntity):
    """An exact terminal/checkpoint label pair, never a checkpoint wait estimate."""

    def __init__(
        self, coordinator: WaitCoordinator, terminal: str, checkpoint: str
    ) -> None:
        # The source supplies no checkpoint IDs. Encode both exact labels with
        # unambiguous boundaries; slugification alone loses punctuation/identity.
        identity = json.dumps([terminal, checkpoint], ensure_ascii=True)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        super().__init__(
            coordinator,
            f"checkpoint_{digest}_open",
            f"{terminal} {checkpoint} open".strip(),
        )
        self.terminal = terminal
        self.checkpoint = checkpoint

    @property
    def suggested_object_id(self) -> str:
        return f"{self.terminal}_{self.checkpoint}_open"

    @property
    def status(self) -> str | None:
        for row in self.coordinator.data.checkpoints:
            if (row["terminal"], row["checkpoint"]) == (self.terminal, self.checkpoint):
                return row["status"]
        return None

    @property
    def available(self) -> bool:
        return super().available and self.status in {"Open", "Closed"}

    @property
    def is_on(self) -> bool | None:
        return {"Open": True, "Closed": False}.get(self.status or "")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "terminal": self.terminal,
            "checkpoint": self.checkpoint,
            "status": self.status,
            "fetched_at": self.coordinator.data.fetched_at.isoformat(),
        }
