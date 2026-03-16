"""Shared resources that stations borrow during operations."""

from dataclasses import dataclass
import simpy


@dataclass
class ResourceConfig:
    name: str
    capacity: int  # how many of this resource exist
    capex_per_unit: float = 0.0


class TrackedResource:
    """A simpy.Resource wrapper that tracks utilization metrics."""

    def __init__(self, env: simpy.Environment, config: ResourceConfig):
        self.env = env
        self.name = config.name
        self.capacity = config.capacity
        self.capex_per_unit = config.capex_per_unit
        self.resource = simpy.Resource(env, capacity=config.capacity)
        # Metrics
        self.total_requests = 0
        self.total_wait_time = 0.0
        self.max_queue_length = 0
        self.queue_history: list[tuple[float, int]] = []

    def request(self) -> simpy.resources.resource.Request:
        self.total_requests += 1
        queue_len = len(self.resource.queue)
        if queue_len > self.max_queue_length:
            self.max_queue_length = queue_len
        self.queue_history.append((self.env.now, queue_len))
        return self.resource.request()

    def release(self, req: simpy.resources.resource.Request):
        self.resource.release(req)

    @property
    def in_use(self) -> int:
        return self.resource.count

    @property
    def queue_length(self) -> int:
        return len(self.resource.queue)

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "total_requests": self.total_requests,
            "max_queue_length": self.max_queue_length,
            "total_capex": self.capacity * self.capex_per_unit,
        }
