"""FastAPI routes for the factory simulator."""

import json
import os
from fastapi import APIRouter, HTTPException

from .schemas import (
    SimulateRequest, BatchResponse, SingleRunResult,
    CapexResponse, ScenarioModel,
)
from ..simulation.engine import Factory, FactoryConfig, run_batch
from ..simulation.capex import compute_capex
from ..config.station_definitions import STATION_DEFINITIONS, DEFAULT_RESOURCES
from ..config.defaults import RAMP_PLAN, DEFAULT_MODULE, DEFAULT_SHIFT, DEFAULT_BUFFERS

router = APIRouter()

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "scenarios")


def _build_config(req: SimulateRequest, seed: int = 42) -> FactoryConfig:
    """Convert API request model into a FactoryConfig."""
    # If ramp_phase is set, use those defaults
    if req.ramp_phase and req.ramp_phase in RAMP_PLAN:
        plan = RAMP_PLAN[req.ramp_phase]
        station_counts = plan["station_counts"]
        resource_counts = DEFAULT_RESOURCES[req.ramp_phase]
        skill_factor = plan["crew_skill_factor"]
    else:
        station_counts = req.station_counts.model_dump()
        resource_counts = req.resource_counts.model_dump()
        skill_factor = req.crew_skill_factor

    buffer_configs = DEFAULT_BUFFERS
    if req.buffer_configs:
        buffer_configs = {k: v.model_dump() for k, v in req.buffer_configs.items()}

    return FactoryConfig(
        station_counts=station_counts,
        resource_counts=resource_counts,
        station_defs=STATION_DEFINITIONS,
        buffer_configs=buffer_configs,
        module_config=req.module_config.model_dump(),
        shift_config=req.shift_config.model_dump(),
        crew_skill_factor=skill_factor,
        absenteeism_rate=req.absenteeism_rate,
        sim_duration_days=req.sim_duration_days,
        seed=seed,
    )


@router.post("/simulate/batch", response_model=BatchResponse)
def simulate_batch(req: SimulateRequest):
    """Run batch simulations and return aggregate results."""
    config = _build_config(req)
    batch = run_batch(config, num_runs=req.num_runs, base_seed=42)
    summary = batch.summary()

    # Compute CAPEX
    if req.ramp_phase and req.ramp_phase in RAMP_PLAN:
        station_counts = RAMP_PLAN[req.ramp_phase]["station_counts"]
        resource_counts = DEFAULT_RESOURCES[req.ramp_phase]
    else:
        station_counts = req.station_counts.model_dump()
        resource_counts = req.resource_counts.model_dump()

    capex = compute_capex(station_counts, STATION_DEFINITIONS, resource_counts)

    # Build individual run summaries (first 10 only to keep response small)
    individual = []
    for r in batch.results[:10]:
        metrics = {}
        for sid, sm in r.station_metrics.items():
            metrics[sid] = {
                "station_type": sm.station_type,
                "utilization": sm.utilization,
                "units_produced": sm.units_produced,
                "time_active": sm.time_active,
                "time_idle": sm.time_idle,
                "time_blocked": sm.time_blocked,
                "time_starved": sm.time_starved,
            }
        individual.append(SingleRunResult(
            modules_completed=r.modules_completed,
            panels_completed=r.panels_completed,
            floor_cassettes_completed=r.floor_cassettes_completed,
            sf_produced=r.sf_produced,
            station_metrics=metrics,
            buffer_stats=r.buffer_stats,
            resource_stats=r.resource_stats,
        ))

    return BatchResponse(
        summary=summary,
        capex=capex,
        individual_runs=individual,
        throughput_per_week=batch.throughput_per_week,
        sf_per_week=batch.sf_per_week,
    )


@router.post("/simulate/single", response_model=SingleRunResult)
def simulate_single(req: SimulateRequest):
    """Run a single simulation and return detailed results."""
    config = _build_config(req)
    factory = Factory(config)
    r = factory.run()

    metrics = {}
    for sid, sm in r.station_metrics.items():
        metrics[sid] = {
            "station_type": sm.station_type,
            "utilization": sm.utilization,
            "units_produced": sm.units_produced,
            "time_active": sm.time_active,
            "time_idle": sm.time_idle,
            "time_blocked": sm.time_blocked,
            "time_starved": sm.time_starved,
        }

    return SingleRunResult(
        modules_completed=r.modules_completed,
        panels_completed=r.panels_completed,
        floor_cassettes_completed=r.floor_cassettes_completed,
        sf_produced=r.sf_produced,
        station_metrics=metrics,
        buffer_stats=r.buffer_stats,
        resource_stats=r.resource_stats,
    )


@router.get("/defaults/{ramp_phase}")
def get_defaults(ramp_phase: str):
    """Get default configuration for a ramp phase."""
    if ramp_phase not in RAMP_PLAN:
        raise HTTPException(404, f"Unknown ramp phase: {ramp_phase}")
    plan = RAMP_PLAN[ramp_phase]
    resources = DEFAULT_RESOURCES[ramp_phase]
    return {
        "station_counts": plan["station_counts"],
        "resource_counts": resources,
        "target_sf_per_week": plan["target_sf_per_week"],
        "crew_skill_factor": plan["crew_skill_factor"],
        "total_headcount_estimate": plan["total_headcount_estimate"],
        "module_config": DEFAULT_MODULE,
        "shift_config": DEFAULT_SHIFT,
        "buffer_configs": DEFAULT_BUFFERS,
    }


@router.get("/capex/{ramp_phase}", response_model=CapexResponse)
def get_capex(ramp_phase: str):
    """Get CAPEX breakdown for a ramp phase."""
    if ramp_phase not in RAMP_PLAN:
        raise HTTPException(404, f"Unknown ramp phase: {ramp_phase}")
    plan = RAMP_PLAN[ramp_phase]
    resources = DEFAULT_RESOURCES[ramp_phase]
    result = compute_capex(plan["station_counts"], STATION_DEFINITIONS, resources)
    return CapexResponse(**result)


@router.get("/station-definitions")
def get_station_definitions():
    """Get all station type definitions (for frontend display)."""
    defs = {}
    for stype, sdef in STATION_DEFINITIONS.items():
        defs[stype] = {
            "display_name": sdef["display_name"],
            "input_types": sdef["input_types"],
            "output_types": sdef["output_types"],
            "crew_size": sdef["crew_size"],
            "capex_cost": sdef["capex_cost"],
            "install_cost": sdef["install_cost"],
            "footprint": sdef["footprint"],
            "default_position": sdef["default_position"],
        }
    return defs


@router.get("/scenarios")
def list_scenarios():
    """List saved scenarios."""
    os.makedirs(SCENARIOS_DIR, exist_ok=True)
    files = [f.replace(".json", "") for f in os.listdir(SCENARIOS_DIR) if f.endswith(".json")]
    return {"scenarios": files}


@router.get("/scenarios/{name}")
def get_scenario(name: str):
    """Load a saved scenario."""
    path = os.path.join(SCENARIOS_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise HTTPException(404, f"Scenario not found: {name}")
    with open(path) as f:
        return json.load(f)


@router.post("/scenarios/{name}")
def save_scenario(name: str, scenario: ScenarioModel):
    """Save a scenario."""
    os.makedirs(SCENARIOS_DIR, exist_ok=True)
    path = os.path.join(SCENARIOS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(scenario.model_dump(), f, indent=2)
    return {"status": "saved", "name": name}
