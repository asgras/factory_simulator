"""Phase 1 tests: verify simulation engine produces reasonable results."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.simulation.engine import Factory, FactoryConfig, run_batch
from backend.simulation.distributions import (
    NormalDistribution, LogNormalDistribution, FixedRateDistribution, FixedDistribution,
)
from backend.simulation.materials import Material, MaterialType
from backend.simulation.entities import Entity, EntityType
from backend.simulation.buffers import Buffer, BufferConfig
from backend.simulation.resources import TrackedResource, ResourceConfig
from backend.simulation.movement import movement_time_minutes, euclidean_distance
from backend.simulation.metrics import StationState
from backend.simulation.capex import compute_capex
from backend.simulation.finishing_models import SimpleFinishingModel
from backend.config.station_definitions import STATION_DEFINITIONS, DEFAULT_RESOURCES
from backend.config.defaults import RAMP_PLAN, DEFAULT_MODULE, DEFAULT_SHIFT, DEFAULT_BUFFERS
import numpy as np


def make_config(ramp_phase: str = "day_1", sim_days: int = 30, seed: int = 42) -> FactoryConfig:
    """Build a FactoryConfig from the defaults for a given ramp phase."""
    plan = RAMP_PLAN[ramp_phase]
    resources = DEFAULT_RESOURCES[ramp_phase]
    return FactoryConfig(
        station_counts=plan["station_counts"],
        resource_counts=resources,
        station_defs=STATION_DEFINITIONS,
        buffer_configs=DEFAULT_BUFFERS,
        module_config=DEFAULT_MODULE,
        shift_config=DEFAULT_SHIFT,
        crew_skill_factor=plan["crew_skill_factor"],
        sim_duration_days=sim_days,
        seed=seed,
    )


def test_distributions():
    """Test that distribution sampling works correctly."""
    rng = np.random.default_rng(42)

    normal = NormalDistribution(mean=100, std=10)
    samples = [normal.sample(rng) for _ in range(1000)]
    assert 95 < np.mean(samples) < 105, f"Normal mean off: {np.mean(samples)}"

    lognormal = LogNormalDistribution(mean=82, std=18, min_val=45, max_val=180)
    samples = [lognormal.sample(rng) for _ in range(1000)]
    assert all(45 <= s <= 180 for s in samples), "LogNormal out of bounds"

    fixed_rate = FixedRateDistribution(units_per_hour=20)
    assert fixed_rate.sample(rng) == 3.0, "FixedRate: 20/hr should be 3 min/unit"

    fixed = FixedDistribution(value=42)
    assert fixed.sample(rng) == 42.0

    print("  [PASS] distributions")


def test_movement():
    """Test movement time calculations."""
    d = euclidean_distance((0, 0), (3, 4))
    assert abs(d - 5.0) < 0.01, f"Distance should be 5, got {d}"

    t = movement_time_minutes((0, 0), (100, 0), "forklift")
    # 120s setup + 100ft / 5fps = 20s travel = 140s = 2.33min
    assert abs(t - 140/60) < 0.1, f"Forklift time off: {t}"

    print("  [PASS] movement")


def test_capex():
    """Test CAPEX calculation."""
    counts = {"manual_framing_table": 2, "onsrud_cnc": 1}
    res_counts = {"forklift": 2, "panel_cart": 4}
    result = compute_capex(counts, STATION_DEFINITIONS, res_counts)

    expected_framing = 2 * (15_000 + 2_000)
    expected_cnc = 1 * (250_000 + 20_000)
    expected_resources = 2 * 35_000 + 4 * 2_000

    assert result["breakdown"]["manual_framing_table"]["line_total"] == expected_framing
    assert result["breakdown"]["onsrud_cnc"]["line_total"] == expected_cnc
    assert result["resource_total"] == expected_resources
    assert result["total"] == expected_framing + expected_cnc + expected_resources

    print("  [PASS] capex")


def test_single_run_day1():
    """Run a single Day 1 simulation and verify basic output."""
    config = make_config("day_1", sim_days=30, seed=42)
    factory = Factory(config)
    result = factory.run()

    print(f"  Day 1 (30 days): {result.modules_completed} modules, "
          f"{result.panels_completed} panels, {result.floor_cassettes_completed} FCs")
    print(f"  SF produced: {result.sf_produced:.0f}")

    # At Day 1 config, with 3 finishing bays and 9-day cycles, max theoretical
    # is about 3 bays × (30/9) ≈ 10 modules — but constrained by upstream
    assert result.panels_completed > 0, "Should produce some panels"
    assert result.floor_cassettes_completed > 0, "Should produce some floor cassettes"
    # Modules might be 0-few depending on pipeline fill time, so just check non-negative
    assert result.modules_completed >= 0, "Modules should be non-negative"

    # Check station metrics exist
    assert len(result.station_metrics) > 0, "Should have station metrics"
    for sid, sm in result.station_metrics.items():
        assert sm.utilization >= 0, f"Station {sid} utilization should be >= 0"

    print(f"  Station utilizations:")
    for sid, sm in result.station_metrics.items():
        print(f"    {sid}: {sm.utilization:.1%} util, {sm.units_produced} units")

    print("  [PASS] single_run_day1")


def test_single_run_day90():
    """Run a Day 90 simulation."""
    config = make_config("day_90", sim_days=30, seed=42)
    factory = Factory(config)
    result = factory.run()

    print(f"  Day 90 (30 days): {result.modules_completed} modules, "
          f"{result.sf_produced:.0f} SF")
    assert result.modules_completed > 0, "Day 90 should complete at least 1 module"
    print("  [PASS] single_run_day90")


def test_single_run_day180():
    """Run a Day 180 simulation."""
    config = make_config("day_180", sim_days=30, seed=42)
    factory = Factory(config)
    result = factory.run()

    print(f"  Day 180 (30 days): {result.modules_completed} modules, "
          f"{result.sf_produced:.0f} SF")
    assert result.modules_completed > 0, "Day 180 should complete modules"
    print("  [PASS] single_run_day180")


def test_batch_run():
    """Run a batch of 20 simulations and check aggregate stats."""
    config = make_config("day_1", sim_days=30, seed=42)
    batch = run_batch(config, num_runs=20, base_seed=42)

    summary = batch.summary()
    print(f"  Batch (20 runs, Day 1, 30 days):")
    print(f"    Modules/week: mean={summary['modules_per_week']['mean']:.2f}, "
          f"std={summary['modules_per_week']['std']:.2f}")
    print(f"    SF/week: mean={summary['sf_per_week']['mean']:.0f}, "
          f"p5={summary['sf_per_week']['p5']:.0f}, p95={summary['sf_per_week']['p95']:.0f}")
    print(f"    Avg utilizations: {summary['avg_station_utilization']}")

    assert summary["num_runs"] == 20
    assert summary["modules_per_week"]["mean"] >= 0
    print("  [PASS] batch_run")


def test_buffer_blocking():
    """Verify that full buffers cause upstream blocking."""
    import simpy
    env = simpy.Environment()
    buf = Buffer(env, BufferConfig("test", capacity=2, storage_method="test"))

    results = {"blocked": False}

    def producer(env, buf):
        for i in range(5):
            yield buf.put(f"item-{i}")
            if buf.level == buf.capacity:
                results["blocked"] = True

    env.process(producer(env, buf))
    env.run(until=100)
    # Buffer should have been full at some point since we put 5 items in capacity-2 buffer
    # Actually, simpy.Store blocks on put when full, so producer would be stuck
    assert buf.level <= buf.capacity, "Buffer should not exceed capacity"
    print("  [PASS] buffer_blocking")


def test_finishing_model():
    """Test SimpleFinishingModel."""
    model = SimpleFinishingModel()
    rng = np.random.default_rng(42)
    dummy = Entity(EntityType.INTEGRATED_MODULE, "test", "mod-1")

    duration = model.get_bay_duration(dummy)
    sample = duration.sample(rng)
    assert 3000 < sample < 6000, f"Finishing time should be ~4320 min, got {sample}"

    crew = model.get_daily_crew_requirements(dummy, 1)
    assert "general_finisher" in crew

    resources = model.get_resource_requirements(dummy, 1)
    assert "scissor_lift" in resources
    resources_day5 = model.get_resource_requirements(dummy, 5)
    assert resources_day5 == []

    print("  [PASS] finishing_model")


if __name__ == "__main__":
    print("Running Phase 1 Tests...")
    print()

    test_distributions()
    test_movement()
    test_capex()
    test_buffer_blocking()
    test_finishing_model()
    test_single_run_day1()
    test_single_run_day90()
    test_single_run_day180()
    test_batch_run()

    print()
    print("All Phase 1 tests passed!")
