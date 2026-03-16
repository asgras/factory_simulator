import { useState, useEffect, useCallback } from "react";
import { ControlPanel } from "./components/ControlPanel";
import { ParameterPanel } from "./components/ParameterPanel";
import { CapexSummary } from "./components/CapexSummary";
import { ResultsDashboard } from "./components/ResultsDashboard";
import { FactoryCanvas } from "./components/FactoryCanvas";
import { useSimulation, DEFAULT_STATION_COUNTS, DEFAULT_RESOURCE_COUNTS } from "./hooks/useSimulation";
import type { StationCounts, ResourceCounts, RampPhase, SimulateRequest } from "./types/factory";
import "./index.css";

// Target SF/week by ramp phase
const TARGETS: Record<RampPhase, number> = {
  day_1: 1000,
  day_90: 2000,
  day_180: 4000,
};

function App() {
  const { loading, error, results, stationDefs, fetchDefaults, fetchStationDefs, runBatch } = useSimulation();

  const [rampPhase, setRampPhase] = useState<RampPhase>("day_1");
  const [numRuns, setNumRuns] = useState(50);
  const [simDays, setSimDays] = useState(30);
  const [stationCounts, setStationCounts] = useState<StationCounts>(DEFAULT_STATION_COUNTS);
  const [resourceCounts, setResourceCounts] = useState<ResourceCounts>(DEFAULT_RESOURCE_COUNTS);
  const [crewSkillFactor, setCrewSkillFactor] = useState(1.3);
  const [absenteeismRate, setAbsenteeismRate] = useState(0.08);
  const [activeTab, setActiveTab] = useState<"canvas" | "results">("results");

  // Load station definitions on mount
  useEffect(() => {
    fetchStationDefs();
  }, [fetchStationDefs]);

  // Load defaults when ramp phase changes
  const handlePhaseChange = useCallback(async (phase: RampPhase) => {
    setRampPhase(phase);
    try {
      const defaults = await fetchDefaults(phase);
      setStationCounts(defaults.station_counts);
      setResourceCounts(defaults.resource_counts);
      setCrewSkillFactor(defaults.crew_skill_factor);
    } catch (e) {
      console.error("Failed to load defaults:", e);
    }
  }, [fetchDefaults]);

  const handleRunBatch = useCallback(async () => {
    const req: SimulateRequest = {
      station_counts: stationCounts,
      resource_counts: resourceCounts,
      module_config: { name: "CCW Module", width_ft: 13.5, length_ft: 54, sf: 715, panels_per_module: 40, weight_tons: 15 },
      shift_config: { hours_per_shift: 9, shifts_per_day: 1, production_days_per_week: 5 },
      crew_skill_factor: crewSkillFactor,
      absenteeism_rate: absenteeismRate,
      sim_duration_days: simDays,
      num_runs: numRuns,
      ramp_phase: null,
    };
    await runBatch(req);
    setActiveTab("results");
  }, [stationCounts, resourceCounts, crewSkillFactor, absenteeismRate, simDays, numRuns, runBatch]);

  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100vh",
      background: "#0f0f1e", color: "#fff", fontFamily: "'Inter', system-ui, sans-serif",
    }}>
      {/* Top bar */}
      <div style={{
        display: "flex", alignItems: "center", padding: "8px 16px",
        background: "#0a0a18", borderBottom: "1px solid #222",
      }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
          FAB1 Factory Simulator
        </h1>
        <span style={{ marginLeft: 12, fontSize: 12, color: "#666" }}>
          Discrete-Event Simulation for Modular Housing Production
        </span>
      </div>

      <ControlPanel
        rampPhase={rampPhase}
        numRuns={numRuns}
        simDays={simDays}
        loading={loading}
        onRampPhaseChange={handlePhaseChange}
        onNumRunsChange={setNumRuns}
        onSimDaysChange={setSimDays}
        onRunBatch={handleRunBatch}
      />

      {error && (
        <div style={{ padding: "8px 16px", background: "#3a1111", color: "#f87171", fontSize: 13 }}>
          Error: {error}
        </div>
      )}

      {/* Main content */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Left: Parameters */}
        <ParameterPanel
          stationCounts={stationCounts}
          resourceCounts={resourceCounts}
          crewSkillFactor={crewSkillFactor}
          absenteeismRate={absenteeismRate}
          stationDefs={stationDefs}
          onStationCountChange={(key, val) => setStationCounts((prev) => ({ ...prev, [key]: val }))}
          onResourceCountChange={(key, val) => setResourceCounts((prev) => ({ ...prev, [key]: val }))}
          onCrewSkillChange={setCrewSkillFactor}
          onAbsenteeismChange={setAbsenteeismRate}
        />

        {/* Center/Right: Canvas + Results */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Tab switcher */}
          <div style={{ display: "flex", borderBottom: "1px solid #333" }}>
            <button
              onClick={() => setActiveTab("canvas")}
              style={{
                padding: "8px 20px", border: "none", cursor: "pointer",
                background: activeTab === "canvas" ? "#1a1a2e" : "transparent",
                color: activeTab === "canvas" ? "#4a9eff" : "#888",
                borderBottom: activeTab === "canvas" ? "2px solid #4a9eff" : "2px solid transparent",
                fontSize: 13, fontWeight: 500,
              }}
            >
              Factory Floor
            </button>
            <button
              onClick={() => setActiveTab("results")}
              style={{
                padding: "8px 20px", border: "none", cursor: "pointer",
                background: activeTab === "results" ? "#1a1a2e" : "transparent",
                color: activeTab === "results" ? "#4a9eff" : "#888",
                borderBottom: activeTab === "results" ? "2px solid #4a9eff" : "2px solid transparent",
                fontSize: 13, fontWeight: 500,
              }}
            >
              Results Dashboard
            </button>
          </div>

          <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            {activeTab === "canvas" ? (
              <div style={{ flex: 1, position: "relative" }}>
                <FactoryCanvas
                  stationCounts={stationCounts}
                  stationDefs={stationDefs}
                  results={results}
                />
              </div>
            ) : (
              <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
                <div style={{ flex: 1, overflowY: "auto" }}>
                  <ResultsDashboard results={results} targetSfPerWeek={TARGETS[rampPhase]} />
                </div>
                <div style={{ width: 320, overflowY: "auto", borderLeft: "1px solid #333", padding: 12 }}>
                  <CapexSummary capex={results?.capex || null} />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
