import { useState } from "react";
import type {
  StationCounts, ResourceCounts, StationDefinition,
} from "../types/factory";
import { STATION_LABELS, RESOURCE_LABELS } from "../types/factory";

interface Props {
  stationCounts: StationCounts;
  resourceCounts: ResourceCounts;
  crewSkillFactor: number;
  absenteeismRate: number;
  stationDefs: Record<string, StationDefinition> | null;
  onStationCountChange: (key: keyof StationCounts, val: number) => void;
  onResourceCountChange: (key: keyof ResourceCounts, val: number) => void;
  onCrewSkillChange: (val: number) => void;
  onAbsenteeismChange: (val: number) => void;
}

function Section({ title, open, children }: { title: string; open?: boolean; children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(open ?? true);
  return (
    <div style={{ marginBottom: 8 }}>
      <div
        onClick={() => setIsOpen(!isOpen)}
        style={{
          cursor: "pointer", padding: "8px 12px", background: "#1e1e32",
          borderRadius: 4, display: "flex", justifyContent: "space-between",
          alignItems: "center", fontSize: 13, fontWeight: 600, color: "#ddd",
        }}
      >
        {title}
        <span style={{ fontSize: 11, color: "#888" }}>{isOpen ? "▼" : "▶"}</span>
      </div>
      {isOpen && <div style={{ padding: "8px 12px" }}>{children}</div>}
    </div>
  );
}

function SliderRow({
  label, value, min, max, step, capex, onChange,
}: {
  label: string; value: number; min: number; max: number;
  step?: number; capex?: string; onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
      <span style={{ width: 140, fontSize: 12, color: "#bbb" }}>{label}</span>
      <input
        type="range" min={min} max={max} step={step || 1} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: "#4a9eff" }}
      />
      <span style={{ width: 36, textAlign: "right", fontSize: 13, color: "#fff", fontWeight: 600 }}>
        {step && step < 1 ? value.toFixed(2) : value}
      </span>
      {capex && (
        <span style={{ width: 80, textAlign: "right", fontSize: 11, color: "#888" }}>
          {capex}
        </span>
      )}
    </div>
  );
}

function formatCost(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n}`;
}

export function ParameterPanel({
  stationCounts, resourceCounts, crewSkillFactor, absenteeismRate,
  stationDefs, onStationCountChange, onResourceCountChange,
  onCrewSkillChange, onAbsenteeismChange,
}: Props) {
  const stationKeys = Object.keys(stationCounts) as (keyof StationCounts)[];
  const resourceKeys = Object.keys(resourceCounts) as (keyof ResourceCounts)[];

  return (
    <div style={{
      width: 380, background: "#16162a", borderRight: "1px solid #333",
      overflowY: "auto", padding: 8, fontSize: 13,
    }}>
      <h3 style={{ color: "#fff", margin: "8px 12px", fontSize: 15 }}>Parameters</h3>

      <Section title="Station Counts">
        {stationKeys.map((key) => {
          const def = stationDefs?.[key];
          const capex = def ? formatCost(def.capex_cost) + "/ea" : "";
          return (
            <SliderRow
              key={key}
              label={STATION_LABELS[key] || key}
              value={stationCounts[key]}
              min={0} max={key === "finishing_bay" ? 15 : 6}
              capex={capex}
              onChange={(v) => onStationCountChange(key, v)}
            />
          );
        })}
      </Section>

      <Section title="Resource Counts" open={false}>
        {resourceKeys.map((key) => (
          <SliderRow
            key={key}
            label={RESOURCE_LABELS[key] || key}
            value={resourceCounts[key]}
            min={0} max={key === "material_cart" ? 30 : 10}
            onChange={(v) => onResourceCountChange(key, v)}
          />
        ))}
      </Section>

      <Section title="Crew & Labor" open={false}>
        <SliderRow
          label="Skill Factor"
          value={crewSkillFactor}
          min={0.7} max={1.5} step={0.05}
          onChange={onCrewSkillChange}
        />
        <p style={{ fontSize: 11, color: "#888", margin: "2px 0 8px 0" }}>
          1.0 = experienced crew. Higher = slower (new hires).
        </p>
        <SliderRow
          label="Absenteeism %"
          value={absenteeismRate}
          min={0} max={0.3} step={0.01}
          onChange={onAbsenteeismChange}
        />
      </Section>
    </div>
  );
}
