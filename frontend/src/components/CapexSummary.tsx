import type { CapexBreakdown } from "../types/factory";
import { STATION_LABELS } from "../types/factory";

interface Props {
  capex: CapexBreakdown | null;
}

function formatCost(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function CapexSummary({ capex }: Props) {
  if (!capex) {
    return (
      <div style={{ padding: 16, color: "#888", fontSize: 13 }}>
        Run a simulation to see CAPEX breakdown.
      </div>
    );
  }

  const stationEntries = Object.entries(capex.breakdown).filter(
    ([k]) => k !== "shared_resources"
  );
  const resourceEntries = capex.breakdown.shared_resources
    ? Object.entries(capex.breakdown.shared_resources as Record<string, { count: number; per_unit: number; total: number }>)
    : [];

  return (
    <div style={{
      background: "#1a1a2e", borderRadius: 8, padding: 16, marginBottom: 16,
    }}>
      <h3 style={{ color: "#fff", margin: "0 0 12px 0", fontSize: 15 }}>
        CAPEX Summary: {formatCost(capex.total)}
      </h3>

      <table style={{ width: "100%", fontSize: 12, color: "#ccc", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #333" }}>
            <th style={{ textAlign: "left", padding: 4 }}>Station</th>
            <th style={{ textAlign: "right", padding: 4 }}>Qty</th>
            <th style={{ textAlign: "right", padding: 4 }}>Unit</th>
            <th style={{ textAlign: "right", padding: 4 }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {stationEntries.map(([key, data]) => {
            if (!data || !('count' in data) || data.count === 0) return null;
            return (
              <tr key={key} style={{ borderBottom: "1px solid #222" }}>
                <td style={{ padding: 4 }}>{STATION_LABELS[key] || key}</td>
                <td style={{ textAlign: "right", padding: 4 }}>{data.count}</td>
                <td style={{ textAlign: "right", padding: 4 }}>{formatCost(data.unit_capex || 0)}</td>
                <td style={{ textAlign: "right", padding: 4, fontWeight: 600 }}>
                  {formatCost(data.line_total || 0)}
                </td>
              </tr>
            );
          })}
          {resourceEntries.length > 0 && (
            <>
              <tr><td colSpan={4} style={{ padding: "8px 4px 4px", color: "#888", fontSize: 11 }}>RESOURCES</td></tr>
              {resourceEntries.map(([key, data]) => {
                if (data.total === 0) return null;
                return (
                  <tr key={key} style={{ borderBottom: "1px solid #222" }}>
                    <td style={{ padding: 4, fontSize: 11 }}>{key.replace(/_/g, " ")}</td>
                    <td style={{ textAlign: "right", padding: 4 }}>{data.count}</td>
                    <td style={{ textAlign: "right", padding: 4 }}>{formatCost(data.per_unit)}</td>
                    <td style={{ textAlign: "right", padding: 4 }}>{formatCost(data.total)}</td>
                  </tr>
                );
              })}
            </>
          )}
        </tbody>
        <tfoot>
          <tr style={{ borderTop: "2px solid #444" }}>
            <td colSpan={3} style={{ padding: "8px 4px", fontWeight: 700, color: "#fff" }}>Total</td>
            <td style={{ textAlign: "right", padding: "8px 4px", fontWeight: 700, color: "#4a9eff", fontSize: 14 }}>
              {formatCost(capex.total)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
