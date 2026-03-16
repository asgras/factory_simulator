"""Entity types — tracked production units flowing through the factory."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    PANEL = "Panel"
    FLOOR_CASSETTE = "FloorCassette"
    INTEGRATED_MODULE = "IntegratedModule"
    FINISHED_MODULE = "FinishedModule"


@dataclass
class Entity:
    entity_type: EntityType
    id: str
    module_ref: str  # which module this belongs to
    created_at: float = 0.0
    completed_at: float | None = None
    current_station: str | None = None
    composed_of: list[Any] = field(default_factory=list)
    history: list[tuple[float, str, str]] = field(default_factory=list)  # (time, station_id, event)

    def add_history(self, time: float, station_id: str, event: str):
        self.history.append((time, station_id, event))
