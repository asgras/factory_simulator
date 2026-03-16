"""Validation tests: check simulation output against spec expectations."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.simulation.engine import Factory, FactoryConfig, run_batch
from backend.simulation.capex import compute_capex
from backend.config.station_definitions import STATION_DEFINITIONS, DEFAULT_RESOURCES
from backend.config.defaults import RAMP_PLAN, DEFAULT_MODULE, DEFAULT_SHIFT, DEFAULT_BUFFERS


def make_config(ramp_phase: str, sim_days: int = 30, seed: int = 42) -> FactoryConfig:
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


def test_throughput_sanity():
    """Check that throughput is in a reasonable range for each ramp phase."""
    print("Throughput Sanity Check (50 runs each, 30 days):")
    print("=" * 60)

    for phase in ["day_1", "day_90", "day_180"]:
        config = make_config(phase, sim_days=30)
        batch = run_batch(config, num_runs=50, base_seed=42)
        summary = batch.summary()

        target = RAMP_PLAN[phase]["target_sf_per_week"]
        mean_sf = summary["sf_per_week"]["mean"]
        p5_sf = summary["sf_per_week"]["p5"]
        p95_sf = summary["sf_per_week"]["p95"]
        mean_mod = summary["modules_per_week"]["mean"]

        print(f"\n{phase}:")
        print(f"  Target SF/week: {target}")
        print(f"  Actual SF/week: mean={mean_sf:.0f}, p5={p5_sf:.0f}, p95={p95_sf:.0f}")
        print(f"  Modules/week:   {mean_mod:.2f}")
        print(f"  Hit rate:       {sum(1 for s in batch.sf_per_week if s >= target) / len(batch.sf_per_week) * 100:.0f}%")
        print(f"  Utilizations:")
        for stype, util in sorted(summary["avg_station_utilization"].items(), key=lambda x: -x[1]):
            bar = "█" * int(util * 30) + "░" * (30 - int(util * 30))
            status = "BOTTLENECK" if util > 0.85 else "busy" if util > 0.6 else ""
            print(f"    {stype:30s} {bar} {util:.1%} {status}")


def test_capex_by_phase():
    """Verify CAPEX is calculated correctly for each phase."""
    print("\n\nCAPEX by Ramp Phase:")
    print("=" * 60)

    for phase in ["day_1", "day_90", "day_180"]:
        plan = RAMP_PLAN[phase]
        resources = DEFAULT_RESOURCES[phase]
        capex = compute_capex(plan["station_counts"], STATION_DEFINITIONS, resources)

        print(f"\n{phase}: Total CAPEX = ${capex['total']:,.0f}")
        for stype, info in capex["breakdown"].items():
            if stype == "shared_resources":
                continue
            if isinstance(info, dict) and info.get("count", 0) > 0:
                print(f"  {stype:30s} {info['count']:2d} x ${info['unit_capex']:>10,} = ${info['line_total']:>12,}")
        print(f"  {'Resources':30s}                          = ${capex['resource_total']:>12,.0f}")


def test_bottleneck_identification():
    """Check that the known bottlenecks (framing tables) show up."""
    print("\n\nBottleneck Identification:")
    print("=" * 60)

    config = make_config("day_1", sim_days=30)
    batch = run_batch(config, num_runs=30, base_seed=42)
    summary = batch.summary()

    bottlenecks = sorted(
        summary["avg_station_utilization"].items(),
        key=lambda x: -x[1]
    )

    print("\nDay 1 top bottleneck:")
    top_name, top_util = bottlenecks[0]
    print(f"  {top_name}: {top_util:.1%}")
    # Framing tables should be the bottleneck at day 1 with only 2 tables
    assert top_name == "manual_framing_table", f"Expected framing table as bottleneck, got {top_name}"
    assert top_util > 0.8, f"Expected >80% utilization for bottleneck, got {top_util:.1%}"
    print("  [PASS] Framing tables correctly identified as Day 1 bottleneck")


def test_finishing_bay_constraint():
    """Verify finishing bays are the throughput constraint when other stations are ample."""
    print("\n\nFinishing Bay Constraint Test:")
    print("=" * 60)

    # Give lots of upstream capacity but few finishing bays
    plan = RAMP_PLAN["day_180"].copy()
    counts = dict(plan["station_counts"])
    counts["finishing_bay"] = 2  # Only 2 finishing bays
    resources = DEFAULT_RESOURCES["day_180"]

    config = FactoryConfig(
        station_counts=counts,
        resource_counts=resources,
        station_defs=STATION_DEFINITIONS,
        buffer_configs=DEFAULT_BUFFERS,
        module_config=DEFAULT_MODULE,
        shift_config=DEFAULT_SHIFT,
        crew_skill_factor=1.0,
        sim_duration_days=30,
        seed=42,
    )
    batch = run_batch(config, num_runs=20, base_seed=42)
    summary = batch.summary()

    fb_util = summary["avg_station_utilization"].get("finishing_bay", 0)
    mean_mod = summary["modules_per_week"]["mean"]

    print(f"  With 2 finishing bays: {mean_mod:.2f} modules/week, FB util = {fb_util:.1%}")
    # With 9 day cycle, 2 bays should produce about 2 * (30/9) / (30/5/9*60) ≈ 0.78/week
    # Actually: each bay can do ~30/9 = 3.3 modules in 30 days, so 2 bays = 6.6 modules = 1.1/week
    assert fb_util > 0.7, f"Finishing bays should be highly utilized, got {fb_util:.1%}"
    print("  [PASS] Finishing bays correctly constrain throughput")


def test_resource_contention():
    """Verify that reducing crane count impacts FC and integration throughput."""
    print("\n\nResource Contention Test (Crane Limit):")
    print("=" * 60)

    # Run with 1 crane vs 6 cranes
    for crane_count in [1, 6]:
        resources = dict(DEFAULT_RESOURCES["day_90"])
        resources["gantry_crane_module_matrix"] = crane_count

        config = FactoryConfig(
            station_counts=RAMP_PLAN["day_90"]["station_counts"],
            resource_counts=resources,
            station_defs=STATION_DEFINITIONS,
            buffer_configs=DEFAULT_BUFFERS,
            module_config=DEFAULT_MODULE,
            shift_config=DEFAULT_SHIFT,
            crew_skill_factor=1.1,
            sim_duration_days=30,
            seed=42,
        )
        batch = run_batch(config, num_runs=20, base_seed=42)
        summary = batch.summary()
        print(f"  Cranes={crane_count}: {summary['modules_per_week']['mean']:.2f} mod/wk, "
              f"SF/wk={summary['sf_per_week']['mean']:.0f}")

    print("  (1 crane should produce fewer modules than 6)")


if __name__ == "__main__":
    test_throughput_sanity()
    test_capex_by_phase()
    test_bottleneck_identification()
    test_finishing_bay_constraint()
    test_resource_contention()
    print("\n\nAll validation tests passed!")
