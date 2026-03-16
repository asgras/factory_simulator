// Core types for the factory simulator frontend

export interface StationCounts {
  easy_frame_saw: number;
  hundegger_saw: number;
  onsrud_cnc: number;
  manual_framing_table: number;
  acadia_workcell: number;
  floor_cassette_bay: number;
  integration_bay: number;
  finishing_bay: number;
  kitting_area: number;
  module_exit: number;
}

export interface ResourceCounts {
  gantry_crane_module_matrix: number;
  forklift: number;
  tugger: number;
  panel_cart: number;
  field_lift_pro: number;
  scissor_lift: number;
  wav: number;
  material_cart: number;
}

export interface ModuleConfig {
  name: string;
  width_ft: number;
  length_ft: number;
  sf: number;
  panels_per_module: number;
  weight_tons: number;
}

export interface ShiftConfig {
  hours_per_shift: number;
  shifts_per_day: number;
  production_days_per_week: number;
}

export interface SimulateRequest {
  station_counts: StationCounts;
  resource_counts: ResourceCounts;
  module_config: ModuleConfig;
  shift_config: ShiftConfig;
  crew_skill_factor: number;
  absenteeism_rate: number;
  sim_duration_days: number;
  num_runs: number;
  ramp_phase: string | null;
}

export interface StationMetric {
  station_type: string;
  utilization: number;
  units_produced: number;
  time_active: number;
  time_idle: number;
  time_blocked: number;
  time_starved: number;
}

export interface DistributionStats {
  mean: number;
  std: number;
  p5: number;
  p50: number;
  p95: number;
  min?: number;
  max?: number;
}

export interface SimulationSummary {
  num_runs: number;
  modules_per_week: DistributionStats;
  sf_per_week: DistributionStats;
  avg_station_utilization: Record<string, number>;
}

export interface CapexBreakdown {
  total: number;
  breakdown: Record<string, {
    count?: number;
    unit_capex?: number;
    install_cost?: number;
    line_total?: number;
  }>;
  resource_total: number;
}

export interface BatchResponse {
  summary: SimulationSummary;
  capex: CapexBreakdown;
  throughput_per_week: number[];
  sf_per_week: number[];
  individual_runs?: {
    modules_completed: number;
    panels_completed: number;
    floor_cassettes_completed: number;
    sf_produced: number;
    station_metrics: Record<string, StationMetric>;
    buffer_stats: Record<string, unknown>;
    resource_stats: Record<string, unknown>;
  }[];
}

export interface StationDefinition {
  display_name: string;
  input_types: string[];
  output_types: string[];
  crew_size: number;
  capex_cost: number;
  install_cost: number;
  footprint: [number, number];
  default_position: [number, number];
}

export interface DefaultsResponse {
  station_counts: StationCounts;
  resource_counts: ResourceCounts;
  target_sf_per_week: number;
  crew_skill_factor: number;
  total_headcount_estimate: number;
  module_config: ModuleConfig;
  shift_config: ShiftConfig;
  buffer_configs: Record<string, unknown>;
}

export type RampPhase = "day_1" | "day_90" | "day_180";

// Display labels for station types
export const STATION_LABELS: Record<string, string> = {
  easy_frame_saw: "EasyFrame Saw",
  hundegger_saw: "Hundegger SC3",
  onsrud_cnc: "Onsrud CNC",
  manual_framing_table: "Framing Table",
  acadia_workcell: "Acadia Workcell",
  floor_cassette_bay: "Floor Cassette Bay",
  integration_bay: "Integration Bay",
  finishing_bay: "Finishing Bay",
  kitting_area: "Kitting Area",
  module_exit: "Module Exit",
};

export const RESOURCE_LABELS: Record<string, string> = {
  gantry_crane_module_matrix: "Gantry Crane",
  forklift: "Forklift",
  tugger: "Tugger",
  panel_cart: "Panel Cart",
  field_lift_pro: "Field Lift Pro",
  scissor_lift: "Scissor Lift",
  wav: "WAV",
  material_cart: "Material Cart",
};
