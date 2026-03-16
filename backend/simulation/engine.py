"""Core SimPy simulation engine for the FAB1 factory."""

import simpy
import numpy as np
from typing import Any

from .materials import Material, MaterialType
from .entities import Entity, EntityType
from .buffers import Buffer, BufferConfig
from .resources import TrackedResource, ResourceConfig
from .movement import movement_time_minutes
from .metrics import StationMetrics, StationState, SimulationResult, BatchResult
from .finishing_models import SimpleFinishingModel
from .capex import compute_capex


class FactoryConfig:
    """Full configuration for a factory simulation run."""

    def __init__(
        self,
        station_counts: dict[str, int],
        resource_counts: dict[str, int],
        station_defs: dict[str, dict],
        buffer_configs: dict[str, dict],
        module_config: dict,
        shift_config: dict,
        crew_skill_factor: float = 1.0,
        absenteeism_rate: float = 0.08,
        breakdown_config: dict | None = None,
        finishing_model: Any = None,
        sim_duration_days: int = 30,
        seed: int | None = None,
    ):
        self.station_counts = station_counts
        self.resource_counts = resource_counts
        self.station_defs = station_defs
        self.buffer_configs = buffer_configs
        self.module_config = module_config
        self.shift_config = shift_config
        self.crew_skill_factor = crew_skill_factor
        self.absenteeism_rate = absenteeism_rate
        self.breakdown_config = breakdown_config or {}
        self.finishing_model = finishing_model or SimpleFinishingModel()
        self.sim_duration_days = sim_duration_days
        self.seed = seed

    @property
    def minutes_per_shift(self) -> float:
        return self.shift_config["hours_per_shift"] * 60

    @property
    def total_sim_minutes(self) -> float:
        return self.sim_duration_days * self.minutes_per_shift

    @property
    def panels_per_module(self) -> int:
        return self.module_config["panels_per_module"]

    @property
    def sf_per_module(self) -> float:
        return self.module_config["sf"]


class Factory:
    """The main simulation orchestrator."""

    def __init__(self, config: FactoryConfig):
        self.config = config
        self.rng = np.random.default_rng(config.seed)
        self.env = simpy.Environment()
        self.result = SimulationResult()

        # Counters for unique IDs
        self._panel_counter = 0
        self._fc_counter = 0
        self._module_counter = 0

        # Set up shared resources
        self.resources: dict[str, TrackedResource] = {}
        for res_name, count in config.resource_counts.items():
            if count > 0:
                from .capex import RESOURCE_CAPEX
                self.resources[res_name] = TrackedResource(
                    self.env,
                    ResourceConfig(res_name, count, RESOURCE_CAPEX.get(res_name, 0))
                )

        # Set up buffers
        self.buffers: dict[str, Buffer] = {}
        for buf_name, buf_cfg in config.buffer_configs.items():
            self.buffers[buf_name] = Buffer(
                self.env,
                BufferConfig(
                    name=buf_name,
                    capacity=buf_cfg["capacity"],
                    storage_method=buf_cfg["storage_method"],
                    position=tuple(buf_cfg.get("position", (0, 0))),
                )
            )

        # Station metrics tracking
        self.station_metrics: dict[str, StationMetrics] = {}

        # Set up raw material sources (unlimited for now — materials arrive as needed)
        self.raw_lumber = simpy.Container(self.env, capacity=10000, init=5000)
        self.raw_sheets = simpy.Container(self.env, capacity=10000, init=5000)
        self.lvl_beams = simpy.Container(self.env, capacity=10000, init=5000)
        self.tji_joists = simpy.Container(self.env, capacity=10000, init=5000)

    def _next_panel_id(self) -> str:
        self._panel_counter += 1
        return f"panel-{self._panel_counter}"

    def _next_fc_id(self) -> str:
        self._fc_counter += 1
        return f"fc-{self._fc_counter}"

    def _next_module_ref(self) -> str:
        self._module_counter += 1
        return f"mod-{self._module_counter}"

    def _get_station_metric(self, station_id: str, station_type: str) -> StationMetrics:
        if station_id not in self.station_metrics:
            self.station_metrics[station_id] = StationMetrics(station_id, station_type)
        return self.station_metrics[station_id]

    def _apply_skill_factor(self, base_time: float) -> float:
        """Apply crew skill factor to cycle time."""
        return base_time * self.config.crew_skill_factor

    def _check_absenteeism(self) -> bool:
        """Returns True if a worker is absent (station should skip this shift)."""
        return self.rng.random() < self.config.absenteeism_rate

    def _acquire_resources(self, requirements: list[tuple[str, int]]) -> list[tuple[str, Any]]:
        """Build list of resource requests needed. Returns list of (name, request) pairs."""
        requests = []
        for res_name, count in requirements:
            if res_name in self.resources:
                for _ in range(count):
                    req = self.resources[res_name].request()
                    requests.append((res_name, req))
        return requests

    def _release_resources(self, held: list[tuple[str, Any]]):
        """Release all held resource requests."""
        for res_name, req in held:
            if res_name in self.resources:
                self.resources[res_name].release(req)

    # ─── Station Processes ───────────────────────────────────────────

    def _saw_process(self, station_id: str, station_type: str):
        """Saw station: converts raw_lumber → cut_lumber continuously."""
        sdef = self.config.station_defs[station_type]
        metric = self._get_station_metric(station_id, station_type)
        cut_lumber_buf = self.buffers["cut_lumber"]

        while True:
            # Check absenteeism at start of each cycle
            if self._check_absenteeism():
                metric.time_idle += 60  # skip an hour
                metric.record_state(self.env.now, StationState.IDLE)
                yield self.env.timeout(60)
                continue

            # Get raw lumber
            start_wait = self.env.now
            yield self.raw_lumber.get(1)
            wait_time = self.env.now - start_wait
            if wait_time > 0:
                metric.time_starved += wait_time

            # Process
            cycle_time = sdef["cycle_time"].sample(self.rng)
            cycle_time = self._apply_skill_factor(cycle_time)
            metric.record_state(self.env.now, StationState.ACTIVE)
            yield self.env.timeout(cycle_time)
            metric.time_active += cycle_time

            # Output to buffer (blocks if full)
            start_block = self.env.now
            yield cut_lumber_buf.put(Material(MaterialType.CUT_LUMBER, 1, self.env.now))
            block_time = self.env.now - start_block
            if block_time > 0:
                metric.time_blocked += block_time
                metric.record_state(self.env.now, StationState.BLOCKED)

            metric.units_produced += 1

    def _cnc_process(self, station_id: str):
        """CNC station: converts raw_sheet_goods → cut_sheets continuously."""
        sdef = self.config.station_defs["onsrud_cnc"]
        metric = self._get_station_metric(station_id, "onsrud_cnc")
        cut_sheets_buf = self.buffers["cut_sheets"]

        while True:
            if self._check_absenteeism():
                metric.time_idle += 60
                metric.record_state(self.env.now, StationState.IDLE)
                yield self.env.timeout(60)
                continue

            start_wait = self.env.now
            yield self.raw_sheets.get(1)
            wait_time = self.env.now - start_wait
            if wait_time > 0:
                metric.time_starved += wait_time

            cycle_time = sdef["cycle_time"].sample(self.rng)
            cycle_time = self._apply_skill_factor(cycle_time)
            metric.record_state(self.env.now, StationState.ACTIVE)
            yield self.env.timeout(cycle_time)
            metric.time_active += cycle_time

            start_block = self.env.now
            yield cut_sheets_buf.put(Material(MaterialType.CUT_SHEETS, 1, self.env.now))
            block_time = self.env.now - start_block
            if block_time > 0:
                metric.time_blocked += block_time

            metric.units_produced += 1

    def _framing_table_process(self, station_id: str, station_type: str):
        """Framing table: consumes cut_lumber + cut_sheets → produces Panel."""
        sdef = self.config.station_defs[station_type]
        metric = self._get_station_metric(station_id, station_type)
        cut_lumber_buf = self.buffers["cut_lumber"]
        cut_sheets_buf = self.buffers["cut_sheets"]
        panel_buf = self.buffers["panel_buffer"]

        while True:
            if self._check_absenteeism():
                metric.time_idle += 60
                yield self.env.timeout(60)
                continue

            # Need both cut lumber and cut sheets to make a panel
            start_wait = self.env.now
            lumber = yield cut_lumber_buf.get()
            sheets = yield cut_sheets_buf.get()
            wait_time = self.env.now - start_wait
            if wait_time > 0:
                metric.time_starved += wait_time
                metric.record_state(self.env.now, StationState.STARVED)

            # Process
            cycle_time = sdef["cycle_time"].sample(self.rng)
            cycle_time = self._apply_skill_factor(cycle_time)
            metric.record_state(self.env.now, StationState.ACTIVE)
            yield self.env.timeout(cycle_time)
            metric.time_active += cycle_time

            # Produce panel
            panel = Entity(
                entity_type=EntityType.PANEL,
                id=self._next_panel_id(),
                module_ref="",  # assigned at integration
                created_at=self.env.now,
                composed_of=[lumber, sheets],
            )
            panel.add_history(self.env.now, station_id, "produced")

            # Output to panel buffer (blocks if full)
            start_block = self.env.now
            yield panel_buf.put(panel)
            block_time = self.env.now - start_block
            if block_time > 0:
                metric.time_blocked += block_time

            metric.units_produced += 1
            self.result.panels_completed += 1

    def _floor_cassette_process(self, station_id: str):
        """Floor cassette bay: produces FloorCassette from raw materials."""
        sdef = self.config.station_defs["floor_cassette_bay"]
        metric = self._get_station_metric(station_id, "floor_cassette_bay")
        fc_buf = self.buffers["floor_cassette"]
        resource_reqs = sdef["required_resources"]

        while True:
            if self._check_absenteeism():
                metric.time_idle += 60
                yield self.env.timeout(60)
                continue

            # Get raw materials
            start_wait = self.env.now
            yield self.lvl_beams.get(1)
            yield self.tji_joists.get(1)
            # Also need some cut sheets
            sheets = yield self.buffers["cut_sheets"].get()
            wait_time = self.env.now - start_wait
            if wait_time > 0:
                metric.time_starved += wait_time

            # Acquire crane resource
            held_resources = self._acquire_resources(resource_reqs)
            for _, req in held_resources:
                yield req

            cycle_time = sdef["cycle_time"].sample(self.rng)
            cycle_time = self._apply_skill_factor(cycle_time)
            metric.record_state(self.env.now, StationState.ACTIVE)
            yield self.env.timeout(cycle_time)
            metric.time_active += cycle_time

            # Release crane
            self._release_resources(held_resources)

            fc = Entity(
                entity_type=EntityType.FLOOR_CASSETTE,
                id=self._next_fc_id(),
                module_ref="",
                created_at=self.env.now,
            )
            fc.add_history(self.env.now, station_id, "produced")

            start_block = self.env.now
            yield fc_buf.put(fc)
            block_time = self.env.now - start_block
            if block_time > 0:
                metric.time_blocked += block_time

            metric.units_produced += 1
            self.result.floor_cassettes_completed += 1

    def _integration_process(self, station_id: str):
        """Integration bay: waits for 1 FloorCassette + N Panels → IntegratedModule."""
        sdef = self.config.station_defs["integration_bay"]
        metric = self._get_station_metric(station_id, "integration_bay")
        fc_buf = self.buffers["floor_cassette"]
        panel_buf = self.buffers["panel_buffer"]
        staging_buf = self.buffers["module_staging"]
        resource_reqs = sdef["required_resources"]
        panels_needed = self.config.panels_per_module

        while True:
            if self._check_absenteeism():
                metric.time_idle += 60
                yield self.env.timeout(60)
                continue

            # Wait for a floor cassette
            start_wait = self.env.now
            fc = yield fc_buf.get()
            # Wait for enough panels
            panels = []
            for _ in range(panels_needed):
                p = yield panel_buf.get()
                panels.append(p)
            wait_time = self.env.now - start_wait
            if wait_time > 0:
                metric.time_starved += wait_time
                metric.record_state(self.env.now, StationState.STARVED)

            module_ref = self._next_module_ref()

            # Acquire cranes
            held_resources = self._acquire_resources(resource_reqs)
            for _, req in held_resources:
                yield req

            # Movement time: panels from buffer to integration bay
            move_time = movement_time_minutes(
                panel_buf.position,
                tuple(sdef["default_position"]),
                "panel_cart"
            )
            yield self.env.timeout(move_time)

            cycle_time = sdef["cycle_time"].sample(self.rng)
            cycle_time = self._apply_skill_factor(cycle_time)
            metric.record_state(self.env.now, StationState.ACTIVE)
            yield self.env.timeout(cycle_time)
            metric.time_active += cycle_time

            self._release_resources(held_resources)

            integrated = Entity(
                entity_type=EntityType.INTEGRATED_MODULE,
                id=f"intmod-{module_ref}",
                module_ref=module_ref,
                created_at=self.env.now,
                composed_of=[fc] + panels,
            )
            integrated.add_history(self.env.now, station_id, "integrated")

            start_block = self.env.now
            yield staging_buf.put(integrated)
            block_time = self.env.now - start_block
            if block_time > 0:
                metric.time_blocked += block_time

            metric.units_produced += 1

    def _finishing_process(self, station_id: str):
        """Finishing bay: module occupies bay for ~9 production days."""
        metric = self._get_station_metric(station_id, "finishing_bay")
        staging_buf = self.buffers["module_staging"]
        yard_buf = self.buffers["module_yard"]

        while True:
            # Wait for an integrated module
            start_wait = self.env.now
            module = yield staging_buf.get()
            wait_time = self.env.now - start_wait
            if wait_time > 0:
                metric.time_idle += wait_time

            # Movement: tugger moves module into bay
            if "tugger" in self.resources:
                tugger_req = self.resources["tugger"].request()
                yield tugger_req
                yield self.env.timeout(15)  # 15 min tugger move
                self.resources["tugger"].release(tugger_req)

            # Get finishing duration from model
            duration_dist = self.config.finishing_model.get_bay_duration(module)
            finish_time = duration_dist.sample(self.rng)
            finish_time = max(finish_time, 480)  # at least 1 day

            metric.record_state(self.env.now, StationState.ACTIVE)
            yield self.env.timeout(finish_time)
            metric.time_active += finish_time

            # Module is done
            finished = Entity(
                entity_type=EntityType.FINISHED_MODULE,
                id=f"finmod-{module.module_ref}",
                module_ref=module.module_ref,
                created_at=module.created_at,
                completed_at=self.env.now,
                composed_of=[module],
            )
            finished.add_history(self.env.now, station_id, "finished")

            # Move to yard
            start_block = self.env.now
            yield yard_buf.put(finished)
            block_time = self.env.now - start_block
            if block_time > 0:
                metric.time_blocked += block_time

            metric.units_produced += 1
            self.result.modules_completed += 1
            self.result.sf_produced += self.config.sf_per_module
            self.result.module_completion_times.append(self.env.now)

    def _module_exit_process(self):
        """Module exit: pulls finished modules from yard (so yard doesn't fill up)."""
        yard_buf = self.buffers["module_yard"]
        exit_reqs = self.config.station_defs["module_exit"]["required_resources"]

        while True:
            module = yield yard_buf.get()

            held = self._acquire_resources(exit_reqs)
            for _, req in held:
                yield req

            yield self.env.timeout(30)  # 30 min exit process
            self._release_resources(held)

    def _material_delivery_process(self):
        """Periodic material delivery to replenish raw material stores."""
        # Deliver materials daily at start of shift
        while True:
            yield self.env.timeout(self.config.minutes_per_shift)
            # Replenish raw materials to capacity
            lumber_needed = self.raw_lumber.capacity - self.raw_lumber.level
            if lumber_needed > 0:
                yield self.raw_lumber.put(lumber_needed)
            sheets_needed = self.raw_sheets.capacity - self.raw_sheets.level
            if sheets_needed > 0:
                yield self.raw_sheets.put(sheets_needed)
            lvl_needed = self.lvl_beams.capacity - self.lvl_beams.level
            if lvl_needed > 0:
                yield self.lvl_beams.put(lvl_needed)
            tji_needed = self.tji_joists.capacity - self.tji_joists.level
            if tji_needed > 0:
                yield self.tji_joists.put(tji_needed)

    def run(self) -> SimulationResult:
        """Run the simulation and return results."""
        counts = self.config.station_counts

        # Start saw processes
        saw_types = ["easy_frame_saw", "hundegger_saw"]
        for saw_type in saw_types:
            for i in range(counts.get(saw_type, 0)):
                sid = f"{saw_type}_{i}"
                self.env.process(self._saw_process(sid, saw_type))

        # Start CNC processes
        for i in range(counts.get("onsrud_cnc", 0)):
            sid = f"onsrud_cnc_{i}"
            self.env.process(self._cnc_process(sid))

        # Start framing table processes
        for ft_type in ["manual_framing_table", "acadia_workcell"]:
            for i in range(counts.get(ft_type, 0)):
                sid = f"{ft_type}_{i}"
                self.env.process(self._framing_table_process(sid, ft_type))

        # Start floor cassette processes
        for i in range(counts.get("floor_cassette_bay", 0)):
            sid = f"floor_cassette_bay_{i}"
            self.env.process(self._floor_cassette_process(sid))

        # Start integration processes
        for i in range(counts.get("integration_bay", 0)):
            sid = f"integration_bay_{i}"
            self.env.process(self._integration_process(sid))

        # Start finishing processes
        for i in range(counts.get("finishing_bay", 0)):
            sid = f"finishing_bay_{i}"
            self.env.process(self._finishing_process(sid))

        # Start module exit
        if counts.get("module_exit", 0) > 0:
            self.env.process(self._module_exit_process())

        # Start material delivery
        self.env.process(self._material_delivery_process())

        # Run simulation
        self.env.run(until=self.config.total_sim_minutes)

        # Collect results
        self.result.sim_duration_minutes = self.config.total_sim_minutes
        self.result.station_metrics = dict(self.station_metrics)
        for buf_name, buf in self.buffers.items():
            self.result.buffer_stats[buf_name] = buf.get_stats()
        for res_name, res in self.resources.items():
            self.result.resource_stats[res_name] = res.get_stats()

        return self.result


def run_batch(config: FactoryConfig, num_runs: int = 100, base_seed: int = 42) -> BatchResult:
    """Run multiple simulations and aggregate results."""
    batch = BatchResult(num_runs=num_runs)
    for i in range(num_runs):
        cfg = FactoryConfig(
            station_counts=config.station_counts,
            resource_counts=config.resource_counts,
            station_defs=config.station_defs,
            buffer_configs=config.buffer_configs,
            module_config=config.module_config,
            shift_config=config.shift_config,
            crew_skill_factor=config.crew_skill_factor,
            absenteeism_rate=config.absenteeism_rate,
            breakdown_config=config.breakdown_config,
            finishing_model=config.finishing_model,
            sim_duration_days=config.sim_duration_days,
            seed=base_seed + i,
        )
        factory = Factory(cfg)
        result = factory.run()
        batch.results.append(result)
    return batch
