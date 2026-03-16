import type { RampPhase } from "../types/factory";

interface Props {
  rampPhase: RampPhase;
  numRuns: number;
  simDays: number;
  loading: boolean;
  onRampPhaseChange: (phase: RampPhase) => void;
  onNumRunsChange: (n: number) => void;
  onSimDaysChange: (n: number) => void;
  onRunBatch: () => void;
}

export function ControlPanel({
  rampPhase, numRuns, simDays, loading,
  onRampPhaseChange, onNumRunsChange, onSimDaysChange, onRunBatch,
}: Props) {
  return (
    <div style={{
      display: "flex", gap: 16, alignItems: "center", padding: "12px 16px",
      background: "#1a1a2e", borderBottom: "1px solid #333", flexWrap: "wrap",
    }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <label style={{ color: "#aaa", fontSize: 13 }}>Ramp Phase:</label>
        {(["day_1", "day_90", "day_180"] as RampPhase[]).map((p) => (
          <button
            key={p}
            onClick={() => onRampPhaseChange(p)}
            style={{
              padding: "6px 14px", border: "none", borderRadius: 4, cursor: "pointer",
              background: rampPhase === p ? "#4a9eff" : "#2a2a3e",
              color: rampPhase === p ? "#fff" : "#aaa",
              fontWeight: rampPhase === p ? 600 : 400,
              fontSize: 13,
            }}
          >
            {p.replace("_", " ").replace("day", "Day")}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <label style={{ color: "#aaa", fontSize: 13 }}>Runs:</label>
        <input
          type="number" min={1} max={500} value={numRuns}
          onChange={(e) => onNumRunsChange(parseInt(e.target.value) || 1)}
          style={{
            width: 60, padding: "4px 8px", background: "#2a2a3e",
            border: "1px solid #444", borderRadius: 4, color: "#fff", fontSize: 13,
          }}
        />
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <label style={{ color: "#aaa", fontSize: 13 }}>Sim Days:</label>
        <input
          type="number" min={5} max={180} value={simDays}
          onChange={(e) => onSimDaysChange(parseInt(e.target.value) || 30)}
          style={{
            width: 60, padding: "4px 8px", background: "#2a2a3e",
            border: "1px solid #444", borderRadius: 4, color: "#fff", fontSize: 13,
          }}
        />
      </div>

      <button
        onClick={onRunBatch}
        disabled={loading}
        style={{
          padding: "8px 24px", border: "none", borderRadius: 4, cursor: loading ? "wait" : "pointer",
          background: loading ? "#555" : "#22c55e", color: "#fff",
          fontWeight: 600, fontSize: 14,
        }}
      >
        {loading ? "Running..." : "Run Simulation"}
      </button>
    </div>
  );
}
