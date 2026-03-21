import { useState, useMemo } from "react";

// ─── Helpers ────────────────────────────────────────────────────────────────
// Input format: "type1:qty1,type2:qty2" e.g. "sheathed_panels:4,mep_panels:2"
// Quantity defaults to 1 if omitted: "raw_lumber" => {type:"raw_lumber", qty:1}
function parseInputs(inputType) {
  if (!inputType) return [];
  return inputType.split(",").map(s => {
    const parts = s.trim().split(":");
    return { type: parts[0].trim(), qty: parts.length > 1 ? parseFloat(parts[1]) || 1 : 1 };
  }).filter(i => i.type);
}

function formatInputs(inputs) {
  return inputs.map(i => i.qty === 1 ? i.type : `${i.type}:${i.qty}`).join(",");
}

function displayInputs(inputType) {
  const inputs = parseInputs(inputType);
  return inputs.map(i => `${i.type} ×${i.qty}`).join(", ");
}

// ─── Default workcell library ───────────────────────────────────────────────
const DEFAULT_WORKCELLS = [
  { id: 1, name: "Framing", inputType: "raw_lumber:2", outputType: "framed_panels", outputRate: 8, laborRequired: 3, sqft: 600 },
  { id: 2, name: "Insulation", inputType: "framed_panels:1", outputType: "insulated_panels", outputRate: 10, laborRequired: 2, sqft: 400 },
  { id: 3, name: "Sheathing", inputType: "insulated_panels:1", outputType: "sheathed_panels", outputRate: 12, laborRequired: 2, sqft: 350 },
  { id: 4, name: "MEP Rough-In", inputType: "framed_panels:1", outputType: "mep_panels", outputRate: 6, laborRequired: 4, sqft: 500 },
  { id: 5, name: "Panel Assembly", inputType: "sheathed_panels:4,mep_panels:2", outputType: "assembled_modules", outputRate: 4, laborRequired: 5, sqft: 800 },
  { id: 6, name: "Finishing", inputType: "assembled_modules:1", outputType: "finished_module", outputRate: 3, laborRequired: 4, sqft: 700 },
];

const DEFAULT_FACTORY = { totalSqft: 15000, totalLabor: 30, sqftPerUnit: 700, hoursPerWeek: 40 };

// ─── Solver ─────────────────────────────────────────────────────────────────
function solveFactory(workcells, factory) {
  const empty = { allocation: [], throughput: 0, bottleneck: null, totalSqft: 0, totalLabor: 0, messages: [], weeklySqft: 0, finalTypes: [], rawTypes: [] };
  if (workcells.length === 0) return { ...empty, messages: ["No workcells defined."] };

  const cells = workcells.map(w => ({
    ...w,
    inputs: parseInputs(w.inputType),
  }));

  const allOutputTypes = new Set(cells.map(c => c.outputType));
  const allInputTypes = new Set(cells.flatMap(c => c.inputs.map(i => i.type)));
  const finalTypes = [...allOutputTypes].filter(t => !allInputTypes.has(t));
  if (finalTypes.length === 0) return { ...empty, messages: ["No final output type found (circular dependency or missing workcells)."] };
  const rawTypes = [...allInputTypes].filter(t => !allOutputTypes.has(t));

  const producerMap = {};
  cells.forEach((c, i) => {
    if (!producerMap[c.outputType]) producerMap[c.outputType] = [];
    producerMap[c.outputType].push(i);
  });

  // ── BFS demand multiplier computation ──────────────────────────────────
  // Processes types in correct order: final outputs first, then upstream,
  // ensuring shared intermediates receive ALL downstream demand before processing.
  const computeDemandMultipliers = (alloc) => {
    const demandMult = {};
    finalTypes.forEach(ft => { demandMult[ft] = 1; });

    // Build consumer map: for type X, which output types consume X as an input?
    const consumedBy = {};
    for (const [type, prods] of Object.entries(producerMap)) {
      for (const pi of prods) {
        for (const inp of cells[pi].inputs) {
          if (rawTypes.includes(inp.type)) continue;
          if (!consumedBy[inp.type]) consumedBy[inp.type] = new Set();
          consumedBy[inp.type].add(type);
        }
      }
    }

    // BFS: only process a type once ALL downstream consumers are processed
    const processed = new Set();
    const queue = [...finalTypes];

    while (queue.length > 0) {
      const type = queue.shift();
      if (processed.has(type)) continue;
      processed.add(type);

      const demand = demandMult[type] || 0;
      const prods = producerMap[type] || [];
      const totalCap = prods.reduce((s, pi) => s + (alloc[pi] > 0 ? alloc[pi] * cells[pi].outputRate : 0), 0);

      for (const pi of prods) {
        if (alloc[pi] === 0) continue;
        const share = totalCap > 0 ? (alloc[pi] * cells[pi].outputRate) / totalCap : 0;
        const producerDemand = demand * share;
        for (const inp of cells[pi].inputs) {
          if (rawTypes.includes(inp.type)) continue;
          demandMult[inp.type] = (demandMult[inp.type] || 0) + inp.qty * producerDemand;
          // Enqueue input type only when ALL its consumers have been processed
          const consumers = consumedBy[inp.type] || new Set();
          if ([...consumers].every(c => processed.has(c)) && !processed.has(inp.type)) {
            queue.push(inp.type);
          }
        }
      }
    }
    return demandMult;
  };

  const computeThroughput = (alloc) => {
    const typeCapacity = {};
    cells.forEach((c, i) => {
      if (alloc[i] > 0) {
        typeCapacity[c.outputType] = (typeCapacity[c.outputType] || 0) + alloc[i] * c.outputRate;
      }
    });
    const demandMult = computeDemandMultipliers(alloc);
    let throughput = Infinity;
    let bottleneckType = null;
    for (const type of Object.keys(demandMult)) {
      const cap = typeCapacity[type] || 0;
      const demand = demandMult[type];
      if (demand > 0) {
        const maxT = cap / demand;
        if (maxT < throughput) { throughput = maxT; bottleneckType = type; }
      }
    }
    if (!isFinite(throughput)) throughput = 0;
    const effectiveRate = {};
    for (const type of Object.keys(demandMult)) {
      effectiveRate[type] = throughput * (demandMult[type] || 0);
    }
    return { finalThroughput: throughput, typeCapacity, effectiveRate, demandMult, bottleneckType };
  };

  // ── Find minimum required cells ────────────────────────────────────────
  const required = new Set();
  const findRequired = (outputType) => {
    const prods = producerMap[outputType] || [];
    if (prods.length === 0) return;
    const best = prods.reduce((a, b) =>
      cells[a].outputRate / (cells[a].sqft + cells[a].laborRequired * 100) >
      cells[b].outputRate / (cells[b].sqft + cells[b].laborRequired * 100) ? a : b
    );
    if (required.has(best)) return;
    required.add(best);
    cells[best].inputs.forEach(inp => {
      if (!rawTypes.includes(inp.type)) findRequired(inp.type);
    });
  };
  finalTypes.forEach(ft => findRequired(ft));

  let allocation = cells.map((_, i) => required.has(i) ? 1 : 0);
  const minSqft = allocation.reduce((s, n, i) => s + n * cells[i].sqft, 0);
  const minLabor = allocation.reduce((s, n, i) => s + n * cells[i].laborRequired, 0);
  if (minSqft > factory.totalSqft || minLabor > factory.totalLabor) {
    return { ...empty, allocation: cells.map((c, i) => ({ ...c, count: allocation[i] })),
      totalSqft: minSqft, totalLabor: minLabor,
      messages: [`Factory too small or insufficient labor. Need at least ${minSqft} sqft and ${minLabor} workers.`] };
  }

  // ── LP-based initial allocation ────────────────────────────────────────
  // Compute demand multipliers from baseline (1 of each required cell)
  const baseDM = computeDemandMultipliers(allocation);

  // For each cell, compute instances needed per unit throughput:
  //   cellNeedPerT[i] = demandMult[outputType] / outputRate (single producer)
  //   For multiple producers: split proportionally by rate
  const cellNeedPerT = cells.map((c, i) => {
    if (!required.has(i)) return 0;
    const d = baseDM[c.outputType] || 0;
    if (d === 0) return 0;
    const prods = (producerMap[c.outputType] || []).filter(pi => required.has(pi));
    if (prods.length === 1) return d / c.outputRate;
    const totalRate = prods.reduce((s, pi) => s + cells[pi].outputRate, 0);
    return d / totalRate;
  });

  // T_max_fractional = min(totalSqft / sum(need*sqft), totalLabor / sum(need*labor))
  const sqftPerT = cellNeedPerT.reduce((s, d, i) => s + d * cells[i].sqft, 0);
  const laborPerT = cellNeedPerT.reduce((s, d, i) => s + d * cells[i].laborRequired, 0);

  if (sqftPerT > 0 && laborPerT > 0) {
    const T_frac = Math.min(factory.totalSqft / sqftPerT, factory.totalLabor / laborPerT);
    allocation = cells.map((c, i) => {
      if (cellNeedPerT[i] === 0) return 0;
      return Math.max(1, Math.floor(T_frac * cellNeedPerT[i]));
    });
  }

  // ── Helper: check if additions fit ─────────────────────────────────────
  const currentUsage = (alloc) => {
    let sq = 0, lb = 0;
    for (let i = 0; i < cells.length; i++) { sq += alloc[i] * cells[i].sqft; lb += alloc[i] * cells[i].laborRequired; }
    return { sq, lb };
  };

  // ── Greedy refinement: singles ─────────────────────────────────────────
  const greedySingles = (alloc, maxIter) => {
    for (let iter = 0; iter < maxIter; iter++) {
      const { sq, lb } = currentUsage(alloc);
      const { finalThroughput } = computeThroughput(alloc);
      let bestGain = 0, bestIdx = -1;
      for (let i = 0; i < cells.length; i++) {
        if (sq + cells[i].sqft > factory.totalSqft || lb + cells[i].laborRequired > factory.totalLabor) continue;
        alloc[i]++;
        const gain = computeThroughput(alloc).finalThroughput - finalThroughput;
        alloc[i]--;
        if (gain > bestGain + 1e-9) { bestGain = gain; bestIdx = i; }
      }
      if (bestIdx === -1 || bestGain <= 1e-9) break;
      alloc[bestIdx]++;
    }
  };

  // ── Greedy refinement: pairs ───────────────────────────────────────────
  const greedyPairs = (alloc, maxIter) => {
    for (let iter = 0; iter < maxIter; iter++) {
      const { sq, lb } = currentUsage(alloc);
      const { finalThroughput } = computeThroughput(alloc);
      let bestGain = 0, bestMove = null;
      for (let i = 0; i < cells.length; i++) {
        for (let j = i; j < cells.length; j++) {
          const addSq = cells[i].sqft + cells[j].sqft;
          const addLb = cells[i].laborRequired + cells[j].laborRequired;
          if (sq + addSq > factory.totalSqft || lb + addLb > factory.totalLabor) continue;
          alloc[i]++; alloc[j]++;
          const gain = computeThroughput(alloc).finalThroughput - finalThroughput;
          alloc[j]--; alloc[i]--;
          if (gain > bestGain + 1e-9) { bestGain = gain; bestMove = [i, j]; }
        }
      }
      if (!bestMove || bestGain <= 1e-9) break;
      for (const idx of bestMove) alloc[idx]++;
    }
  };

  // ── Greedy refinement: bottleneck batch additions ──────────────────────
  // Finds all near-bottleneck types and tries adding one of each simultaneously.
  // This handles cases where 3+ stages are co-bottlenecked and no pair helps.
  const greedyBatch = (alloc, maxIter) => {
    for (let iter = 0; iter < maxIter; iter++) {
      const { sq, lb } = currentUsage(alloc);
      const { finalThroughput, demandMult: dm, typeCapacity } = computeThroughput(alloc);
      if (finalThroughput <= 0) break;

      // Find near-bottleneck types (within 2% of minimum ratio)
      const bottleneckCells = [];
      for (const type of Object.keys(dm)) {
        const cap = typeCapacity[type] || 0;
        const ratio = dm[type] > 0 ? cap / dm[type] : Infinity;
        if (ratio < finalThroughput * 1.02) {
          const prods = (producerMap[type] || []).filter(pi => alloc[pi] > 0 || required.has(pi));
          if (prods.length > 0) {
            const best = prods.reduce((a, b) =>
              cells[a].sqft + cells[a].laborRequired < cells[b].sqft + cells[b].laborRequired ? a : b
            );
            bottleneckCells.push(best);
          }
        }
      }

      if (bottleneckCells.length < 2) break; // singles/pairs handle 1-cell additions
      const unique = [...new Set(bottleneckCells)];
      const addSq = unique.reduce((s, i) => s + cells[i].sqft, 0);
      const addLb = unique.reduce((s, i) => s + cells[i].laborRequired, 0);
      if (sq + addSq > factory.totalSqft || lb + addLb > factory.totalLabor) {
        // Try subsets: remove the most expensive cell and retry
        let found = false;
        for (let drop = 0; drop < unique.length && !found; drop++) {
          const subset = unique.filter((_, idx) => idx !== drop);
          const subSq = subset.reduce((s, i) => s + cells[i].sqft, 0);
          const subLb = subset.reduce((s, i) => s + cells[i].laborRequired, 0);
          if (sq + subSq <= factory.totalSqft && lb + subLb <= factory.totalLabor) {
            for (const i of subset) alloc[i]++;
            const gain = computeThroughput(alloc).finalThroughput - finalThroughput;
            if (gain > 1e-9) { found = true; } else { for (const i of subset) alloc[i]--; }
          }
        }
        if (!found) break;
      } else {
        for (const i of unique) alloc[i]++;
        const gain = computeThroughput(alloc).finalThroughput - finalThroughput;
        if (gain <= 1e-9) {
          for (const i of unique) alloc[i]--;
          break;
        }
      }
    }
  };

  // ── Proportional chain scaling ─────────────────────────────────────────
  // After initial greedy, try adding complete proportional batches
  // (one of each required cell) to scale up evenly.
  const greedyChain = (alloc, maxIter) => {
    const reqArr = [...required];
    const chainSqft = reqArr.reduce((s, i) => s + cells[i].sqft, 0);
    const chainLabor = reqArr.reduce((s, i) => s + cells[i].laborRequired, 0);
    for (let iter = 0; iter < maxIter; iter++) {
      const { sq, lb } = currentUsage(alloc);
      if (sq + chainSqft > factory.totalSqft || lb + chainLabor > factory.totalLabor) break;
      const { finalThroughput } = computeThroughput(alloc);
      for (const i of reqArr) alloc[i]++;
      const gain = computeThroughput(alloc).finalThroughput - finalThroughput;
      if (gain <= 1e-9) {
        for (const i of reqArr) alloc[i]--;
        break;
      }
    }
  };

  // ── Swap optimization ─────────────────────────────────────────────────
  // Try removing one instance of a non-bottleneck cell and using freed
  // resources for bottleneck cells.
  const greedySwaps = (alloc, maxIter) => {
    for (let iter = 0; iter < maxIter; iter++) {
      const { finalThroughput } = computeThroughput(alloc);
      let bestGain = 0, bestSwap = null;
      for (let rem = 0; rem < cells.length; rem++) {
        if (alloc[rem] <= 1) continue; // keep at least 1
        alloc[rem]--;
        const { sq: freeSq, lb: freeLb } = currentUsage(alloc);
        // Try adding 1 or 2 other cells with the freed resources
        for (let add = 0; add < cells.length; add++) {
          if (freeSq + cells[add].sqft > factory.totalSqft || freeLb + cells[add].laborRequired > factory.totalLabor) continue;
          alloc[add]++;
          const gain = computeThroughput(alloc).finalThroughput - finalThroughput;
          if (gain > bestGain + 1e-9) { bestGain = gain; bestSwap = { rem, adds: [add] }; }
          // Try adding a second cell too
          const { sq: sq2, lb: lb2 } = currentUsage(alloc);
          for (let add2 = add; add2 < cells.length; add2++) {
            if (sq2 + cells[add2].sqft > factory.totalSqft || lb2 + cells[add2].laborRequired > factory.totalLabor) continue;
            alloc[add2]++;
            const gain2 = computeThroughput(alloc).finalThroughput - finalThroughput;
            if (gain2 > bestGain + 1e-9) { bestGain = gain2; bestSwap = { rem, adds: [add, add2] }; }
            alloc[add2]--;
          }
          alloc[add]--;
        }
        alloc[rem]++;
      }
      if (!bestSwap || bestGain <= 1e-9) break;
      alloc[bestSwap.rem]--;
      for (const a of bestSwap.adds) alloc[a]++;
    }
  };

  // Run all optimization passes
  greedySingles(allocation, 500);
  greedyPairs(allocation, 200);
  greedyBatch(allocation, 100);
  greedyChain(allocation, 50);
  greedySwaps(allocation, 100);
  greedySingles(allocation, 500); // Final cleanup pass

  // ── Results ─────────────────────────────────────────────────────────────
  const totalSqft = allocation.reduce((s, n, i) => s + n * cells[i].sqft, 0);
  const totalLabor = allocation.reduce((s, n, i) => s + n * cells[i].laborRequired, 0);
  const { finalThroughput, typeCapacity, effectiveRate, demandMult, bottleneckType } = computeThroughput(allocation);

  let bottleneckIdx = -1;
  if (bottleneckType) {
    let minSlack = Infinity;
    for (const pi of (producerMap[bottleneckType] || [])) {
      if (allocation[pi] > 0) {
        const slack = allocation[pi] * cells[pi].outputRate - (demandMult[cells[pi].outputType] || 0) * finalThroughput;
        if (slack < minSlack) { minSlack = slack; bottleneckIdx = pi; }
      }
    }
  }

  const weeklySqft = finalThroughput * (factory.hoursPerWeek || 40) * (factory.sqftPerUnit || 0);
  const messages = [];
  const sqftUtil = (totalSqft / factory.totalSqft * 100).toFixed(1);
  const laborUtil = (totalLabor / factory.totalLabor * 100).toFixed(1);
  messages.push(`Space utilization: ${sqftUtil}% (${totalSqft.toLocaleString()} / ${factory.totalSqft.toLocaleString()} sqft)`);
  messages.push(`Labor utilization: ${laborUtil}% (${totalLabor} / ${factory.totalLabor} workers)`);
  if (bottleneckIdx >= 0) messages.push(`Bottleneck: ${cells[bottleneckIdx].name}`);

  const remSqft = factory.totalSqft - totalSqft;
  const remLabor = factory.totalLabor - totalLabor;
  // Explain why resources are unused
  if (remSqft > 0 && remLabor > 0) {
    const smallestSqft = Math.min(...cells.map(c => c.sqft));
    const smallestLabor = Math.min(...cells.map(c => c.laborRequired));
    if (remLabor < smallestLabor) {
      messages.push(`Remaining ${remLabor} worker(s) cannot staff any workcell (min: ${smallestLabor})`);
    } else if (remSqft < smallestSqft) {
      messages.push(`Remaining ${remSqft.toLocaleString()} sqft cannot fit any workcell (min: ${smallestSqft})`);
    } else {
      messages.push(`Unused: ${remSqft.toLocaleString()} sqft, ${remLabor} workers — adding more cells wouldn't improve throughput (co-bottleneck constraint)`);
    }
  } else if (remSqft <= 0 && remLabor <= 0) {
    messages.push("Both floor space and labor are fully allocated");
  } else if (remSqft <= 0) {
    messages.push("Constraint: floor space is fully allocated");
  } else {
    messages.push("Constraint: labor pool is fully allocated");
  }

  return {
    allocation: cells.map((c, i) => ({
      ...c, count: allocation[i],
      totalCapacity: allocation[i] * c.outputRate,
      effectiveRate: effectiveRate[c.outputType] || 0,
      demandMult: demandMult[c.outputType] || 0,
      utilization: allocation[i] > 0 ? Math.min(1, (effectiveRate[c.outputType] || 0) / (allocation[i] * c.outputRate)) : 0,
    })),
    throughput: finalThroughput,
    bottleneck: bottleneckIdx >= 0 ? cells[bottleneckIdx].name : "None",
    totalSqft, totalLabor, finalTypes, rawTypes, messages, weeklySqft,
  };
}

// ─── Input Editor (sub-component for editing inputs with quantities) ────────

function InputEditor({ inputs, onChange }) {
  const update = (idx, field, value) => {
    const next = inputs.map((inp, i) => i === idx ? { ...inp, [field]: value } : inp);
    onChange(next);
  };
  const add = () => onChange([...inputs, { type: "", qty: 1 }]);
  const remove = (idx) => onChange(inputs.filter((_, i) => i !== idx));

  const sm = { padding: "4px 6px", border: "1px solid #d1d5db", borderRadius: "4px", fontSize: "12px", background: "#fff", boxSizing: "border-box" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
      {inputs.map((inp, idx) => (
        <div key={idx} style={{ display: "flex", gap: "4px", alignItems: "center" }}>
          <input style={{ ...sm, flex: 1, minWidth: "80px" }} value={inp.type} placeholder="material_type"
            onChange={e => update(idx, "type", e.target.value)} />
          <span style={{ fontSize: "11px", color: "#9ca3af" }}>×</span>
          <input style={{ ...sm, width: "44px", textAlign: "center" }} type="number" min="0.1" step="0.1" value={inp.qty}
            onChange={e => update(idx, "qty", parseFloat(e.target.value) || 1)} />
          {inputs.length > 1 && (
            <button onClick={() => remove(idx)} style={{ background: "none", border: "none", color: "#dc2626", cursor: "pointer", fontSize: "14px", padding: "0 2px", lineHeight: 1 }}>×</button>
          )}
        </div>
      ))}
      <button onClick={add} style={{ fontSize: "11px", color: "#2563eb", background: "none", border: "none", cursor: "pointer", textAlign: "left", padding: "2px 0" }}>+ add input</button>
    </div>
  );
}

// ─── Workcell Editor ────────────────────────────────────────────────────────

function WorkcellEditor({ workcells, setWorkcells }) {
  const [editing, setEditing] = useState(null);
  const [isAdding, setIsAdding] = useState(false);
  const [form, setForm] = useState({});
  const [formInputs, setFormInputs] = useState([]);

  const startEdit = (wc) => {
    setIsAdding(false);
    setEditing(wc.id);
    setForm({ ...wc });
    setFormInputs(parseInputs(wc.inputType));
  };

  const startAdd = () => {
    const newId = Math.max(0, ...workcells.map(w => w.id)) + 1;
    setForm({ id: newId, name: "", inputType: "", outputType: "", outputRate: 1, laborRequired: 1, sqft: 100 });
    setFormInputs([{ type: "", qty: 1 }]);
    setIsAdding(true);
    setEditing(newId);
  };

  const save = () => {
    const inputType = formatInputs(formInputs.filter(i => i.type.trim()));
    const wc = { ...form, inputType };
    if (isAdding) {
      setWorkcells([...workcells, wc]);
    } else {
      setWorkcells(workcells.map(w => w.id === form.id ? wc : w));
    }
    setEditing(null);
    setIsAdding(false);
  };

  const cancelEdit = () => { setEditing(null); setIsAdding(false); };
  const remove = (id) => { setWorkcells(workcells.filter(w => w.id !== id)); if (editing === id) cancelEdit(); };

  const fld = { padding: "6px 10px", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "13px", width: "100%", boxSizing: "border-box", background: "#fff" };

  const renderFormRow = (key) => (
    <tr key={key} style={{ background: "#eff6ff", verticalAlign: "top" }}>
      <td style={{ padding: "6px" }}><input style={fld} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Name" autoFocus /></td>
      <td style={{ padding: "6px" }}>
        <InputEditor inputs={formInputs} onChange={setFormInputs} />
      </td>
      <td style={{ padding: "6px" }}><input style={fld} value={form.outputType} onChange={e => setForm({ ...form, outputType: e.target.value })} placeholder="output_type" /></td>
      <td style={{ padding: "6px" }}><input style={fld} type="number" min="0.1" step="0.1" value={form.outputRate} onChange={e => setForm({ ...form, outputRate: parseFloat(e.target.value) || 0 })} /></td>
      <td style={{ padding: "6px" }}><input style={fld} type="number" min="1" step="1" value={form.laborRequired} onChange={e => setForm({ ...form, laborRequired: parseInt(e.target.value) || 1 })} /></td>
      <td style={{ padding: "6px" }}><input style={fld} type="number" min="10" step="10" value={form.sqft} onChange={e => setForm({ ...form, sqft: parseInt(e.target.value) || 100 })} /></td>
      <td style={{ padding: "6px", whiteSpace: "nowrap" }}>
        <button onClick={save} style={{ padding: "4px 10px", background: "#16a34a", color: "#fff", border: "none", borderRadius: "4px", fontSize: "12px", cursor: "pointer", marginRight: "4px" }}>Save</button>
        <button onClick={cancelEdit} style={{ padding: "4px 10px", background: "#9ca3af", color: "#fff", border: "none", borderRadius: "4px", fontSize: "12px", cursor: "pointer" }}>Cancel</button>
      </td>
    </tr>
  );

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <h3 style={{ margin: 0, fontSize: "15px", fontWeight: 600, color: "#374151" }}>Workcells</h3>
        <button onClick={startAdd} disabled={isAdding} style={{
          padding: "6px 14px", background: isAdding ? "#93c5fd" : "#2563eb", color: "#fff", border: "none",
          borderRadius: "6px", fontSize: "13px", cursor: isAdding ? "default" : "pointer", fontWeight: 500,
        }}>+ Add Workcell</button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
              {["Name", "Inputs (type × qty)", "Output Type", "Rate/hr", "Labor", "Sqft", ""].map(h => (
                <th key={h} style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {workcells.map(wc => (
              editing === wc.id && !isAdding ? renderFormRow(wc.id) : (
                <tr key={wc.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "8px 10px", fontWeight: 500 }}>{wc.name}</td>
                  <td style={{ padding: "8px 10px", color: "#6b7280", fontSize: "12px" }}>{displayInputs(wc.inputType)}</td>
                  <td style={{ padding: "8px 10px", color: "#6b7280" }}>{wc.outputType}</td>
                  <td style={{ padding: "8px 10px" }}>{wc.outputRate}</td>
                  <td style={{ padding: "8px 10px" }}>{wc.laborRequired}</td>
                  <td style={{ padding: "8px 10px" }}>{wc.sqft.toLocaleString()}</td>
                  <td style={{ padding: "8px 10px", whiteSpace: "nowrap" }}>
                    <button onClick={() => startEdit(wc)} style={{ padding: "3px 8px", background: "#f3f4f6", border: "1px solid #d1d5db", borderRadius: "4px", fontSize: "12px", cursor: "pointer", marginRight: "4px" }}>Edit</button>
                    <button onClick={() => remove(wc.id)} style={{ padding: "3px 8px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "4px", fontSize: "12px", cursor: "pointer", color: "#dc2626" }}>Remove</button>
                  </td>
                </tr>
              )
            ))}
            {isAdding && renderFormRow("new-workcell")}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Factory Params ─────────────────────────────────────────────────────────

function FactoryParams({ factory, setFactory }) {
  const sliderTrack = { width: "100%", cursor: "pointer", accentColor: "#2563eb" };
  const numInput = { padding: "6px 10px", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "13px", width: "100px", background: "#fff", textAlign: "right" };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
      <div>
        <label style={{ fontSize: "13px", fontWeight: 600, color: "#374151", display: "block", marginBottom: "6px" }}>
          Factory Floor Area: <span style={{ color: "#2563eb" }}>{factory.totalSqft.toLocaleString()} sqft</span>
        </label>
        <input type="range" min={1000} max={100000} step={500} value={factory.totalSqft}
          onChange={e => setFactory({ ...factory, totalSqft: parseInt(e.target.value) })} style={sliderTrack} />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#9ca3af" }}><span>1,000</span><span>100,000</span></div>
      </div>
      <div>
        <label style={{ fontSize: "13px", fontWeight: 600, color: "#374151", display: "block", marginBottom: "6px" }}>
          Labor Pool: <span style={{ color: "#2563eb" }}>{factory.totalLabor} workers</span>
        </label>
        <input type="range" min={1} max={200} step={1} value={factory.totalLabor}
          onChange={e => setFactory({ ...factory, totalLabor: parseInt(e.target.value) })} style={sliderTrack} />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#9ca3af" }}><span>1</span><span>200</span></div>
      </div>
      <div>
        <label style={{ fontSize: "13px", fontWeight: 600, color: "#374151", display: "block", marginBottom: "6px" }}>Sqft per Finished Unit</label>
        <input type="number" min={1} step={10} value={factory.sqftPerUnit}
          onChange={e => setFactory({ ...factory, sqftPerUnit: parseFloat(e.target.value) || 0 })} style={numInput} />
        <span style={{ fontSize: "12px", color: "#9ca3af", marginLeft: "8px" }}>sqft/unit</span>
      </div>
      <div>
        <label style={{ fontSize: "13px", fontWeight: 600, color: "#374151", display: "block", marginBottom: "6px" }}>Production Hours per Week</label>
        <input type="number" min={1} max={168} step={1} value={factory.hoursPerWeek}
          onChange={e => setFactory({ ...factory, hoursPerWeek: parseInt(e.target.value) || 40 })} style={numInput} />
        <span style={{ fontSize: "12px", color: "#9ca3af", marginLeft: "8px" }}>hrs/week</span>
      </div>
    </div>
  );
}

// ─── Results Dashboard ──────────────────────────────────────────────────────

function ResultsDashboard({ result, factory }) {
  if (!result || result.throughput === 0) {
    return (
      <div style={{ padding: "20px", background: "#fef2f2", borderRadius: "8px", border: "1px solid #fecaca" }}>
        <p style={{ margin: 0, color: "#dc2626", fontSize: "14px" }}>{result?.messages?.[0] || "Unable to compute throughput."}</p>
      </div>
    );
  }

  const weeklySqft = result.weeklySqft || 0;
  const weeklyUnits = result.throughput * (factory.hoursPerWeek || 40);
  const yearlySqft = weeklySqft * 52;

  return (
    <div>
      {/* Primary throughput banner */}
      {factory.sqftPerUnit > 0 && (
        <div style={{ background: "linear-gradient(135deg, #059669, #047857)", borderRadius: "10px", padding: "20px 24px", marginBottom: "16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "11px", fontWeight: 600, color: "rgba(255,255,255,0.7)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "4px" }}>Weekly Throughput</div>
            <div style={{ fontSize: "32px", fontWeight: 700, color: "#fff" }}>{weeklySqft.toLocaleString(undefined, { maximumFractionDigits: 0 })} <span style={{ fontSize: "18px", fontWeight: 500 }}>sqft/week</span></div>
          </div>
          <div style={{ textAlign: "right", color: "rgba(255,255,255,0.85)", fontSize: "13px", lineHeight: 1.8 }}>
            <div>{weeklyUnits.toFixed(1)} units/week × {factory.sqftPerUnit} sqft/unit</div>
            <div style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>{yearlySqft.toLocaleString(undefined, { maximumFractionDigits: 0 })} sqft/year</div>
          </div>
        </div>
      )}

      {/* KPI cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "16px" }}>
        {[
          { label: "Hourly Rate", value: `${result.throughput.toFixed(2)}`, unit: "units/hr", color: "#2563eb", bg: "#eff6ff" },
          { label: "Weekly Units", value: `${weeklyUnits.toFixed(1)}`, unit: `units (${factory.hoursPerWeek}hrs)`, color: "#7c3aed", bg: "#f5f3ff" },
          { label: "Space Used", value: `${(result.totalSqft / factory.totalSqft * 100).toFixed(0)}%`, unit: `${result.totalSqft.toLocaleString()} / ${factory.totalSqft.toLocaleString()} sqft`, color: "#0891b2", bg: "#ecfeff" },
          { label: "Bottleneck", value: result.bottleneck, unit: "", color: "#dc2626", bg: "#fef2f2" },
        ].map(kpi => (
          <div key={kpi.label} style={{ background: kpi.bg, borderRadius: "8px", padding: "14px 16px" }}>
            <div style={{ fontSize: "11px", fontWeight: 600, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "4px" }}>{kpi.label}</div>
            <div style={{ fontSize: "20px", fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
            {kpi.unit && <div style={{ fontSize: "11px", color: "#9ca3af" }}>{kpi.unit}</div>}
          </div>
        ))}
      </div>

      {/* Status messages */}
      <div style={{ background: "#f9fafb", borderRadius: "8px", padding: "12px 16px", marginBottom: "20px" }}>
        {result.messages.map((m, i) => (
          <div key={i} style={{ fontSize: "13px", color: "#4b5563", padding: "2px 0" }}>{m}</div>
        ))}
      </div>

      {/* Allocation table */}
      <h3 style={{ fontSize: "15px", fontWeight: 600, color: "#374151", marginBottom: "10px" }}>Optimal Allocation</h3>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
        <thead>
          <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
            {["Workcell", "Instances", "Capacity (units/hr)", "Effective Rate", "Utilization", "Total Sqft", "Total Labor"].map(h => (
              <th key={h} style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.allocation.filter(a => a.count > 0).map((a, i) => {
            const utilPct = (a.utilization * 100).toFixed(0);
            const isBottleneck = a.name === result.bottleneck;
            const barColor = a.utilization > 0.9 ? "#dc2626" : a.utilization > 0.7 ? "#f59e0b" : "#16a34a";
            return (
              <tr key={i} style={{ borderBottom: "1px solid #f3f4f6", background: isBottleneck ? "#fef2f2" : "transparent" }}>
                <td style={{ padding: "8px 10px", fontWeight: isBottleneck ? 700 : 500 }}>
                  {a.name} {isBottleneck && <span style={{ fontSize: "10px", color: "#dc2626", fontWeight: 600 }}>BOTTLENECK</span>}
                </td>
                <td style={{ padding: "8px 10px", fontWeight: 600 }}>{a.count}</td>
                <td style={{ padding: "8px 10px" }}>{a.totalCapacity.toFixed(1)}</td>
                <td style={{ padding: "8px 10px" }}>{a.effectiveRate.toFixed(1)}</td>
                <td style={{ padding: "8px 10px", width: "140px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <div style={{ flex: 1, height: "8px", background: "#e5e7eb", borderRadius: "4px", overflow: "hidden" }}>
                      <div style={{ width: `${utilPct}%`, height: "100%", background: barColor, borderRadius: "4px", transition: "width 0.3s" }} />
                    </div>
                    <span style={{ fontSize: "12px", fontWeight: 600, color: barColor, minWidth: "36px" }}>{utilPct}%</span>
                  </div>
                </td>
                <td style={{ padding: "8px 10px" }}>{(a.count * a.sqft).toLocaleString()}</td>
                <td style={{ padding: "8px 10px" }}>{a.count * a.laborRequired}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Scenario Heatmap ───────────────────────────────────────────────────────

function ScenarioComparison({ workcells }) {
  const scenarios = useMemo(() => {
    const results = [];
    const sqftRange = [5000, 10000, 15000, 20000, 30000, 50000];
    const laborRange = [10, 20, 30, 40, 50, 75];
    for (const sqft of sqftRange) {
      for (const labor of laborRange) {
        const r = solveFactory(workcells, { totalSqft: sqft, totalLabor: labor });
        results.push({ sqft, labor, throughput: r.throughput, bottleneck: r.bottleneck });
      }
    }
    return results;
  }, [workcells]);

  const maxT = Math.max(...scenarios.map(s => s.throughput), 1);
  const sqftVals = [...new Set(scenarios.map(s => s.sqft))];
  const laborVals = [...new Set(scenarios.map(s => s.labor))];

  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, color: "#374151", marginBottom: "6px" }}>Throughput Heatmap (units/hr)</h3>
      <p style={{ fontSize: "12px", color: "#9ca3af", margin: "0 0 12px 0" }}>Factory size vs. labor pool</p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "12px" }}>
          <thead>
            <tr>
              <th style={{ padding: "6px 10px", fontSize: "11px", color: "#6b7280" }}>Sqft \ Labor</th>
              {laborVals.map(l => <th key={l} style={{ padding: "6px 10px", fontSize: "11px", color: "#6b7280", textAlign: "center" }}>{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {sqftVals.map(sqft => (
              <tr key={sqft}>
                <td style={{ padding: "6px 10px", fontWeight: 600, color: "#374151" }}>{sqft.toLocaleString()}</td>
                {laborVals.map(labor => {
                  const s = scenarios.find(x => x.sqft === sqft && x.labor === labor);
                  const pct = s.throughput / maxT;
                  const bg = pct === 0 ? "#f9fafb" : `rgb(${Math.round(239 - pct * 200)},${Math.round(246 - pct * 100)},${Math.round(255 - pct * 20)})`;
                  return (
                    <td key={labor} style={{ padding: "8px 12px", textAlign: "center", background: bg, color: pct > 0.6 ? "#fff" : "#374151", fontWeight: pct > 0.5 ? 600 : 400, borderRadius: "2px", minWidth: "60px" }}>
                      {s.throughput.toFixed(1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Flow Diagram ───────────────────────────────────────────────────────────

function FlowDiagram({ workcells, result }) {
  if (!result || result.throughput === 0) return null;

  const cells = workcells.map(w => ({ ...w, inputs: parseInputs(w.inputType) }));
  const allOutputTypes = new Set(cells.map(c => c.outputType));
  const allInputTypes = new Set(cells.flatMap(c => c.inputs.map(i => i.type)));
  const rawTypes = [...allInputTypes].filter(t => !allOutputTypes.has(t));

  const layers = {};
  const visited = new Set();
  const assignLayer = (type, layer) => {
    if (visited.has(type)) return;
    visited.add(type);
    if (!layers[layer]) layers[layer] = [];
    for (const p of cells.filter(c => c.outputType === type)) {
      layers[layer].push(p);
      for (const inp of p.inputs) {
        if (!rawTypes.includes(inp.type)) assignLayer(inp.type, layer + 1);
      }
    }
  };
  (result.finalTypes || []).forEach(ft => assignLayer(ft, 0));

  const layerKeys = Object.keys(layers).map(Number).sort((a, b) => b - a);
  const maxNodes = Math.max(...layerKeys.map(k => layers[k].length), 1);
  const W = 140, H = 56, hGap = 50, vGap = 30;
  const svgW = Math.max(layerKeys.length * (W + hGap) + 40, 400);
  const svgH = Math.max(maxNodes * (H + vGap) + 40, 200);

  const pos = {};
  layerKeys.forEach((li, col) => {
    const nodes = layers[li];
    const totalH = nodes.length * H + (nodes.length - 1) * vGap;
    const startY = (svgH - totalH) / 2;
    nodes.forEach((n, row) => { pos[n.name] = { x: 20 + col * (W + hGap), y: startY + row * (H + vGap) }; });
  });

  const edges = [];
  cells.forEach(c => {
    const tgt = pos[c.name];
    if (!tgt) return;
    c.inputs.forEach(inp => {
      if (rawTypes.includes(inp.type)) return;
      cells.filter(s => s.outputType === inp.type).forEach(s => {
        if (pos[s.name]) edges.push({ from: pos[s.name], to: tgt, label: `×${inp.qty}` });
      });
    });
  });

  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, color: "#374151", marginBottom: "10px" }}>Material Flow</h3>
      <svg width={svgW} height={svgH} style={{ background: "#f9fafb", borderRadius: "8px" }}>
        <defs>
          <marker id="arrow" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="8" markerHeight="6" orient="auto">
            <path d="M0,0 L10,3 L0,6 Z" fill="#9ca3af" />
          </marker>
        </defs>
        {edges.map((e, i) => {
          const mx = (e.from.x + W + e.to.x) / 2;
          const my = (e.from.y + H / 2 + e.to.y + H / 2) / 2;
          return (
            <g key={i}>
              <line x1={e.from.x + W} y1={e.from.y + H / 2} x2={e.to.x} y2={e.to.y + H / 2}
                stroke="#9ca3af" strokeWidth="1.5" markerEnd="url(#arrow)" />
              <text x={mx} y={my - 4} textAnchor="middle" fontSize="10" fill="#6b7280" fontWeight="600">{e.label}</text>
            </g>
          );
        })}
        {Object.entries(pos).map(([name, p]) => {
          const alloc = result.allocation.find(a => a.name === name);
          const isB = name === result.bottleneck;
          return (
            <g key={name}>
              <rect x={p.x} y={p.y} width={W} height={H} rx={6}
                fill={isB ? "#fef2f2" : "#fff"} stroke={isB ? "#dc2626" : "#d1d5db"} strokeWidth={isB ? 2 : 1} />
              <text x={p.x + W / 2} y={p.y + 22} textAnchor="middle" fontSize="12" fontWeight="600" fill="#374151">{name}</text>
              {alloc && <text x={p.x + W / 2} y={p.y + 38} textAnchor="middle" fontSize="10" fill="#6b7280">×{alloc.count} | {alloc.totalCapacity.toFixed(1)}/hr</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── Tabs ───────────────────────────────────────────────────────────────────

function Tabs({ tabs, active, onSelect }) {
  return (
    <div style={{ display: "flex", gap: "2px", borderBottom: "2px solid #e5e7eb", marginBottom: "20px" }}>
      {tabs.map(t => (
        <button key={t.id} onClick={() => onSelect(t.id)} style={{
          padding: "10px 18px", fontSize: "13px", fontWeight: active === t.id ? 600 : 400,
          color: active === t.id ? "#2563eb" : "#6b7280", background: "transparent", border: "none",
          borderBottom: active === t.id ? "2px solid #2563eb" : "2px solid transparent",
          cursor: "pointer", marginBottom: "-2px",
        }}>{t.label}</button>
      ))}
    </div>
  );
}

// ─── Import/Export ──────────────────────────────────────────────────────────

function ConfigActions({ workcells, setWorkcells, factory, setFactory }) {
  const [showModal, setShowModal] = useState(null);
  const [importText, setImportText] = useState("");
  const [status, setStatus] = useState(null);

  const exportJson = JSON.stringify({ version: 2, exportedAt: new Date().toISOString(), factory, workcells }, null, 2);

  const handleCopy = () => {
    try {
      const ta = document.createElement("textarea");
      ta.value = exportJson; ta.style.position = "fixed"; ta.style.left = "-9999px";
      document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
      setStatus("Copied!"); setTimeout(() => setStatus(null), 2000);
    } catch { setStatus("Select all and copy manually"); }
  };

  const handleImport = () => {
    try {
      const config = JSON.parse(importText);
      if (config.workcells && Array.isArray(config.workcells)) setWorkcells(config.workcells);
      if (config.factory && typeof config.factory === "object") setFactory(config.factory);
      setShowModal(null); setImportText(""); setStatus("Loaded!"); setTimeout(() => setStatus(null), 2000);
    } catch { setStatus("Invalid JSON"); setTimeout(() => setStatus(null), 3000); }
  };

  const btn = { padding: "6px 14px", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "12px", cursor: "pointer", fontWeight: 500, background: "#fff", color: "#374151" };
  const overlay = { position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 };
  const modal = { background: "#fff", borderRadius: "12px", padding: "24px", width: "560px", maxHeight: "80vh", display: "flex", flexDirection: "column", boxShadow: "0 20px 60px rgba(0,0,0,0.2)" };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <button onClick={() => setShowModal("export")} style={{ ...btn, background: "#f0fdf4", borderColor: "#bbf7d0", color: "#16a34a" }}>Export</button>
        <button onClick={() => setShowModal("import")} style={{ ...btn, background: "#eff6ff", borderColor: "#bfdbfe", color: "#2563eb" }}>Import</button>
        {status && <span style={{ fontSize: "12px", color: status.includes("!") ? "#16a34a" : "#dc2626", fontWeight: 500 }}>{status}</span>}
      </div>
      {showModal === "export" && (
        <div style={overlay} onClick={() => setShowModal(null)}>
          <div style={modal} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "12px" }}>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 600 }}>Export Configuration</h3>
              <button onClick={() => setShowModal(null)} style={{ background: "none", border: "none", fontSize: "18px", cursor: "pointer", color: "#6b7280" }}>×</button>
            </div>
            <p style={{ fontSize: "13px", color: "#6b7280", margin: "0 0 10px 0" }}>Copy this JSON and save it to preserve your configuration.</p>
            <textarea readOnly value={exportJson} onFocus={e => e.target.select()}
              style={{ width: "100%", height: "280px", fontFamily: "monospace", fontSize: "12px", padding: "12px", border: "1px solid #d1d5db", borderRadius: "8px", resize: "vertical", boxSizing: "border-box", background: "#f9fafb" }} />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "12px" }}>
              <button onClick={() => setShowModal(null)} style={btn}>Close</button>
              <button onClick={handleCopy} style={{ ...btn, background: "#16a34a", color: "#fff", borderColor: "#16a34a" }}>Copy to Clipboard</button>
            </div>
          </div>
        </div>
      )}
      {showModal === "import" && (
        <div style={overlay} onClick={() => setShowModal(null)}>
          <div style={modal} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "12px" }}>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 600 }}>Import Configuration</h3>
              <button onClick={() => setShowModal(null)} style={{ background: "none", border: "none", fontSize: "18px", cursor: "pointer", color: "#6b7280" }}>×</button>
            </div>
            <p style={{ fontSize: "13px", color: "#6b7280", margin: "0 0 10px 0" }}>Paste a previously exported JSON configuration.</p>
            <textarea value={importText} onChange={e => setImportText(e.target.value)} placeholder='{"version": 2, ...}'
              style={{ width: "100%", height: "280px", fontFamily: "monospace", fontSize: "12px", padding: "12px", border: "1px solid #d1d5db", borderRadius: "8px", resize: "vertical", boxSizing: "border-box" }} />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "12px" }}>
              <button onClick={() => { setShowModal(null); setImportText(""); }} style={btn}>Cancel</button>
              <button onClick={handleImport} disabled={!importText.trim()} style={{ ...btn, background: importText.trim() ? "#2563eb" : "#9ca3af", color: "#fff", borderColor: importText.trim() ? "#2563eb" : "#9ca3af" }}>Load Config</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── Main App ───────────────────────────────────────────────────────────────

export default function FactorySimulator() {
  const [workcells, setWorkcells] = useState(DEFAULT_WORKCELLS);
  const [factory, setFactory] = useState(DEFAULT_FACTORY);
  const [activeTab, setActiveTab] = useState("results");

  const result = useMemo(() => solveFactory(workcells, factory), [workcells, factory]);

  const tabs = [
    { id: "results", label: "Optimization Results" },
    { id: "flow", label: "Material Flow" },
    { id: "scenarios", label: "Scenario Heatmap" },
  ];

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "24px", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      <div style={{ marginBottom: "24px", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ fontSize: "22px", fontWeight: 700, color: "#111827", margin: "0 0 4px 0" }}>Factory Throughput Simulator</h1>
          <p style={{ fontSize: "13px", color: "#6b7280", margin: 0 }}>Define workcells with input quantities, set constraints, and optimize throughput.</p>
        </div>
        <ConfigActions workcells={workcells} setWorkcells={setWorkcells} factory={factory} setFactory={setFactory} />
      </div>

      <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: "10px", padding: "20px", marginBottom: "16px" }}>
        <FactoryParams factory={factory} setFactory={setFactory} />
      </div>

      <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: "10px", padding: "20px", marginBottom: "16px" }}>
        <WorkcellEditor workcells={workcells} setWorkcells={setWorkcells} />
      </div>

      <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: "10px", padding: "20px" }}>
        <Tabs tabs={tabs} active={activeTab} onSelect={setActiveTab} />
        {activeTab === "results" && <ResultsDashboard result={result} factory={factory} />}
        {activeTab === "flow" && <FlowDiagram workcells={workcells} result={result} />}
        {activeTab === "scenarios" && <ScenarioComparison workcells={workcells} />}
      </div>
    </div>
  );
}
