import { useRef, useEffect, useCallback } from "react";
import type { StationCounts, StationDefinition, BatchResponse } from "../types/factory";
import { STATION_LABELS } from "../types/factory";

interface Props {
  stationCounts: StationCounts;
  stationDefs: Record<string, StationDefinition> | null;
  results: BatchResponse | null;
}

// Factory dimensions in feet
const FACTORY_W = 400;
const FACTORY_H = 275;

// Station positions (from spec, in feet, draggable later)
const STATION_POSITIONS: Record<string, [number, number]> = {
  easy_frame_saw: [80, 60],
  hundegger_saw: [80, 60],
  onsrud_cnc: [160, 60],
  manual_framing_table: [120, 120],
  acadia_workcell: [250, 120],
  floor_cassette_bay: [60, 180],
  integration_bay: [120, 200],
  finishing_bay: [60, 250],
  kitting_area: [300, 60],
  module_exit: [200, 270],
};

// Buffer positions
const BUFFER_POSITIONS: Record<string, [number, number]> = {
  raw_lumber: [50, 30],
  raw_sheets: [150, 30],
  cut_lumber: [90, 90],
  cut_sheets: [170, 90],
  panel_buffer: [180, 160],
  floor_cassette: [80, 190],
  module_staging: [120, 220],
  module_yard: [250, 270],
};

// Color mapping for station state based on utilization
function utilColor(util: number): string {
  if (util > 0.85) return "#ef4444";
  if (util > 0.6) return "#f59e0b";
  if (util > 0.3) return "#22c55e";
  return "#555";
}

export function FactoryCanvas({ stationCounts, stationDefs, results }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const scaleX = w / FACTORY_W;
    const scaleY = h / FACTORY_H;

    // Background
    ctx.fillStyle = "#0d0d1a";
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = "#1a1a2e";
    ctx.lineWidth = 0.5;
    for (let x = 0; x <= FACTORY_W; x += 20) {
      ctx.beginPath();
      ctx.moveTo(x * scaleX, 0);
      ctx.lineTo(x * scaleX, h);
      ctx.stroke();
    }
    for (let y = 0; y <= FACTORY_H; y += 20) {
      ctx.beginPath();
      ctx.moveTo(0, y * scaleY);
      ctx.lineTo(w, y * scaleY);
      ctx.stroke();
    }

    // Dock doors (top)
    ctx.fillStyle = "#333";
    ctx.fillRect(40 * scaleX, 0, 180 * scaleX, 15 * scaleY);
    ctx.fillStyle = "#888";
    ctx.font = "11px monospace";
    ctx.fillText("DOCK DOORS", 100 * scaleX, 10 * scaleY);

    // Draw buffers
    Object.entries(BUFFER_POSITIONS).forEach(([name, [x, y]]) => {
      const sx = x * scaleX;
      const sy = y * scaleY;
      ctx.fillStyle = "#1a2a1a";
      ctx.strokeStyle = "#2a4a2a";
      ctx.lineWidth = 1;
      ctx.fillRect(sx - 8, sy - 6, 16, 12);
      ctx.strokeRect(sx - 8, sy - 6, 16, 12);
      ctx.fillStyle = "#4a8a4a";
      ctx.font = "8px monospace";
      ctx.fillText(name.replace(/_/g, " "), sx - 8, sy + 16);
    });

    // Get utilization data from results
    const utilByType: Record<string, number> = {};
    if (results?.summary?.avg_station_utilization) {
      Object.assign(utilByType, results.summary.avg_station_utilization);
    }

    // Draw stations
    const stationKeys = Object.keys(stationCounts) as (keyof StationCounts)[];
    stationKeys.forEach((key) => {
      const count = stationCounts[key];
      if (count === 0) return;

      const basePos = STATION_POSITIONS[key];
      if (!basePos) return;
      const def = stationDefs?.[key];
      const footprint = def?.footprint || [20, 60];

      for (let i = 0; i < count; i++) {
        // Offset multiple stations of same type
        const offsetX = key === "finishing_bay"
          ? (i % 6) * 35  // finishing bays in rows
          : i * (footprint[0] + 10);
        const offsetY = key === "finishing_bay" && i >= 6 ? 30 : 0;

        const px = (basePos[0] + offsetX) * scaleX;
        const py = (basePos[1] + offsetY) * scaleY;
        const fw = footprint[0] * scaleX * 0.8;
        const fh = footprint[1] * scaleY * 0.15;

        const util = utilByType[key] || 0;
        const color = count > 0 ? utilColor(util) : "#333";

        // Station rect
        ctx.fillStyle = color + "40"; // semi-transparent fill
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.fillRect(px, py, fw, fh);
        ctx.strokeRect(px, py, fw, fh);

        // Label
        ctx.fillStyle = "#ddd";
        ctx.font = "10px monospace";
        const label = i === 0 ? (STATION_LABELS[key] || key) : `#${i + 1}`;
        ctx.fillText(label, px + 2, py + fh / 2 + 3);

        // Utilization percentage
        if (util > 0) {
          ctx.fillStyle = color;
          ctx.font = "bold 9px monospace";
          ctx.fillText(`${Math.round(util * 100)}%`, px + fw - 28, py + fh / 2 + 3);
        }
      }
    });

    // Draw flow arrows between key stages
    ctx.strokeStyle = "#334";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);

    const flows: [string, string][] = [
      ["raw_lumber", "easy_frame_saw"],
      ["raw_sheets", "onsrud_cnc"],
      ["easy_frame_saw", "manual_framing_table"],
      ["onsrud_cnc", "manual_framing_table"],
      ["manual_framing_table", "integration_bay"],
      ["floor_cassette_bay", "integration_bay"],
      ["integration_bay", "finishing_bay"],
      ["finishing_bay", "module_exit"],
    ];

    flows.forEach(([from, to]) => {
      const fromPos = BUFFER_POSITIONS[from] || STATION_POSITIONS[from];
      const toPos = STATION_POSITIONS[to] || BUFFER_POSITIONS[to];
      if (!fromPos || !toPos) return;

      ctx.beginPath();
      ctx.moveTo(fromPos[0] * scaleX, fromPos[1] * scaleY);
      ctx.lineTo(toPos[0] * scaleX, toPos[1] * scaleY);
      ctx.stroke();
    });

    ctx.setLineDash([]);

    // Scale indicator
    ctx.fillStyle = "#555";
    ctx.font = "10px monospace";
    ctx.fillText(`${FACTORY_W}' x ${FACTORY_H}'`, w - 80, h - 8);
  }, [stationCounts, stationDefs, results]);

  useEffect(() => {
    draw();
    const handleResize = () => draw();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
