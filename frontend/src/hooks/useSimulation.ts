import { useState, useCallback } from "react";
import type {
  SimulateRequest,
  BatchResponse,
  DefaultsResponse,
  StationCounts,
  ResourceCounts,
  RampPhase,
  StationDefinition,
} from "../types/factory";

const API_BASE = "http://localhost:8000/api";

export function useSimulation() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<BatchResponse | null>(null);
  const [stationDefs, setStationDefs] = useState<Record<string, StationDefinition> | null>(null);

  const fetchDefaults = useCallback(async (phase: RampPhase): Promise<DefaultsResponse> => {
    const res = await fetch(`${API_BASE}/defaults/${phase}`);
    if (!res.ok) throw new Error(`Failed to fetch defaults: ${res.statusText}`);
    return res.json();
  }, []);

  const fetchStationDefs = useCallback(async () => {
    const res = await fetch(`${API_BASE}/station-definitions`);
    if (!res.ok) throw new Error(`Failed to fetch station definitions`);
    const data = await res.json();
    setStationDefs(data);
    return data;
  }, []);

  const runBatch = useCallback(
    async (req: SimulateRequest) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/simulate/batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(req),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || res.statusText);
        }
        const data: BatchResponse = await res.json();
        setResults(data);
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Unknown error";
        setError(msg);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return {
    loading,
    error,
    results,
    stationDefs,
    fetchDefaults,
    fetchStationDefs,
    runBatch,
  };
}

// Default station counts matching Day 1
export const DEFAULT_STATION_COUNTS: StationCounts = {
  easy_frame_saw: 1,
  hundegger_saw: 0,
  onsrud_cnc: 1,
  manual_framing_table: 2,
  acadia_workcell: 0,
  floor_cassette_bay: 1,
  integration_bay: 1,
  finishing_bay: 3,
  kitting_area: 1,
  module_exit: 1,
};

export const DEFAULT_RESOURCE_COUNTS: ResourceCounts = {
  gantry_crane_module_matrix: 2,
  forklift: 1,
  tugger: 1,
  panel_cart: 4,
  field_lift_pro: 2,
  scissor_lift: 2,
  wav: 1,
  material_cart: 10,
};
