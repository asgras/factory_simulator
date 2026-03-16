import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import type { BatchResponse } from "../types/factory";
import { STATION_LABELS } from "../types/factory";

interface Props {
  results: BatchResponse | null;
  targetSfPerWeek: number;
}

export function ResultsDashboard({ results, targetSfPerWeek }: Props) {
  if (!results) {
    return (
      <div style={{ padding: 32, color: "#888", textAlign: "center", fontSize: 14 }}>
        Configure parameters and run a simulation to see results.
      </div>
    );
  }

  const { summary } = results;

  // Build throughput histogram data
  const sfValues = results.sf_per_week;
  const binCount = 15;
  const minVal = Math.min(...sfValues);
  const maxVal = Math.max(...sfValues);
  const binWidth = (maxVal - minVal) / binCount || 1;
  const histBins: { range: string; count: number; aboveTarget: boolean }[] = [];
  for (let i = 0; i < binCount; i++) {
    const lo = minVal + i * binWidth;
    const hi = lo + binWidth;
    const count = sfValues.filter((v) => v >= lo && (i === binCount - 1 ? v <= hi : v < hi)).length;
    histBins.push({
      range: `${lo.toFixed(0)}`,
      count,
      aboveTarget: lo >= targetSfPerWeek,
    });
  }

  // Build utilization data
  const utilData = Object.entries(summary.avg_station_utilization).map(([key, util]) => ({
    name: STATION_LABELS[key] || key,
    utilization: Math.round(util * 100),
    fill: util > 0.85 ? "#ef4444" : util > 0.6 ? "#f59e0b" : "#22c55e",
  }));

  // Probability of hitting target
  const hitTarget = sfValues.filter((v) => v >= targetSfPerWeek).length;
  const probHit = (hitTarget / sfValues.length) * 100;

  return (
    <div style={{ padding: 16, overflowY: "auto" }}>
      {/* Summary Stats */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <StatCard label="Modules/Week" value={summary.modules_per_week.mean.toFixed(2)}
          sub={`p5=${summary.modules_per_week.p5.toFixed(1)} | p95=${summary.modules_per_week.p95.toFixed(1)}`} />
        <StatCard label="SF/Week" value={summary.sf_per_week.mean.toFixed(0)}
          sub={`p5=${summary.sf_per_week.p5.toFixed(0)} | p95=${summary.sf_per_week.p95.toFixed(0)}`} />
        <StatCard label="Target Hit Prob" value={`${probHit.toFixed(0)}%`}
          sub={`${hitTarget}/${sfValues.length} runs >= ${targetSfPerWeek} SF/wk`}
          color={probHit >= 80 ? "#22c55e" : probHit >= 50 ? "#f59e0b" : "#ef4444"} />
        <StatCard label="Runs" value={String(summary.num_runs)} sub="Monte Carlo simulations" />
      </div>

      {/* Throughput Histogram */}
      <div style={{ background: "#1a1a2e", borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <h4 style={{ color: "#fff", margin: "0 0 12px 0", fontSize: 14 }}>SF/Week Distribution</h4>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={histBins}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="range" tick={{ fill: "#888", fontSize: 10 }} />
            <YAxis tick={{ fill: "#888", fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: "#222", border: "1px solid #444", fontSize: 12 }}
              labelStyle={{ color: "#fff" }}
            />
            <Bar dataKey="count" fill="#4a9eff" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Station Utilization */}
      <div style={{ background: "#1a1a2e", borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <h4 style={{ color: "#fff", margin: "0 0 12px 0", fontSize: 14 }}>Station Utilization (%)</h4>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={utilData} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis type="number" domain={[0, 100]} tick={{ fill: "#888", fontSize: 10 }} />
            <YAxis type="category" dataKey="name" width={120} tick={{ fill: "#bbb", fontSize: 11 }} />
            <Tooltip
              contentStyle={{ background: "#222", border: "1px solid #444", fontSize: 12 }}
              formatter={(value) => [`${value}%`, "Utilization"]}
            />
            <Bar dataKey="utilization" radius={[0, 4, 4, 0]}>
              {utilData.map((entry, i) => (
                <Cell key={i} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 11, color: "#888" }}>
          <span><span style={{ color: "#ef4444" }}>■</span> &gt;85% (bottleneck)</span>
          <span><span style={{ color: "#f59e0b" }}>■</span> 60-85%</span>
          <span><span style={{ color: "#22c55e" }}>■</span> &lt;60%</span>
        </div>
      </div>

      {/* Bottleneck Table */}
      <div style={{ background: "#1a1a2e", borderRadius: 8, padding: 16 }}>
        <h4 style={{ color: "#fff", margin: "0 0 12px 0", fontSize: 14 }}>Bottleneck Analysis</h4>
        <table style={{ width: "100%", fontSize: 12, color: "#ccc", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #333" }}>
              <th style={{ textAlign: "left", padding: 6 }}>Station</th>
              <th style={{ textAlign: "right", padding: 6 }}>Util %</th>
              <th style={{ textAlign: "right", padding: 6 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {utilData.sort((a, b) => b.utilization - a.utilization).map((d) => (
              <tr key={d.name} style={{ borderBottom: "1px solid #222" }}>
                <td style={{ padding: 6 }}>{d.name}</td>
                <td style={{ textAlign: "right", padding: 6 }}>{d.utilization}%</td>
                <td style={{ textAlign: "right", padding: 6, color: d.fill, fontWeight: 600 }}>
                  {d.utilization > 85 ? "BOTTLENECK" : d.utilization > 60 ? "Busy" : "OK"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, color }: {
  label: string; value: string; sub: string; color?: string;
}) {
  return (
    <div style={{
      background: "#1a1a2e", borderRadius: 8, padding: "12px 20px",
      minWidth: 140, flex: 1,
    }}>
      <div style={{ color: "#888", fontSize: 11, marginBottom: 4 }}>{label}</div>
      <div style={{ color: color || "#fff", fontSize: 24, fontWeight: 700 }}>{value}</div>
      <div style={{ color: "#666", fontSize: 11, marginTop: 2 }}>{sub}</div>
    </div>
  );
}
