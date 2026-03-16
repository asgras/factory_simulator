"""Metrics collection and aggregation for simulation runs."""

from dataclasses import dataclass, field
from enum import Enum
import numpy as np


class StationState(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    BLOCKED = "blocked"
    STARVED = "starved"
    BROKEN = "broken"


@dataclass
class StationMetrics:
    station_id: str
    station_type: str
    time_active: float = 0.0
    time_idle: float = 0.0
    time_blocked: float = 0.0
    time_starved: float = 0.0
    time_broken: float = 0.0
    units_produced: int = 0
    state_history: list[tuple[float, str]] = field(default_factory=list)

    def record_state(self, time: float, state: StationState):
        self.state_history.append((time, state.value))

    @property
    def total_time(self) -> float:
        return self.time_active + self.time_idle + self.time_blocked + self.time_starved + self.time_broken

    @property
    def utilization(self) -> float:
        if self.total_time == 0:
            return 0.0
        return self.time_active / self.total_time


@dataclass
class SimulationResult:
    """Results from a single simulation run."""
    modules_completed: int = 0
    panels_completed: int = 0
    floor_cassettes_completed: int = 0
    sf_produced: float = 0.0
    sim_duration_minutes: float = 0.0
    station_metrics: dict[str, StationMetrics] = field(default_factory=dict)
    buffer_stats: dict[str, dict] = field(default_factory=dict)
    resource_stats: dict[str, dict] = field(default_factory=dict)
    module_completion_times: list[float] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


@dataclass
class BatchResult:
    """Aggregated results from multiple simulation runs."""
    num_runs: int = 0
    results: list[SimulationResult] = field(default_factory=list)

    @property
    def throughput_per_week(self) -> list[float]:
        """Modules per week for each run."""
        out = []
        for r in self.results:
            if r.sim_duration_minutes > 0:
                weeks = r.sim_duration_minutes / (5 * 9 * 60)  # 5 days, 9 hrs
                out.append(r.modules_completed / weeks if weeks > 0 else 0)
            else:
                out.append(0)
        return out

    @property
    def sf_per_week(self) -> list[float]:
        out = []
        for r in self.results:
            if r.sim_duration_minutes > 0:
                weeks = r.sim_duration_minutes / (5 * 9 * 60)
                out.append(r.sf_produced / weeks if weeks > 0 else 0)
            else:
                out.append(0)
        return out

    def summary(self) -> dict:
        tp = self.throughput_per_week
        sf = self.sf_per_week
        if not tp:
            return {}
        tp_arr = np.array(tp)
        sf_arr = np.array(sf)
        return {
            "num_runs": self.num_runs,
            "modules_per_week": {
                "mean": float(np.mean(tp_arr)),
                "std": float(np.std(tp_arr)),
                "p5": float(np.percentile(tp_arr, 5)),
                "p50": float(np.percentile(tp_arr, 50)),
                "p95": float(np.percentile(tp_arr, 95)),
                "min": float(np.min(tp_arr)),
                "max": float(np.max(tp_arr)),
            },
            "sf_per_week": {
                "mean": float(np.mean(sf_arr)),
                "std": float(np.std(sf_arr)),
                "p5": float(np.percentile(sf_arr, 5)),
                "p50": float(np.percentile(sf_arr, 50)),
                "p95": float(np.percentile(sf_arr, 95)),
            },
            "avg_station_utilization": self._avg_utilization(),
        }

    def _avg_utilization(self) -> dict[str, float]:
        """Average utilization across all runs per station type."""
        if not self.results:
            return {}
        util_by_type: dict[str, list[float]] = {}
        for r in self.results:
            for sid, sm in r.station_metrics.items():
                stype = sm.station_type
                if stype not in util_by_type:
                    util_by_type[stype] = []
                util_by_type[stype].append(sm.utilization)
        return {k: float(np.mean(v)) for k, v in util_by_type.items()}
