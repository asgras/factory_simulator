"""Pydantic models for API request/response validation."""

from pydantic import BaseModel, Field
from typing import Any


class StationCountsModel(BaseModel):
    easy_frame_saw: int = 1
    hundegger_saw: int = 0
    onsrud_cnc: int = 1
    manual_framing_table: int = 2
    acadia_workcell: int = 0
    floor_cassette_bay: int = 1
    integration_bay: int = 1
    finishing_bay: int = 3
    kitting_area: int = 1
    module_exit: int = 1


class ResourceCountsModel(BaseModel):
    gantry_crane_module_matrix: int = 2
    forklift: int = 1
    tugger: int = 1
    panel_cart: int = 4
    field_lift_pro: int = 2
    scissor_lift: int = 2
    wav: int = 1
    material_cart: int = 10


class BufferConfigModel(BaseModel):
    capacity: int
    storage_method: str
    position: list[float] = [0, 0]


class ModuleConfigModel(BaseModel):
    name: str = "CCW Module"
    width_ft: float = 13.5
    length_ft: float = 54
    sf: float = 715
    panels_per_module: int = 40
    weight_tons: float = 15


class ShiftConfigModel(BaseModel):
    hours_per_shift: int = 9
    shifts_per_day: int = 1
    production_days_per_week: int = 5


class SimulateRequest(BaseModel):
    station_counts: StationCountsModel = StationCountsModel()
    resource_counts: ResourceCountsModel = ResourceCountsModel()
    buffer_configs: dict[str, BufferConfigModel] | None = None
    module_config: ModuleConfigModel = ModuleConfigModel()
    shift_config: ShiftConfigModel = ShiftConfigModel()
    crew_skill_factor: float = 1.0
    absenteeism_rate: float = 0.08
    sim_duration_days: int = 30
    num_runs: int = 100
    ramp_phase: str | None = None  # if set, overrides station/resource counts


class SimulationSummary(BaseModel):
    num_runs: int
    modules_per_week: dict[str, float]
    sf_per_week: dict[str, float]
    avg_station_utilization: dict[str, float]


class SingleRunResult(BaseModel):
    modules_completed: int
    panels_completed: int
    floor_cassettes_completed: int
    sf_produced: float
    station_metrics: dict[str, Any]
    buffer_stats: dict[str, Any]
    resource_stats: dict[str, Any]


class BatchResponse(BaseModel):
    summary: dict[str, Any]
    capex: dict[str, Any]
    individual_runs: list[SingleRunResult] | None = None
    throughput_per_week: list[float]
    sf_per_week: list[float]


class CapexResponse(BaseModel):
    total: float
    breakdown: dict[str, Any]
    resource_total: float


class ScenarioModel(BaseModel):
    name: str
    config: SimulateRequest
