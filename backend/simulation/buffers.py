"""Buffer management for material and entity staging areas."""

from dataclasses import dataclass, field
from typing import Any
import simpy


@dataclass
class BufferConfig:
    name: str
    capacity: int  # max units
    storage_method: str  # material_cart, panel_cart, floor, mod_cribs
    position: tuple[float, float] = (0.0, 0.0)


class Buffer:
    """A capacity-limited staging area between stations.

    Uses a simpy.Store so that put() blocks when full (causing upstream blocking)
    and get() blocks when empty (causing downstream starvation).
    """

    def __init__(self, env: simpy.Environment, config: BufferConfig):
        self.env = env
        self.name = config.name
        self.capacity = config.capacity
        self.storage_method = config.storage_method
        self.position = config.position
        self.store = simpy.Store(env, capacity=config.capacity)
        # Metrics
        self.total_put = 0
        self.total_get = 0
        self.max_level = 0
        self.level_history: list[tuple[float, int]] = []

    @property
    def level(self) -> int:
        return len(self.store.items)

    def put(self, item: Any) -> simpy.events.Event:
        """Put an item into the buffer. Blocks if full."""
        self.total_put += 1
        self._record_level()
        return self.store.put(item)

    def get(self) -> simpy.events.Event:
        """Get an item from the buffer. Blocks if empty."""
        self.total_get += 1
        self._record_level()
        return self.store.get()

    def _record_level(self):
        level = self.level
        if level > self.max_level:
            self.max_level = level
        self.level_history.append((self.env.now, level))

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "current_level": self.level,
            "max_level": self.max_level,
            "total_throughput": self.total_get,
        }
