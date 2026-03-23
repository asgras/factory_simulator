"""
Factory Throughput Simulator
Ported from factory-simulator.jsx — business logic in Python, UI via Streamlit.

Run with: streamlit run factory_simulator.py
"""

import json
import math
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

# ─── Helpers ──────────────────────────────────────────────────────────────────
# Input format: "type1:qty1,type2:qty2" e.g. "roughed_panels:40,floor_cassettes"
# Quantity defaults to 1 if omitted

@dataclass
class MaterialInput:
    type: str
    qty: float = 1.0

def parse_inputs(input_type: str) -> list[MaterialInput]:
    """Parse comma-separated 'type:qty' string into a list of MaterialInput."""
    if not input_type:
        return []
    result = []
    for s in input_type.split(","):
        parts = s.strip().split(":")
        t = parts[0].strip()
        if not t:
            continue
        qty = float(parts[1]) if len(parts) > 1 and parts[1].strip() else 1.0
        result.append(MaterialInput(type=t, qty=qty))
    return result

def display_inputs(input_type: str) -> str:
    """Format inputs for display: 'raw_lumber ×2, cut_sheets ×1'."""
    return ", ".join(f"{i.type} ×{i.qty:g}" for i in parse_inputs(input_type))


# ─── Solver ───────────────────────────────────────────────────────────────────
# This is the core optimization engine. It:
# 1. Identifies final output types (not consumed by anything) and raw inputs (not produced)
# 2. Uses BFS to compute demand multipliers — how many units of each intermediate
#    are needed per unit of final output
# 3. Starts with minimum viable allocation (1 of each required cell)
# 4. Uses LP-based fractional scaling for initial allocation
# 5. Runs multiple greedy passes (singles, pairs, batch, chain, swaps) to maximize
#    throughput within sqft and labor constraints

@dataclass
class WorkcellAllocation:
    """Result for a single workcell after optimization."""
    name: str
    output_type: str
    input_type: str
    output_rate: float
    labor_required: int
    sqft: int
    count: int
    total_capacity: float
    effective_rate: float
    demand_mult: float
    utilization: float

@dataclass
class SolverResult:
    allocation: list[WorkcellAllocation]
    throughput: float
    bottleneck: str
    total_sqft: int
    total_labor: int
    messages: list[str]
    weekly_sqft: float
    final_types: list[str]
    raw_types: list[str]


def solve_factory(workcells: list[dict], factory: dict) -> SolverResult:
    """
    Main solver: given workcell definitions and factory constraints,
    find the allocation that maximizes throughput of final output types.
    """
    empty = SolverResult([], 0, "None", 0, 0, [], 0, [], [])

    if not workcells:
        empty.messages = ["No workcells defined."]
        return empty

    # Parse each workcell's inputs
    cells = []
    for w in workcells:
        cells.append({**w, "inputs": parse_inputs(w["inputType"])})

    # Identify final outputs (produced but never consumed) and raw inputs (consumed but never produced)
    all_output_types = set(c["outputType"] for c in cells)
    all_input_types = set(inp.type for c in cells for inp in c["inputs"])
    final_types = [t for t in all_output_types if t not in all_input_types]
    raw_types = [t for t in all_input_types if t not in all_output_types]

    if not final_types:
        empty.messages = ["No final output type found (circular dependency or missing workcells)."]
        return empty

    # Map: output_type -> list of cell indices that produce it
    producer_map: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(cells):
        producer_map[c["outputType"]].append(i)

    # ── BFS demand multiplier computation ──────────────────────────────────
    # Walks from final outputs upstream, computing how many units of each
    # intermediate type are needed per unit of final output.
    # Processes types only after ALL downstream consumers are done (handles fan-in).
    def compute_demand_multipliers(alloc: list[int]) -> dict[str, float]:
        demand_mult = {ft: 1.0 for ft in final_types}

        # Build consumer map: for type X, which output types consume X?
        consumed_by: dict[str, set[str]] = defaultdict(set)
        for out_type, prods in producer_map.items():
            for pi in prods:
                for inp in cells[pi]["inputs"]:
                    if inp.type not in raw_types:
                        consumed_by[inp.type].add(out_type)

        # BFS from final types upstream
        processed = set()
        queue = list(final_types)

        while queue:
            typ = queue.pop(0)
            if typ in processed:
                continue
            processed.add(typ)

            demand = demand_mult.get(typ, 0)
            prods = producer_map.get(typ, [])
            # Total capacity of all active producers of this type
            total_cap = sum(
                alloc[pi] * cells[pi]["outputRate"]
                for pi in prods if alloc[pi] > 0
            )

            for pi in prods:
                if alloc[pi] == 0:
                    continue
                # Each producer's share of demand is proportional to its capacity
                share = (alloc[pi] * cells[pi]["outputRate"]) / total_cap if total_cap > 0 else 0
                producer_demand = demand * share
                for inp in cells[pi]["inputs"]:
                    if inp.type in raw_types:
                        continue
                    # Accumulate: if this producer needs qty units of inp per output,
                    # then upstream must produce qty * producer_demand per unit throughput
                    demand_mult[inp.type] = demand_mult.get(inp.type, 0) + inp.qty * producer_demand
                    # Only enqueue once ALL consumers have been processed
                    consumers = consumed_by.get(inp.type, set())
                    if all(c in processed for c in consumers) and inp.type not in processed:
                        queue.append(inp.type)

        return demand_mult

    def compute_throughput(alloc: list[int]):
        """
        Given an allocation (count per cell), compute the max achievable throughput.
        Throughput is limited by the type with the worst capacity/demand ratio.
        Returns throughput, capacities, effective rates, demand multipliers, and bottleneck type.
        """
        # Total capacity per type = sum of (count * rate) for all producers
        type_capacity: dict[str, float] = defaultdict(float)
        for i, c in enumerate(cells):
            if alloc[i] > 0:
                type_capacity[c["outputType"]] += alloc[i] * c["outputRate"]

        demand_mult = compute_demand_multipliers(alloc)

        # Throughput = min over all types of (capacity / demand_multiplier)
        throughput = float("inf")
        bottleneck_type = None
        for typ, demand in demand_mult.items():
            if demand > 0:
                cap = type_capacity.get(typ, 0)
                max_t = cap / demand
                if max_t < throughput:
                    throughput = max_t
                    bottleneck_type = typ

        if not math.isfinite(throughput):
            throughput = 0

        # Effective rate = how much of each type is actually produced at this throughput
        effective_rate = {typ: throughput * (demand_mult.get(typ, 0)) for typ in demand_mult}

        return throughput, type_capacity, effective_rate, demand_mult, bottleneck_type

    # ── Find minimum required cells ────────────────────────────────────────
    # Traces from final outputs upstream, picking the most efficient producer
    # at each step (best rate per resource cost)
    required: set[int] = set()
    def find_required(output_type: str):
        prods = producer_map.get(output_type, [])
        if not prods:
            return
        # Pick the producer with the best efficiency score
        best = max(prods, key=lambda pi: cells[pi]["outputRate"] / (cells[pi]["sqft"] + cells[pi]["laborRequired"] * 100))
        if best in required:
            return
        required.add(best)
        for inp in cells[best]["inputs"]:
            if inp.type not in raw_types:
                find_required(inp.type)

    for ft in final_types:
        find_required(ft)

    allocation = [1 if i in required else 0 for i in range(len(cells))]

    # Check if minimum allocation fits
    min_sqft = sum(allocation[i] * cells[i]["sqft"] for i in range(len(cells)))
    min_labor = sum(allocation[i] * cells[i]["laborRequired"] for i in range(len(cells)))
    if min_sqft > factory["totalSqft"] or min_labor > factory["totalLabor"]:
        return SolverResult(
            allocation=[WorkcellAllocation(
                name=c["name"], output_type=c["outputType"], input_type=c["inputType"],
                output_rate=c["outputRate"], labor_required=c["laborRequired"], sqft=c["sqft"],
                count=allocation[i], total_capacity=0, effective_rate=0, demand_mult=0, utilization=0,
            ) for i, c in enumerate(cells)],
            throughput=0, bottleneck="None", total_sqft=min_sqft, total_labor=min_labor,
            messages=[f"Factory too small or insufficient labor. Need at least {min_sqft} sqft and {min_labor} workers."],
            weekly_sqft=0, final_types=final_types, raw_types=raw_types,
        )

    # ── LP-based initial allocation ────────────────────────────────────────
    # Uses demand multipliers from baseline to compute how many instances of
    # each cell are needed per unit of throughput, then scales to fit constraints.
    base_dm = compute_demand_multipliers(allocation)

    cell_need_per_t = []
    for i, c in enumerate(cells):
        if i not in required:
            cell_need_per_t.append(0)
            continue
        d = base_dm.get(c["outputType"], 0)
        if d == 0:
            cell_need_per_t.append(0)
            continue
        prods = [pi for pi in producer_map.get(c["outputType"], []) if pi in required]
        if len(prods) == 1:
            cell_need_per_t.append(d / c["outputRate"])
        else:
            total_rate = sum(cells[pi]["outputRate"] for pi in prods)
            cell_need_per_t.append(d / total_rate)

    # Max fractional throughput = min(total_sqft / sqft_per_T, total_labor / labor_per_T)
    sqft_per_t = sum(cell_need_per_t[i] * cells[i]["sqft"] for i in range(len(cells)))
    labor_per_t = sum(cell_need_per_t[i] * cells[i]["laborRequired"] for i in range(len(cells)))

    if sqft_per_t > 0 and labor_per_t > 0:
        t_frac = min(factory["totalSqft"] / sqft_per_t, factory["totalLabor"] / labor_per_t)
        allocation = [
            max(1, int(t_frac * cell_need_per_t[i])) if cell_need_per_t[i] > 0 else 0
            for i in range(len(cells))
        ]

    # ── Resource usage helper ──────────────────────────────────────────────
    def current_usage(alloc):
        sq = sum(alloc[i] * cells[i]["sqft"] for i in range(len(cells)))
        lb = sum(alloc[i] * cells[i]["laborRequired"] for i in range(len(cells)))
        return sq, lb

    # ── Greedy refinement: singles ─────────────────────────────────────────
    # Tries adding one instance of each cell, picks the one that improves throughput most
    def greedy_singles(alloc, max_iter):
        for _ in range(max_iter):
            sq, lb = current_usage(alloc)
            current_tp = compute_throughput(alloc)[0]
            best_gain, best_idx = 0, -1
            for i in range(len(cells)):
                if sq + cells[i]["sqft"] > factory["totalSqft"] or lb + cells[i]["laborRequired"] > factory["totalLabor"]:
                    continue
                alloc[i] += 1
                gain = compute_throughput(alloc)[0] - current_tp
                alloc[i] -= 1
                if gain > best_gain + 1e-9:
                    best_gain, best_idx = gain, i
            if best_idx == -1 or best_gain <= 1e-9:
                break
            alloc[best_idx] += 1

    # ── Greedy refinement: pairs ───────────────────────────────────────────
    # Tries adding pairs of cells simultaneously (handles co-bottlenecks)
    def greedy_pairs(alloc, max_iter):
        for _ in range(max_iter):
            sq, lb = current_usage(alloc)
            current_tp = compute_throughput(alloc)[0]
            best_gain, best_move = 0, None
            for i in range(len(cells)):
                for j in range(i, len(cells)):
                    add_sq = cells[i]["sqft"] + cells[j]["sqft"]
                    add_lb = cells[i]["laborRequired"] + cells[j]["laborRequired"]
                    if sq + add_sq > factory["totalSqft"] or lb + add_lb > factory["totalLabor"]:
                        continue
                    alloc[i] += 1
                    alloc[j] += 1
                    gain = compute_throughput(alloc)[0] - current_tp
                    alloc[j] -= 1
                    alloc[i] -= 1
                    if gain > best_gain + 1e-9:
                        best_gain, best_move = gain, (i, j)
            if not best_move or best_gain <= 1e-9:
                break
            alloc[best_move[0]] += 1
            alloc[best_move[1]] += 1

    # ── Greedy refinement: batch ───────────────────────────────────────────
    # Finds all near-bottleneck types (within 2%) and adds one producer of each simultaneously
    def greedy_batch(alloc, max_iter):
        for _ in range(max_iter):
            sq, lb = current_usage(alloc)
            tp, type_cap, _, dm, _ = compute_throughput(alloc)
            if tp <= 0:
                break

            bottleneck_cells = []
            for typ in dm:
                cap = type_cap.get(typ, 0)
                ratio = cap / dm[typ] if dm[typ] > 0 else float("inf")
                if ratio < tp * 1.02:
                    prods = [pi for pi in producer_map.get(typ, []) if alloc[pi] > 0 or pi in required]
                    if prods:
                        best = min(prods, key=lambda pi: cells[pi]["sqft"] + cells[pi]["laborRequired"])
                        bottleneck_cells.append(best)

            if len(bottleneck_cells) < 2:
                break
            unique = list(set(bottleneck_cells))
            add_sq = sum(cells[i]["sqft"] for i in unique)
            add_lb = sum(cells[i]["laborRequired"] for i in unique)

            if sq + add_sq > factory["totalSqft"] or lb + add_lb > factory["totalLabor"]:
                # Try subsets — drop the most expensive cell one at a time
                found = False
                for drop in range(len(unique)):
                    subset = [u for idx, u in enumerate(unique) if idx != drop]
                    sub_sq = sum(cells[i]["sqft"] for i in subset)
                    sub_lb = sum(cells[i]["laborRequired"] for i in subset)
                    if sq + sub_sq <= factory["totalSqft"] and lb + sub_lb <= factory["totalLabor"]:
                        for i in subset:
                            alloc[i] += 1
                        gain = compute_throughput(alloc)[0] - tp
                        if gain > 1e-9:
                            found = True
                            break
                        else:
                            for i in subset:
                                alloc[i] -= 1
                if not found:
                    break
            else:
                for i in unique:
                    alloc[i] += 1
                gain = compute_throughput(alloc)[0] - tp
                if gain <= 1e-9:
                    for i in unique:
                        alloc[i] -= 1
                    break

    # ── Proportional chain scaling ─────────────────────────────────────────
    # Adds one of every required cell at once (scales proportionally)
    def greedy_chain(alloc, max_iter):
        req_arr = list(required)
        chain_sqft = sum(cells[i]["sqft"] for i in req_arr)
        chain_labor = sum(cells[i]["laborRequired"] for i in req_arr)
        for _ in range(max_iter):
            sq, lb = current_usage(alloc)
            if sq + chain_sqft > factory["totalSqft"] or lb + chain_labor > factory["totalLabor"]:
                break
            tp = compute_throughput(alloc)[0]
            for i in req_arr:
                alloc[i] += 1
            gain = compute_throughput(alloc)[0] - tp
            if gain <= 1e-9:
                for i in req_arr:
                    alloc[i] -= 1
                break

    # ── Swap optimization ──────────────────────────────────────────────────
    # Removes one non-bottleneck cell and uses freed resources for bottleneck cells
    def greedy_swaps(alloc, max_iter):
        for _ in range(max_iter):
            tp = compute_throughput(alloc)[0]
            best_gain, best_swap = 0, None
            for rem in range(len(cells)):
                if alloc[rem] <= 1:
                    continue
                alloc[rem] -= 1
                free_sq, free_lb = current_usage(alloc)
                for add in range(len(cells)):
                    if free_sq + cells[add]["sqft"] > factory["totalSqft"] or free_lb + cells[add]["laborRequired"] > factory["totalLabor"]:
                        continue
                    alloc[add] += 1
                    gain = compute_throughput(alloc)[0] - tp
                    if gain > best_gain + 1e-9:
                        best_gain, best_swap = gain, (rem, [add])
                    # Try adding a second cell
                    sq2, lb2 = current_usage(alloc)
                    for add2 in range(add, len(cells)):
                        if sq2 + cells[add2]["sqft"] > factory["totalSqft"] or lb2 + cells[add2]["laborRequired"] > factory["totalLabor"]:
                            continue
                        alloc[add2] += 1
                        gain2 = compute_throughput(alloc)[0] - tp
                        if gain2 > best_gain + 1e-9:
                            best_gain, best_swap = gain2, (rem, [add, add2])
                        alloc[add2] -= 1
                    alloc[add] -= 1
                alloc[rem] += 1
            if not best_swap or best_gain <= 1e-9:
                break
            alloc[best_swap[0]] -= 1
            for a in best_swap[1]:
                alloc[a] += 1

    # Run all optimization passes (same order as JS version)
    greedy_singles(allocation, 500)
    greedy_pairs(allocation, 200)
    greedy_batch(allocation, 100)
    greedy_chain(allocation, 50)
    greedy_swaps(allocation, 100)
    greedy_singles(allocation, 500)  # final cleanup

    # ── Build results ──────────────────────────────────────────────────────
    total_sqft = sum(allocation[i] * cells[i]["sqft"] for i in range(len(cells)))
    total_labor = sum(allocation[i] * cells[i]["laborRequired"] for i in range(len(cells)))
    throughput, type_capacity, effective_rate, demand_mult, bottleneck_type = compute_throughput(allocation)

    # Find the specific bottleneck cell (tightest producer of bottleneck type)
    bottleneck_idx = -1
    if bottleneck_type:
        min_slack = float("inf")
        for pi in producer_map.get(bottleneck_type, []):
            if allocation[pi] > 0:
                slack = allocation[pi] * cells[pi]["outputRate"] - demand_mult.get(cells[pi]["outputType"], 0) * throughput
                if slack < min_slack:
                    min_slack = slack
                    bottleneck_idx = pi

    weekly_sqft = throughput * factory.get("hoursPerWeek", 40) * factory.get("sqftPerUnit", 0)

    # Status messages
    messages = []
    sqft_util = total_sqft / factory["totalSqft"] * 100
    labor_util = total_labor / factory["totalLabor"] * 100
    messages.append(f"Space utilization: {sqft_util:.1f}% ({total_sqft:,} / {factory['totalSqft']:,} sqft)")
    messages.append(f"Labor utilization: {labor_util:.1f}% ({total_labor} / {factory['totalLabor']} workers)")
    if bottleneck_idx >= 0:
        messages.append(f"Bottleneck: {cells[bottleneck_idx]['name']}")

    rem_sqft = factory["totalSqft"] - total_sqft
    rem_labor = factory["totalLabor"] - total_labor
    if rem_sqft > 0 and rem_labor > 0:
        smallest_sqft = min(c["sqft"] for c in cells)
        smallest_labor = min(c["laborRequired"] for c in cells)
        if rem_labor < smallest_labor:
            messages.append(f"Remaining {rem_labor} worker(s) cannot staff any workcell (min: {smallest_labor})")
        elif rem_sqft < smallest_sqft:
            messages.append(f"Remaining {rem_sqft:,} sqft cannot fit any workcell (min: {smallest_sqft})")
        else:
            messages.append(f"Unused: {rem_sqft:,} sqft, {rem_labor} workers — adding more cells wouldn't improve throughput (co-bottleneck constraint)")
    elif rem_sqft <= 0 and rem_labor <= 0:
        messages.append("Both floor space and labor are fully allocated")
    elif rem_sqft <= 0:
        messages.append("Constraint: floor space is fully allocated")
    else:
        messages.append("Constraint: labor pool is fully allocated")

    # Build allocation result objects
    alloc_results = []
    for i, c in enumerate(cells):
        cap = allocation[i] * c["outputRate"]
        eff = effective_rate.get(c["outputType"], 0)
        util = min(1.0, eff / cap) if allocation[i] > 0 and cap > 0 else 0
        alloc_results.append(WorkcellAllocation(
            name=c["name"], output_type=c["outputType"], input_type=c["inputType"],
            output_rate=c["outputRate"], labor_required=c["laborRequired"], sqft=c["sqft"],
            count=allocation[i], total_capacity=cap, effective_rate=eff,
            demand_mult=demand_mult.get(c["outputType"], 0), utilization=util,
        ))

    return SolverResult(
        allocation=alloc_results, throughput=throughput,
        bottleneck=cells[bottleneck_idx]["name"] if bottleneck_idx >= 0 else "None",
        total_sqft=total_sqft, total_labor=total_labor, messages=messages,
        weekly_sqft=weekly_sqft, final_types=final_types, raw_types=raw_types,
    )


# ─── Streamlit UI ─────────────────────────────────────────────────────────────

def load_config(path: str) -> tuple[list[dict], dict]:
    """Load workcells and factory params from a JSON config file."""
    with open(path) as f:
        config = json.load(f)
    return config.get("workcells", []), config.get("factory", {})

def main():
    import streamlit as st
    st.set_page_config(page_title="Factory Throughput Simulator", layout="wide")
    st.title("Factory Throughput Simulator")
    st.caption("Define workcells with input quantities, set constraints, and optimize throughput.")

    # Load config from JSON as defaults
    config_path = Path(__file__).parent / "simulator_config.json"
    default_workcells, default_factory = load_config(config_path)

    # Initialize session state
    if "workcells" not in st.session_state:
        st.session_state.workcells = default_workcells
    if "factory" not in st.session_state:
        st.session_state.factory = {
            "totalSqft": default_factory.get("totalSqft", 15000),
            "totalLabor": default_factory.get("totalLabor", 30),
            "sqftPerUnit": default_factory.get("sqftPerUnit", 700),
            "hoursPerWeek": default_factory.get("hoursPerWeek", 40),
        }

    factory = st.session_state.factory

    # ── Factory parameters ─────────────────────────────────────────────────
    st.subheader("Factory Parameters")
    col1, col2 = st.columns(2)
    with col1:
        factory["totalSqft"] = st.slider("Factory Floor Area (sqft)", 1000, 100000, factory["totalSqft"], step=500)
        factory["sqftPerUnit"] = st.number_input("Sqft per Finished Unit", min_value=0, value=factory["sqftPerUnit"], step=10)
    with col2:
        factory["totalLabor"] = st.slider("Labor Pool (workers)", 1, 200, factory["totalLabor"], step=1)
        factory["hoursPerWeek"] = st.number_input("Production Hours per Week", min_value=1, max_value=168, value=factory["hoursPerWeek"], step=1)

    # ── Workcell editor ────────────────────────────────────────────────────
    st.subheader("Workcells")

    # Display current workcells in editable table
    workcells = st.session_state.workcells
    for idx, wc in enumerate(workcells):
        with st.expander(f"**{wc['name']}** — {display_inputs(wc['inputType'])} → {wc['outputType']}", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                wc["name"] = st.text_input("Name", wc["name"], key=f"name_{idx}")
                wc["inputType"] = st.text_input("Input Type (type:qty,type:qty)", wc["inputType"], key=f"input_{idx}")
            with c2:
                wc["outputType"] = st.text_input("Output Type", wc["outputType"], key=f"output_{idx}")
                wc["outputRate"] = st.number_input("Rate/hr", value=float(wc["outputRate"]), min_value=0.001, step=0.1, key=f"rate_{idx}")
            with c3:
                wc["laborRequired"] = st.number_input("Labor Required", value=int(wc["laborRequired"]), min_value=1, step=1, key=f"labor_{idx}")
                wc["sqft"] = st.number_input("Sqft", value=int(wc["sqft"]), min_value=10, step=10, key=f"sqft_{idx}")
            if st.button("Remove", key=f"rm_{idx}"):
                st.session_state.workcells.pop(idx)
                st.rerun()

    # Add workcell button
    if st.button("+ Add Workcell"):
        new_id = max((w.get("id", 0) for w in workcells), default=0) + 1
        st.session_state.workcells.append({
            "id": new_id, "name": "New Workcell", "inputType": "",
            "outputType": "", "outputRate": 1, "laborRequired": 1, "sqft": 100,
        })
        st.rerun()

    # ── Import/Export ──────────────────────────────────────────────────────
    with st.expander("Import / Export Config"):
        export_data = json.dumps({"version": 2, "factory": factory, "workcells": workcells}, indent=2)
        st.download_button("Download Config JSON", export_data, "factory_config.json", "application/json")
        uploaded = st.file_uploader("Import Config JSON", type=["json"])
        if uploaded:
            config = json.loads(uploaded.read())
            if "workcells" in config:
                st.session_state.workcells = config["workcells"]
            if "factory" in config:
                st.session_state.factory = config["factory"]
            st.rerun()

    # ── Solve & display results ────────────────────────────────────────────
    st.divider()
    result = solve_factory(workcells, factory)

    if result.throughput == 0:
        st.error(result.messages[0] if result.messages else "Unable to compute throughput.")
        return

    # Throughput banner
    weekly_units = result.throughput * factory.get("hoursPerWeek", 40)
    yearly_sqft = result.weekly_sqft * 52

    if factory.get("sqftPerUnit", 0) > 0:
        st.metric("Weekly Throughput", f"{result.weekly_sqft:,.0f} sqft/week",
                   delta=f"{yearly_sqft:,.0f} sqft/year")

    # KPI cards
    tab_results, tab_flow, tab_heatmap = st.tabs(["Optimization Results", "Material Flow", "Scenario Heatmap"])

    with tab_results:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Hourly Rate", f"{result.throughput:.2f} units/hr")
        k2.metric("Weekly Units", f"{weekly_units:.1f} units ({factory['hoursPerWeek']}hrs)")
        k3.metric("Space Used", f"{result.total_sqft / factory['totalSqft'] * 100:.0f}%",
                   delta=f"{result.total_sqft:,} / {factory['totalSqft']:,} sqft", delta_color="off")
        k4.metric("Bottleneck", result.bottleneck)

        # Status messages
        for msg in result.messages:
            st.info(msg)

        # Allocation table
        st.subheader("Optimal Allocation")
        active = [a for a in result.allocation if a.count > 0]
        table_data = []
        for a in active:
            util_pct = a.utilization * 100
            table_data.append({
                "Workcell": f"{'🔴 ' if a.name == result.bottleneck else ''}{a.name}",
                "Instances": a.count,
                "Capacity (units/hr)": round(a.total_capacity, 1),
                "Effective Rate": round(a.effective_rate, 1),
                "Utilization": f"{util_pct:.0f}%",
                "Total Sqft": f"{a.count * a.sqft:,}",
                "Total Labor": a.count * a.labor_required,
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        # Utilization bar chart
        st.subheader("Utilization by Workcell")
        chart_data = {a.name: a.utilization * 100 for a in active}
        st.bar_chart(chart_data, horizontal=True)

    with tab_flow:
        # Text-based flow diagram
        st.subheader("Material Flow")
        cells_parsed = [{"name": w["name"], "outputType": w["outputType"], "inputs": parse_inputs(w["inputType"])} for w in workcells]
        alloc_map = {a.name: a for a in result.allocation if a.count > 0}

        for c in cells_parsed:
            a = alloc_map.get(c["name"])
            if not a:
                continue
            input_str = " + ".join(f"{inp.type} ×{inp.qty:g}" for inp in c["inputs"])
            is_bn = "🔴" if c["name"] == result.bottleneck else "  "
            st.text(f"{is_bn} [{input_str}] → **{c['name']}** ×{a.count} ({a.total_capacity:.1f}/hr) → {c['outputType']}")

        # Show raw inputs and final outputs
        st.markdown(f"**Raw inputs:** {', '.join(result.raw_types)}")
        st.markdown(f"**Final outputs:** {', '.join(result.final_types)}")

    with tab_heatmap:
        st.subheader("Throughput Heatmap (units/hr)")
        st.caption("Factory size vs. labor pool")
        sqft_range = [5000, 10000, 15000, 20000, 30000, 50000]
        labor_range = [10, 20, 30, 40, 50, 75]

        # Build heatmap data
        heatmap = {}
        for sqft in sqft_range:
            row = {}
            for labor in labor_range:
                r = solve_factory(workcells, {"totalSqft": sqft, "totalLabor": labor,
                                              "sqftPerUnit": factory.get("sqftPerUnit", 0),
                                              "hoursPerWeek": factory.get("hoursPerWeek", 40)})
                row[f"{labor} workers"] = round(r.throughput, 2)
            heatmap[f"{sqft:,} sqft"] = row

        import pandas as pd
        df = pd.DataFrame(heatmap).T
        st.dataframe(df.style.background_gradient(cmap="YlOrRd", axis=None), use_container_width=True)

if __name__ == "__main__":
    main()
