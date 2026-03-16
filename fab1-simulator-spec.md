# FAB1 Factory Simulator — Claude Code Implementation Spec

## 1. Project Overview

### What Is This?
A discrete-event factory simulation with a visual 2D top-down interface for Reframe's FAB1 modular housing factory. The simulator models the full production pipeline from raw material receiving through finished module exit, allowing users to adjust station counts, crew sizes, cycle times, layout positions, and process variability to evaluate throughput, labor efficiency, and bottleneck sensitivity.

### Why Build It?
Reframe is planning FAB1, an expansion facility targeting 1,000 → 2,000 → 4,000 SF/week throughput ramp over 180 days. The team is currently making layout, staffing, and equipment decisions using a mix of Figma layouts, spreadsheet calculators, Notion docs, and meeting-room intuition. This simulator unifies those inputs into a single internally-consistent model that handles stochastic variability — something spreadsheets can't do well.

### Design Philosophy
This tool should embody the FAB1 Commission Tenets:
- **Design for Density**: The simulator should make density/movement tradeoffs visible and quantifiable
- **Creativity Before Capital**: Help the team evaluate cheap-but-creative solutions vs. expensive ones
- **Bias-for-Action**: Ship a useful V1 fast; don't over-engineer

### Tech Stack
- **Backend/Simulation Engine**: Python 3.11+, using `simpy` for discrete-event simulation
- **Frontend**: React + TypeScript served via a local dev server
- **Visualization**: HTML5 Canvas (2D top-down factory view) + Recharts (dashboard charts)
- **Data Format**: JSON config files for factory scenarios
- **Communication**: REST API (FastAPI) between simulation engine and frontend

---

## 2. Core Concepts: Materials, Entities, Resources, and Stations

### 2.1 Terminology — What's What

The simulation deals with four distinct types of objects. Getting this right is critical to the whole model.

**Materials** are raw or intermediate physical goods that flow through the factory and are consumed or transformed by stations. They have a `material_type`, quantity, and physical properties. Materials are what move on carts, get cut, get assembled.

**Entities** are the tracked units of production — the things we care about completing. A **Panel** and a **Module** are entities. Entities are composed of materials and pass through a defined sequence of stations. Entities have lifecycle tracking (created_at, current_station, history).

**Resources** are shared, capacity-limited assets that stations or movement operations need to borrow. A gantry crane, a forklift, the tugger — these are resources. They cause contention when multiple stations need them simultaneously. Resources are NOT consumed; they are occupied temporarily and then released.

**Stations** are fixed locations where work happens. Each station has defined **input material/entity types** (what it consumes or receives), **output material/entity types** (what it produces or releases), a cycle time distribution, a crew requirement, a physical position, and a CAPEX cost. Stations may require one or more **resources** to operate.

```
Material (flows, gets consumed/transformed)
    ↓ feeds into
Station (fixed location, does work, has CAPEX cost)
    ↓ produces
Entity or Material (output of the station)
    ↑ borrows during operation
Resource (shared, capacity-limited, causes contention)
```

### 2.2 Material Types

| Material Type | Unit | Source | Storage Method | Notes |
|---|---|---|---|---|
| `raw_lumber` | board-feet | Dock door delivery | **Material carts** near saw | Arrives as bundles on delivery trucks |
| `raw_sheet_goods` | sheets | Dock door delivery | **Material carts** near CNC | OSB, Zip, drywall |
| `cut_lumber` | cut pieces | Saw output | **Material carts** near framing tables | **0.5-day buffer capacity** |
| `cut_sheets` | cut pieces | CNC output | **Material carts** near framing tables | **0.5-day buffer capacity** |
| `insulation` | batts/rolls | Dock door delivery | Floor storage / carts | Used in finishing |
| `drywall_sheets` | sheets | Dock door delivery | Material carts | Used in finishing |
| `mep_rough_materials` | kits | Kitting area | Material carts | Electrical, plumbing rough-in kits |
| `trim_materials` | kits | Kitting area | Material carts | Interior finish materials |
| `fasteners` | boxes | Storage area | Shelving | Nails, screws, staples |
| `lvl_beams` | pieces | Dock door delivery | **Material carts** / floor storage | LVLs for floor cassettes |
| `tji_joists` | pieces | Dock door delivery | **Material carts** / floor storage | TJIs for floor cassettes |

### 2.3 Entity Types

Entities are the tracked production units that flow through the factory pipeline.

| Entity Type | Composed Of | Dimensions | Key Properties |
|---|---|---|---|
| `Panel` | cut_lumber + cut_sheets (+ optional insulation, drywall, window) | Varies (~4'×8' to 4'×10') | `panel_type` (wall/ceiling), `is_enclosed` (bool), `module_ref` |
| `FloorCassette` | lvl_beams + tji_joists + cut_sheets | ~13.5' × 54' for CCW | `module_ref` |
| `IntegratedModule` | 1 FloorCassette + ~40 Panels | 13.5' × 54' | `module_ref`, `weight_tons` |
| `FinishedModule` | 1 IntegratedModule + finishing materials | 13.5' × 54' | `module_ref`, `weight_tons` (~15-25 tons) |

### 2.4 Resource Types

Resources are shared, non-consumed, capacity-limited assets.

| Resource | Default Count | Used By | Contention Notes |
|---|---|---|---|
| `gantry_crane_module_matrix` | 1-2 per FC bay, 2 per integration bay | Floor cassette, integration, panel lifting | Biggest real bottleneck source |
| `forklift` | 1-2 | Material receiving, lumber/sheet cart loading, general transport | Heavy contention at shift start |
| `tugger` | 1 | Module movement: integration → finishing → exit | ~15 min per move + setup |
| `panel_cart` | 4-8 | Moving panels from framing area to integration staging | Can be a constraint if not enough carts |
| `field_lift_pro` | 2-4 | Lifting modules for caster install, module positioning | |
| `scissor_lift` | 2-4 | Elevated work in integration and finishing | |
| `wav` | 1-2 | Work Assist Vehicle for elevated access | |

---

## 3. Station Definitions

Each station type has a complete definition including inputs, outputs, costs, and operating parameters. **Every station must declare its input and output types** — this is how the simulation engine knows what flows where.

### 3.1 Station Schema

```python
class StationDefinition:
    station_type: str
    display_name: str
    
    # What this station consumes and produces
    input_types: list[MaterialOrEntityType]   # what it needs to start work
    output_types: list[MaterialOrEntityType]   # what it produces when done
    
    # Operating parameters
    cycle_time_distribution: Distribution
    crew_size: int
    crew_skill_factor: float  # 0.7 (new hire) to 1.2 (expert), multiplier on cycle time
    
    # Resources required during operation
    required_resources: list[ResourceRequirement]  # e.g., [("gantry_crane", 1)]
    
    # Reliability
    breakdown_rate: float     # mean time between failures (hours), 0 = never breaks
    repair_time_distribution: Distribution
    
    # Physical properties
    position: tuple[float, float]  # (x, y) in factory coordinates (feet)
    footprint: tuple[float, float] # (width, depth) in feet
    
    # Cost
    capex_cost: float         # $ equipment purchase cost
    install_cost: float       # $ installation/commissioning cost
    monthly_maintenance: float # $ estimated monthly maintenance
```

### 3.2 Station Type Definitions

| Station Type | Inputs | Outputs | Default Count (D1/D90/D180) | Cycle Time | Crew | CAPEX (per unit) | Footprint | Required Resources |
|---|---|---|---|---|---|---|---|---|
| **`hundegger_saw`** | `raw_lumber` | `cut_lumber` | 0/0/1 (Nov delivery) | Continuous: ~30 cuts/hr | 1-2 | $800K (used Hundegger SC3) | 10'×60' | Compressed air |
| **`easy_frame_saw`** | `raw_lumber` | `cut_lumber` | 1/1/0 (replaced by Hundegger) | Continuous: ~20 cuts/hr | 1-2 | $150K | 10'×40' | Compressed air |
| **`onsrud_cnc`** | `raw_sheet_goods` | `cut_sheets` | 1/1/1 | Continuous: ~8 sheets/hr | 1 | $250K | 15'×30' | Vacuum pump, dust collector, compressed air, jib crane |
| **`manual_framing_table`** | `cut_lumber`, `cut_sheets` | `Panel` | 2/4/4 | LogNormal(μ=82min, σ=18min) | 2-3 | $15K (table + jig) | 20'×60' | None (self-contained) |
| **`acadia_workcell`** | `cut_lumber`, `cut_sheets` | `Panel` | 0/0/1 | Normal(μ=60min, σ=10min) | 1-2 | $500K+ | 25'×65' | Compressed air, reinforced slab |
| **`floor_cassette_bay`** | `lvl_beams`, `tji_joists`, `cut_sheets` | `FloorCassette` | 1/2/2-3 | Normal(μ=480min, σ=60min) [1 shift] | 3-4 | $50K (jig + tooling) | 20'×60' | `gantry_crane_module_matrix` ×1 |
| **`integration_bay`** | `FloorCassette` + `Panel` (×~40) | `IntegratedModule` | 1/2/3 | Normal(μ=960min, σ=120min) [2 shifts] | 4-6 | $60K (crane + tooling) | 20'×60' | `gantry_crane_module_matrix` ×2 |
| **`finishing_bay`** | `IntegratedModule` + finishing materials | `FinishedModule` | 3/6/11-12 | Normal(μ=4320min, σ=480min) [9 prod. days] | 2-3 (varies by trade) | $10K (tooling per bay) | 20'×60' | `scissor_lift` or `wav` (intermittent) |
| **`kitting_area`** | Various raw materials | Material kits | 1/1/1 | Parallel to production | 1-2 | $20K (shelving, wire cutter, etc.) | 30'×30' | None |
| **`module_exit`** | `FinishedModule` | (leaves factory) | 1/1/1 | ~30min (tugger to yard) | 1-2 | N/A | 20'×60' (exit lane) | `tugger`, `field_lift_pro` |

### 3.3 Finishing Bay Model — IMPORTANT

The finishing bays do NOT use a push cadence. The model is simpler:

**After integration, a module occupies 1 finishing bay for 9 production days (1.8 calendar weeks), then exits.**

The number of finishing bays is the direct constraint on throughput at this stage. At steady state for 4,000 SF/week:
- Need ~5.6 modules/week (at 715 SF each)
- Each module occupies a bay for 9 days = 1.8 weeks
- Need ~5.6 × 1.8 = ~10-11 bays minimum (plus buffer for variability)

This is why the Day 180 plan calls for 11-12 finishing bays.

### 3.4 Scheduler Integration Interface

Reframe has an existing production scheduling tool ("Sidekick" / the scheduler) that provides more granular task-by-task resource allocation within finishing bays. The simulator should provide a clean integration point for this.

**Abstraction approach — Finishing Bay Schedule Provider:**

```python
class FinishingBayScheduleProvider(Protocol):
    """Interface for providing detailed finishing bay schedules.
    
    The default implementation uses the simple 9-day-per-bay model.
    An advanced implementation can import data from the external
    scheduling tool to provide trade-by-trade, day-by-day task 
    breakdowns within each finishing bay.
    """
    
    def get_bay_duration(self, module: IntegratedModule) -> Distribution:
        """Return the total time a module will occupy a finishing bay."""
        ...
    
    def get_daily_crew_requirements(
        self, module: IntegratedModule, day_in_bay: int
    ) -> dict[str, int]:
        """Return crew requirements by trade for a given day.
        
        Returns e.g.: {"electrician": 2, "plumber": 1, "carpenter": 3}
        This enables the simulator to model labor contention across
        multiple finishing bays competing for the same trade crews.
        """
        ...
    
    def get_resource_requirements(
        self, module: IntegratedModule, day_in_bay: int
    ) -> list[str]:
        """Return shared resources needed on a given day.
        
        Returns e.g.: ["scissor_lift", "wav"]
        """
        ...


class SimpleFinishingModel(FinishingBayScheduleProvider):
    """Default: 9 production days, flat crew of 2-3 per bay."""
    
    def get_bay_duration(self, module):
        return Normal(mean=4320, std=480)  # 9 days in minutes
    
    def get_daily_crew_requirements(self, module, day_in_bay):
        return {"general_finisher": 3}
    
    def get_resource_requirements(self, module, day_in_bay):
        if day_in_bay in [1, 2]:  # MEP rough
            return ["scissor_lift"]
        return []


class SchedulerImportModel(FinishingBayScheduleProvider):
    """Advanced: imports from external scheduling tool.
    
    Reads a JSON/CSV export from the Reframe production scheduler 
    that specifies per-module, per-day task allocations.
    
    Expected input format (JSON):
    {
        "module_type": "CCW",
        "finishing_schedule": [
            {
                "day": 1,
                "tasks": ["MEP rough-in"],
                "crew": {"electrician": 2, "plumber": 1},
                "resources": ["scissor_lift"],
                "duration_hours": 9
            },
            {
                "day": 2,
                "tasks": ["MEP rough-in continued", "insulation prep"],
                "crew": {"electrician": 1, "plumber": 1, "insulator": 2},
                "resources": ["scissor_lift"],
                "duration_hours": 9
            },
            ...
        ]
    }
    
    This format can be exported from the scheduling tool or 
    manually defined. The simulator uses it to:
    1. Model trade-specific labor contention across bays
    2. Identify which trades are bottlenecks (e.g., not enough 
       electricians to staff 6 bays simultaneously)
    3. Model resource contention (e.g., 3 bays need scissor 
       lifts but only 2 exist)
    """
    
    def __init__(self, schedule_path: str):
        self.schedule = load_schedule(schedule_path)
    
    def get_bay_duration(self, module):
        total_days = len(self.schedule["finishing_schedule"])
        return Fixed(total_days * 540)  # days × minutes per shift
    
    def get_daily_crew_requirements(self, module, day_in_bay):
        if day_in_bay < len(self.schedule["finishing_schedule"]):
            return self.schedule["finishing_schedule"][day_in_bay]["crew"]
        return {}
    
    def get_resource_requirements(self, module, day_in_bay):
        if day_in_bay < len(self.schedule["finishing_schedule"]):
            return self.schedule["finishing_schedule"][day_in_bay]["resources"]
        return []
```

The key insight: the simulator doesn't need to replicate the scheduling tool's logic. It just needs to consume its output (a per-day breakdown of crew and resource needs per module) and use that to model contention across multiple bays. The simulator adds the stochastic variability layer and the cross-bay resource competition that the scheduler doesn't model.

---

## 4. Production Pipeline — Material and Entity Flow

### 4.1 Complete Flow with Input/Output Types

```
RECEIVING (Dock Doors)
  ├── raw_lumber (bundles on delivery trucks)
  │     → stored on MATERIAL CARTS near saw
  │     → [easy_frame_saw] or [hundegger_saw]
  │           Inputs:  raw_lumber
  │           Outputs: cut_lumber
  │           → stored on MATERIAL CARTS (0.5-day buffer)
  │
  └── raw_sheet_goods (pallets)
        → stored on MATERIAL CARTS near CNC
        → [onsrud_cnc]
              Inputs:  raw_sheet_goods
              Outputs: cut_sheets
              → stored on MATERIAL CARTS (0.5-day buffer)

PANEL PRODUCTION
  [manual_framing_table] or [acadia_workcell]
      Inputs:  cut_lumber, cut_sheets
      Outputs: Panel (entity)
      → Panels stored in PANEL BUFFER (0.5-1.5 day capacity)
        transported via panel_cart resource

FLOOR CASSETTE PRODUCTION (parallel to panels)
  [floor_cassette_bay]
      Inputs:  lvl_beams, tji_joists, cut_sheets
      Outputs: FloorCassette (entity)
      Resources: gantry_crane_module_matrix
      → FloorCassette staged in FC BUFFER (0-1 unit)

INTEGRATION (waits for BOTH FloorCassette AND ~40 Panels)
  [integration_bay]
      Inputs:  FloorCassette (×1), Panel (×~40)
      Outputs: IntegratedModule (entity)
      Resources: gantry_crane_module_matrix (×2)

FINISHING (9 production days per module per bay)
  [finishing_bay]
      Inputs:  IntegratedModule, finishing materials (from kitting)
      Outputs: FinishedModule (entity)
      Resources: scissor_lift/wav (intermittent, per scheduler)
      Movement: tugger + casters to move module into bay

MODULE EXIT
  [module_exit]
      Inputs:  FinishedModule
      Outputs: (exits factory to yard)
      Resources: tugger, field_lift_pro
```

### 4.2 Buffer Definitions

| Buffer | Between | Storage Method | Default Capacity | Notes |
|---|---|---|---|---|
| **Cut Lumber Staging** | Saw → Framing Tables | **Material carts** | **0.5 production days** (~4 hrs of cut output) | Small buffer — carts, not racking |
| **Cut Sheet Staging** | CNC → Framing Tables | **Material carts** | **0.5 production days** (~4 hrs of cut output) | Small buffer — carts, not racking |
| **Panel Buffer** | Framing Tables → Integration | Panel carts / floor staging | 0.5-1.5 days of panels (configurable) | Actively debated by team |
| **Floor Cassette Staging** | FC Bay → Integration | Floor (in-place) | 0-1 cassettes | Small footprint |
| **Module Staging (pre-finish)** | Integration → Finishing | Floor (on casters) | 0-1 modules | Only if no bay available |
| **Module Yard** | Finishing → Shipping | Outdoor on mod cribs | 4-8 modules | Post-production storage |

---

## 5. Simulation Engine Spec

### 5.1 Core Architecture

Use `simpy` (Python discrete-event simulation library).

```python
class Factory:
    env: simpy.Environment
    stations: dict[str, list[Station]]
    buffers: dict[str, Buffer]
    resources: dict[str, simpy.Resource]
    material_sources: list[MaterialSource]
    metrics: MetricsCollector
    config: FactoryConfig
    finishing_model: FinishingBayScheduleProvider

class Station:
    definition: StationDefinition    # from Section 3
    current_entity: Entity | None
    state: StationState              # ACTIVE, IDLE, BLOCKED, STARVED, BROKEN
    metrics: StationMetrics

class Buffer:
    buffer_type: str
    capacity: int                    # max units (materials or entities)
    storage_method: str              # "material_cart", "panel_cart", "floor"
    current_contents: list[Material | Entity]
    position: tuple[float, float]

class Material:
    material_type: str               # from Section 2.2
    quantity: float
    unit: str
    created_at: float
    
class Entity:
    entity_type: str                 # Panel, FloorCassette, IntegratedModule, FinishedModule
    created_at: float
    completed_at: float | None
    current_station: Station | None
    module_ref: str                  # which module this entity belongs to
    composed_of: list[Material | Entity]  # what went into making this
    history: list[tuple[float, str, str]]  # (time, station_id, event)
```

### 5.2 Simulation Loop

Each production day = 1 shift = 9 hours (configurable).

The simulation models:

1. **Material arrival**: Lumber and sheet goods arrive at dock doors on a schedule (daily or 2x/week)
2. **Saw/CNC processing**: Continuous feed; output goes to cut material buffers (material carts, 0.5-day capacity)
3. **Panel production**: Workers at framing tables pull from cut material carts, produce panels with stochastic cycle times
4. **Floor cassette production**: Parallel to panel production; pulls from cut lumber and LVLs
5. **Integration**: Waits for BOTH a completed floor cassette AND enough panels (~40 per module), then integrates over 2 production days
6. **Finishing**: Module enters a finishing bay and occupies it for 9 production days. Crew and resource requirements per day come from the FinishingBayScheduleProvider.
7. **Module exit**: Finished modules move to yard via tugger

Key behaviors to model:
- **Blocking**: If a downstream buffer is full, the upstream station is blocked (cannot release its output)
- **Starvation**: If an upstream buffer is empty, the downstream station is idle
- **Resource contention**: If a shared resource (crane, forklift) is in use, requesters queue
- **Equipment breakdown**: Stations can fail stochastically; repair takes time
- **Crew availability**: Crews can be absent (absenteeism rate), reducing effective station count
- **Material movement time**: Time to move entities between stations is a function of distance
- **Trade contention** (via scheduler integration): Multiple finishing bays competing for limited electricians, plumbers, etc.

### 5.3 Movement Model

Material movement time between two stations:

```python
def movement_time(from_pos, to_pos, movement_type):
    distance = euclidean_distance(from_pos, to_pos)
    speeds = {
        "forklift":     {"speed_fps": 5, "setup_sec": 120},  # loading material carts
        "tugger":       {"speed_fps": 2, "setup_sec": 600},  # caster install + hookup for modules
        "panel_cart":   {"speed_fps": 3, "setup_sec": 60},   # manual push
        "material_cart":{"speed_fps": 3, "setup_sec": 30},   # lighter than panel carts
        "crane":        {"speed_fps": 1, "setup_sec": 180},  # overhead traverse + rigging
        "walk":         {"speed_fps": 4, "setup_sec": 0},    # crew walking
    }
    s = speeds[movement_type]
    return s["setup_sec"] + (distance / s["speed_fps"])
```

### 5.4 Cycle Time Distributions

```python
CYCLE_TIME_DEFAULTS = {
    "manual_framing_table": {
        "distribution": "lognormal",
        "mean_minutes": 82,
        "std_minutes": 18,
        "min_minutes": 45,
        "max_minutes": 180,
    },
    "acadia_workcell": {
        "distribution": "normal",
        "mean_minutes": 60,
        "std_minutes": 10,
    },
    "floor_cassette": {
        "distribution": "normal",
        "mean_minutes": 480,  # 1 shift
        "std_minutes": 60,
    },
    "integration": {
        "distribution": "normal",
        "mean_minutes": 960,  # 2 shifts
        "std_minutes": 120,
    },
    "finishing_bay": {
        "distribution": "normal",
        "mean_minutes": 4320,  # 9 production days × 480 min/day
        "std_minutes": 480,    # ~1 day of variability
    },
    "easy_frame_saw": {
        "distribution": "fixed_rate",
        "units_per_hour": 20,
    },
    "hundegger_saw": {
        "distribution": "fixed_rate",
        "units_per_hour": 30,
    },
    "onsrud_cnc": {
        "distribution": "fixed_rate",
        "units_per_hour": 8,
    },
}
```

### 5.5 Ramp Plan Model

```python
RAMP_PLAN = {
    "day_1": {
        "easy_frame_saw": 1,
        "hundegger_saw": 0,
        "onsrud_cnc": 1,
        "manual_framing_tables": 2,
        "acadia_workcells": 0,
        "floor_cassette_bays": 1,
        "integration_bays": 1,
        "finishing_bays": 3,
        "target_sf_per_week": 1000,
        "total_headcount_estimate": 25,
    },
    "day_90": {
        "easy_frame_saw": 1,
        "hundegger_saw": 0,
        "onsrud_cnc": 1,
        "manual_framing_tables": 4,
        "acadia_workcells": 0,
        "floor_cassette_bays": 2,
        "integration_bays": 2,
        "finishing_bays": 6,
        "target_sf_per_week": 2000,
        "total_headcount_estimate": 45,
    },
    "day_180": {
        "easy_frame_saw": 0,
        "hundegger_saw": 1,
        "onsrud_cnc": 1,
        "manual_framing_tables": 4,
        "acadia_workcells": 1,
        "floor_cassette_bays": 3,  # desired: 2 at 1.5-shift CT
        "integration_bays": 3,
        "finishing_bays": 12,
        "target_sf_per_week": 4000,
        "total_headcount_estimate": 70,
    },
}
```

### 5.6 CAPEX Summary (auto-calculated from station config)

The simulator should compute total CAPEX from station definitions:

```python
def compute_capex(config: FactoryConfig) -> dict:
    """Sum CAPEX across all stations for a given configuration."""
    total = 0
    breakdown = {}
    for station_type, count in config.station_counts.items():
        unit_cost = STATION_DEFINITIONS[station_type].capex_cost
        install = STATION_DEFINITIONS[station_type].install_cost
        line_total = count * (unit_cost + install)
        breakdown[station_type] = {
            "count": count,
            "unit_capex": unit_cost,
            "install_cost": install,
            "line_total": line_total,
        }
        total += line_total
    # Add shared resources CAPEX
    breakdown["shared_resources"] = {
        "gantry_cranes": config.resource_counts["gantry_crane"] * 25_000,
        "forklift": config.resource_counts["forklift"] * 35_000,
        "tugger": config.resource_counts["tugger"] * 25_000,
        "field_lift_pros": config.resource_counts["field_lift_pro"] * 15_000,
        "scissor_lifts": config.resource_counts["scissor_lift"] * 8_000,
        "panel_carts": config.resource_counts["panel_cart"] * 2_000,
        "material_carts": config.resource_counts["material_cart"] * 500,
    }
    return {"total": total, "breakdown": breakdown}
```

### 5.7 Output Metrics

**Throughput Metrics**
- Modules completed per week (distribution over N runs)
- SF produced per week (modules × 715 SF for CCW)
- Probability of hitting target at each ramp phase

**Efficiency Metrics**
- Station utilization (% time: active / idle / blocked / starved / broken) per station
- Labor utilization (% time workers are productive vs waiting vs moving materials)
- SF per labor-hour

**Bottleneck Metrics**
- Most frequently starved station
- Most frequently blocked station
- Longest queue at each buffer (avg and p95)

**Material Movement Metrics**
- Total forklift-hours per week
- Total tugger moves per week
- Average material travel distance per module produced
- Movement heat map (which paths are most traveled)

**Financial Metrics**
- Total CAPEX by configuration (auto-summed from station definitions)
- Labor cost per SF (headcount × hourly rate / SF produced)
- Cost per module
- CAPEX per SF/week of capacity

---

## 6. Frontend Spec

### 6.1 Two-Panel Layout

**Left Panel: 2D Factory Floor View (Canvas)**
- Top-down view of the factory floor at scale
- Station blocks are colored rectangles with labels, positioned at (x, y) coordinates
- **Material carts** shown as small rectangles near their parent stations with fill indicators
- Entities (panels, modules) are small colored dots/rectangles that move between stations
- Buffer zones shown as shaded areas with fill-level indicators
- Material flow paths drawn as lines connecting stations
- Color-coding: green = active, yellow = idle/starved, red = blocked/broken, gray = off
- **Drag and drop** station repositioning (updates movement distances in real-time)
- Hover over any station to see: current metrics, input/output types, CAPEX cost, crew assignment

**Right Panel: Dashboard + Controls**
- **Control Bar** (top):
  - Play / Pause / Step simulation
  - Speed slider (1x, 5x, 20x, 100x)
  - Run count for Monte Carlo (default: 100 runs)
  - "Run Batch" button (runs N simulations headless)
  - Ramp phase selector: Day 1 / Day 90 / Day 180 / Custom
- **Parameter Panels** (collapsible accordion sections):
  - Station Counts (sliders per station type, shows per-unit CAPEX next to each)
  - Crew Sizes (sliders per station type)
  - Cycle Times (mean + std sliders per station type)
  - Buffer Capacities (sliders, storage method labels)
  - Resource Counts (sliders for shared resources)
  - Equipment Breakdown rates (sliders)
  - Shift Configuration (hours per shift, shifts per day)
  - Module Type selector (CCW 715 SF, or custom dimensions)
  - Finishing Model selector: Simple (9-day) / Import from Scheduler
- **CAPEX Summary** (persistent sidebar widget):
  - Total CAPEX for current configuration
  - Breakdown by station type and resources
  - Updates in real-time as user adjusts station counts
- **Results Dashboard** (bottom):
  - Throughput histogram (from batch runs)
  - Station utilization bar chart
  - Bottleneck identification table
  - SF/labor-hour trend
  - CAPEX efficiency: $/SF/week of throughput

### 6.2 Factory Floor Coordinate System

```
Factory dimensions: ~400 ft × 275 ft (configurable per facility)

Default station positions (approximate, draggable):
- Dock Doors: top edge (y=0), x=50 to x=200
- Lumber Material Carts: (50, 30)
- Sheet Material Carts: (150, 30)
- EasyFrame Saw: (80, 60)
- Onsrud CNC: (160, 60)
- Cut Lumber Carts (0.5-day buffer): (90, 90)
- Cut Sheet Carts (0.5-day buffer): (170, 90)
- Manual Framing Tables: (100, 120) to (200, 120), spaced 30ft apart
- Acadia Workcell: (250, 120)
- Panel Buffer: (180, 160)
- Floor Cassette Bays: (60, 180)
- Integration Bays: (100, 200) to (160, 200), spaced 60ft apart
- Finishing Bays: (60, 250) to (350, 250), arranged in 2 lanes
- Module Exit: bottom edge (y=275), x=200
```

### 6.3 Visual Simulation Playback

When running in visual mode (not batch):
- Entities appear at material sources and move along paths between stations
- Movement speed is proportional to the movement model
- Stations pulse/glow when actively working
- Stations turn red when broken down
- Buffer zones (including material carts) fill/empty visually
- Simulation clock shows current day/hour
- Station labels show real-time metrics

### 6.4 Scenario Management

- Save/load factory configurations as named JSON scenarios
- Compare two scenarios side-by-side
- Export results as CSV
- Ramp plan visualization (Day 1 → 90 → 180 metrics trajectory)
- Movement heatmap overlay on factory floor
- **CAPEX comparison** between scenarios

---

## 7. Default Scenario: CCW (Cape Cod Walkup)

```json
{
  "scenario_name": "CCW Baseline",
  "module_type": {
    "name": "CCW Module",
    "width_ft": 13.5,
    "length_ft": 54,
    "sf": 715,
    "panels_per_module": 40,
    "weight_tons": 15
  },
  "facility": {
    "width_ft": 400,
    "depth_ft": 275,
    "usable_production_sf": 65000
  },
  "shift": {
    "hours_per_shift": 9,
    "shifts_per_day": 1,
    "production_days_per_week": 5
  },
  "buffers": {
    "cut_lumber": {"capacity_days": 0.5, "storage_method": "material_cart"},
    "cut_sheets": {"capacity_days": 0.5, "storage_method": "material_cart"},
    "panel_buffer": {"capacity_days": 1.0, "storage_method": "panel_cart"},
    "floor_cassette": {"capacity_units": 1, "storage_method": "floor"},
    "module_staging": {"capacity_units": 1, "storage_method": "floor"},
    "module_yard": {"capacity_units": 8, "storage_method": "mod_cribs"}
  },
  "finishing_model": "simple",
  "finishing_schedule_path": null,
  "absenteeism_rate": 0.08,
  "equipment_breakdown": {
    "easy_frame_mtbf_hours": 200,
    "easy_frame_repair_hours": 4,
    "cnc_mtbf_hours": 300,
    "cnc_repair_hours": 6,
    "crane_mtbf_hours": 500,
    "crane_repair_hours": 2,
    "forklift_mtbf_hours": 400,
    "forklift_repair_hours": 1
  }
}
```

---

## 8. API Endpoints

```
POST /api/simulate/batch
  Body: { config: FactoryConfig, num_runs: int, ramp_phase: string }
  Returns: { throughput_distribution, utilization_by_station, bottlenecks, 
             summary_stats, capex_summary }

POST /api/simulate/stream
  Body: { config: FactoryConfig }
  Returns: WebSocket stream of simulation events:
    { time, event_type, entity_id, entity_type, station_id, details }

GET /api/scenarios
GET /api/scenarios/{name}
POST /api/scenarios/{name}

GET /api/defaults/{ramp_phase}
  Returns: default FactoryConfig for day_1 / day_90 / day_180

GET /api/capex/{ramp_phase}
  Returns: CAPEX breakdown for a ramp phase configuration

POST /api/finishing-schedule/validate
  Body: { schedule_json }
  Returns: validation result for imported scheduler data
```

---

## 9. Implementation Plan for Claude Code

### Phase 1: Simulation Engine (Days 1-2)

1. Set up project structure (see below)
2. Implement Material, Entity, Resource, Station, Buffer classes with input/output type declarations
3. Implement the production pipeline with correct material → station → entity flow
4. Implement the movement model with distance-based transport times
5. Implement cycle time distributions with stochastic variability
6. Implement CAPEX calculation from station definitions
7. Implement SimpleFinishingModel (9 days per bay)
8. Implement metrics collection
9. Verify: run 100 headless simulations of Day 1, print throughput distribution + CAPEX

### Phase 2: Frontend — Dashboard + Controls (Days 2-3)

1. Scaffold React + TypeScript app with Vite
2. Build ParameterPanel with all configurable parameters, CAPEX shown per station
3. Build CAPEX summary sidebar
4. Build ResultsDashboard with throughput histogram, utilization chart, bottleneck table
5. Wire to backend via REST API

### Phase 3: Factory Floor Visualization (Days 3-4)

1. Build FactoryCanvas (HTML5 Canvas) with stations, material carts, buffers
2. Add drag-and-drop station repositioning
3. Implement visual simulation playback with entity movement
4. Add hover tooltips showing station inputs/outputs/CAPEX/metrics

### Phase 4: Polish + Scheduler Integration (Day 4-5)

1. Implement SchedulerImportModel for finishing bay detail
2. Add finishing schedule JSON import UI
3. Save/load scenarios, side-by-side comparison
4. CSV export, movement heatmap, ramp plan visualization

### Project Structure

```
fab1-simulator/
├── backend/
│   ├── main.py                    # FastAPI server
│   ├── simulation/
│   │   ├── engine.py              # Core simpy simulation loop
│   │   ├── stations.py            # Station classes with input/output types + CAPEX
│   │   ├── entities.py            # Panel, FloorCassette, Module classes
│   │   ├── materials.py           # Material types and tracking
│   │   ├── buffers.py             # Buffer management (incl. material cart buffers)
│   │   ├── resources.py           # Shared resources (cranes, forklifts, tugger)
│   │   ├── movement.py            # Distance-based movement time calculations
│   │   ├── metrics.py             # Metrics collection and aggregation
│   │   ├── distributions.py       # Cycle time distributions
│   │   ├── capex.py               # CAPEX calculation from station configs
│   │   └── finishing_models.py    # SimpleFinishingModel + SchedulerImportModel
│   ├── config/
│   │   ├── defaults.py            # Default parameters with CAPEX
│   │   ├── station_definitions.py # All station types with I/O + costs
│   │   └── scenarios/
│   │       └── ccw_baseline.json
│   └── api/
│       ├── routes.py
│       └── schemas.py             # Pydantic models
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── FactoryCanvas.tsx
│   │   │   ├── ControlPanel.tsx
│   │   │   ├── ParameterPanel.tsx
│   │   │   ├── CapexSummary.tsx
│   │   │   ├── ResultsDashboard.tsx
│   │   │   ├── StationTooltip.tsx
│   │   │   └── FinishingScheduleImport.tsx
│   │   ├── hooks/
│   │   │   ├── useSimulation.ts
│   │   │   └── useFactoryLayout.ts
│   │   └── types/
│   │       └── factory.ts
│   └── package.json
├── scheduler_templates/
│   └── ccw_finishing_schedule.json  # Example finishing schedule import
├── requirements.txt
└── README.md
```

---

## 10. What Success Looks Like

### Minimum Viable Simulator (must-have for V1)
- [ ] Headless simulation with stochastic cycle times and throughput distributions
- [ ] All station types modeled with declared input/output material and entity types
- [ ] Material carts as storage for cut lumber and cut sheets (0.5-day buffer)
- [ ] Buffer capacity constraints cause blocking/starvation
- [ ] Finishing bays model: 1 module occupies 1 bay for 9 production days
- [ ] CAPEX auto-calculated from station definitions, shown in UI
- [ ] Parameter sliders for all variables
- [ ] Results dashboard: throughput histogram, utilization, bottlenecks, CAPEX summary
- [ ] Batch mode: 100+ simulations with probability of hitting targets
- [ ] 2D factory floor with station layout

### Nice-to-Have for V1
- [ ] Visual playback with entity movement
- [ ] Drag-and-drop station repositioning
- [ ] Equipment breakdown modeling
- [ ] Ramp plan interpolation (full 180-day trajectory)
- [ ] Scenario save/load/compare
- [ ] Finishing schedule import from external scheduler

### V2 (Future)
- [ ] Live integration with scheduling tool API (not just JSON import)
- [ ] Import actual cycle time data from PostgreSQL RDS factory data stack
- [ ] Multi-module-type support (CCW + future project types)
- [ ] Optimization mode: find best layout given constraints
- [ ] Series B demo mode with polished visuals

---

## 11. Critical Domain Constraints

1. **Panel → Integration synchronization**: Integration cannot start until BOTH a floor cassette AND ~40 panels are ready. This coupling is the most critical dependency.

2. **Finishing = 9 days, 1 bay**: Each module occupies one finishing bay for 9 production days. The number of bays is a hard throughput constraint.

3. **Shared crane contention**: Gantry cranes serve floor cassette, integration, AND panel lifting. Real bottleneck the spreadsheet misses.

4. **Module movement is slow**: 55' module via tugger + casters = ~15 min per move + setup. Blocks aisle traffic.

5. **Cut material on carts, not racks**: Both cut lumber and cut sheets are stored on material carts with only 0.5-day buffer. This means the saw/CNC must run nearly continuously to avoid starving framing tables.

6. **Crew skill ramp**: Day 1 crews will be slower than Day 90 crews. Model a learning curve factor (e.g., 1.3× cycle time at Day 1, improving to 1.0× by Day 60).

---

## 12. Notes for Claude Code Agent

- Use `simpy` 4.x for simulation. Use `FastAPI` + `uvicorn` for backend. Use `pydantic` for config validation.
- Use `numpy` for random distributions. Seed RNG for reproducibility.
- Frontend: Vite + React + TypeScript. `recharts` for charts. Raw HTML5 Canvas for 2D floor.
- **Every station MUST declare input_types and output_types.** The engine should validate that the production graph is connected and all inputs have sources.
- **Every station MUST have a capex_cost field.** The UI should show CAPEX next to every station count slider.
- Materials and entities are distinct: materials are consumed/transformed, entities are tracked production units with lifecycle history.
- Resources are borrowed, not consumed. They cause contention via simpy.Resource queuing.
- The finishing bay model defaults to SimpleFinishingModel (9 days). The SchedulerImportModel reads a JSON file with per-day trade and resource requirements.
- All default parameters should be grounded in the domain data from this spec so the simulator is immediately useful without manual configuration.
- The factory coordinate system is in feet, (0,0) at top-left, Y increases downward.
