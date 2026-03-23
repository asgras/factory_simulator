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

    # Parse each workcell's inputs, separating overhead (no input AND no output)
    # from production cells. Overhead always gets exactly 1 instance and its
    # sqft/labor is subtracted from the factory budget before optimization.
    all_parsed = [{**w, "inputs": parse_inputs(w["inputType"])} for w in workcells]
    overhead = [c for c in all_parsed if not c["inputType"].strip() and not c["outputType"].strip()]
    cells = [c for c in all_parsed if c["inputType"].strip() or c["outputType"].strip()]

    overhead_sqft = sum(c["sqft"] for c in overhead)
    overhead_labor = sum(c["laborRequired"] for c in overhead)
    original_sqft = factory["totalSqft"]
    original_labor = factory["totalLabor"]
    # Create an adjusted factory budget for the production solver
    factory = {**factory,
               "totalSqft": factory["totalSqft"] - overhead_sqft,
               "totalLabor": factory["totalLabor"] - overhead_labor}

    if factory["totalSqft"] < 0 or factory["totalLabor"] < 0:
        empty.messages = [f"Overhead areas ({overhead_sqft:,} sqft, {overhead_labor} workers) exceed factory capacity."]
        # Include overhead in allocation with count=1
        for c in overhead:
            empty.allocation.append(WorkcellAllocation(
                name=c["name"], output_type="", input_type="", output_rate=0,
                labor_required=c["laborRequired"], sqft=c["sqft"],
                count=1, total_capacity=0, effective_rate=0, demand_mult=0, utilization=0,
            ))
        return empty

    # Identify final outputs (produced but never consumed) and raw inputs (consumed but never produced)
    all_output_types = set(c["outputType"] for c in cells if c["outputType"])
    all_input_types = set(inp.type for c in cells for inp in c["inputs"])
    final_types = [t for t in all_output_types if t not in all_input_types]
    raw_types = [t for t in all_input_types if t not in all_output_types]

    if not final_types:
        empty.messages = ["No final output type found (circular dependency or missing workcells)."]
        return empty

    # Map: output_type -> list of cell indices that produce it
    producer_map: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(cells):
        if c["outputType"]:
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
        candidate = [
            max(1, int(t_frac * cell_need_per_t[i])) if cell_need_per_t[i] > 0 else 0
            for i in range(len(cells))
        ]
        # Verify LP allocation fits — if not, fall back to minimum (1 of each required)
        cand_sqft = sum(candidate[i] * cells[i]["sqft"] for i in range(len(cells)))
        cand_labor = sum(candidate[i] * cells[i]["laborRequired"] for i in range(len(cells)))
        if cand_sqft <= factory["totalSqft"] and cand_labor <= factory["totalLabor"]:
            allocation = candidate
        # else: keep the minimum allocation (1 of each required), greedy passes will scale up

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
    # Finds all near-bottleneck types (within 2%) and adds one producer of each simultaneously.
    # When the full set doesn't fit, tries all subsets from largest to smallest.
    def greedy_batch(alloc, max_iter):
        from itertools import combinations
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
                # Try all subsets from largest to smallest (skip size < 2)
                found = False
                for size in range(len(unique) - 1, 1, -1):
                    for subset in combinations(unique, size):
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
                    if found:
                        break
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

    # Run optimization passes in a loop until throughput stops improving.
    # Each pass type can unlock improvements for subsequent passes (e.g. swaps
    # free resources that pairs can then use), so we repeat until convergence.
    prev_tp = -1
    for _round in range(10):
        greedy_singles(allocation, 500)
        greedy_pairs(allocation, 200)
        greedy_batch(allocation, 100)
        greedy_chain(allocation, 50)
        greedy_swaps(allocation, 100)
        tp = compute_throughput(allocation)[0]
        if tp <= prev_tp + 1e-9:
            break
        prev_tp = tp

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

    # outputRate is per-day, so throughput is units/day; weekly = 5 working days
    days_per_week = 5
    weekly_sqft = throughput * days_per_week * factory.get("sqftPerUnit", 0)

    # Status messages — report against original factory size (before overhead deduction)
    messages = []
    total_sqft_with_oh = total_sqft + overhead_sqft
    total_labor_with_oh = total_labor + overhead_labor
    sqft_util = total_sqft_with_oh / original_sqft * 100
    labor_util = total_labor_with_oh / original_labor * 100
    messages.append(f"Space utilization: {sqft_util:.1f}% ({total_sqft_with_oh:,} / {original_sqft:,} sqft)")
    messages.append(f"Labor utilization: {labor_util:.1f}% ({total_labor_with_oh} / {original_labor} workers)")
    if overhead:
        oh_names = ", ".join(c["name"] for c in overhead)
        messages.append(f"Overhead: {overhead_sqft:,} sqft, {overhead_labor} workers ({oh_names})")
    if bottleneck_idx >= 0:
        messages.append(f"Bottleneck: {cells[bottleneck_idx]['name']}")

    rem_sqft = original_sqft - total_sqft_with_oh
    rem_labor = original_labor - total_labor_with_oh
    if rem_sqft > 0 and rem_labor > 0:
        smallest_sqft = min(c["sqft"] for c in cells)
        smallest_labor = min(c["laborRequired"] for c in cells)
        if rem_labor < smallest_labor:
            messages.append(f"Remaining {rem_labor} worker(s) cannot staff any workcell (min required: {smallest_labor})")
        elif rem_sqft < smallest_sqft:
            messages.append(f"Remaining {rem_sqft:,} sqft cannot fit any workcell (min required: {smallest_sqft})")
        else:
            # Identify co-bottlenecked types to explain WHY adding doesn't help
            co_bn_types = []
            for typ, d in demand_mult.items():
                if d > 0:
                    cap = type_capacity.get(typ, 0)
                    ratio = cap / d
                    if ratio < throughput * 1.02:
                        co_bn_types.append(typ)
            # Find the total labor needed to add 1 producer of each co-bottleneck type
            bn_producers = set()
            for typ in co_bn_types:
                prods = [pi for pi in (producer_map.get(typ, [])) if allocation[pi] > 0]
                if prods:
                    bn_producers.add(min(prods, key=lambda pi: cells[pi]["laborRequired"]))
            needed_labor = sum(cells[pi]["laborRequired"] for pi in bn_producers)
            bn_names = [cells[pi]["name"] for pi in bn_producers]

            needed_sqft = sum(cells[pi]["sqft"] for pi in bn_producers)
            # Report whichever resource is actually the binding constraint
            labor_short = needed_labor > rem_labor
            sqft_short = needed_sqft > rem_sqft
            if labor_short and sqft_short:
                constraint = f"requiring {needed_labor} workers and {needed_sqft:,} sqft, but only {rem_labor} workers and {rem_sqft:,} sqft available"
            elif labor_short:
                constraint = f"requiring {needed_labor} workers, but only {rem_labor} available"
            else:
                constraint = f"requiring {needed_sqft:,} sqft, but only {rem_sqft:,} available"
            messages.append(
                f"Unused: {rem_sqft:,} sqft, {rem_labor} workers — "
                f"{len(co_bn_types)} stage{'s are' if len(co_bn_types) > 1 else ' is'} co-bottlenecked ({', '.join(bn_names)}). "
                f"All must be scaled together, {constraint}."
            )
    elif rem_sqft <= 0 and rem_labor <= 0:
        messages.append("Both floor space and labor are fully allocated")
    elif rem_sqft <= 0:
        messages.append("Constraint: floor space is fully allocated")
    else:
        messages.append("Constraint: labor pool is fully allocated")

    # Build allocation result objects — production cells
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

    # Add overhead cells (always 1 instance, no production role)
    for c in overhead:
        alloc_results.append(WorkcellAllocation(
            name=c["name"], output_type="", input_type="",
            output_rate=0, labor_required=c["laborRequired"], sqft=c["sqft"],
            count=1, total_capacity=0, effective_rate=0, demand_mult=0, utilization=0,
        ))

    return SolverResult(
        allocation=alloc_results, throughput=throughput,
        bottleneck=cells[bottleneck_idx]["name"] if bottleneck_idx >= 0 else "None",
        total_sqft=total_sqft_with_oh, total_labor=total_labor_with_oh, messages=messages,
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
    import pandas as pd

    # ── All inputs in a form — only reruns on "Apply Changes" ─────────────
    with st.form("config_form"):
        # Factory parameters
        st.subheader("Factory Parameters")
        col1, col2 = st.columns(2)
        with col1:
            form_totalSqft = st.slider("Factory Floor Area (sqft)", 1000, 100000, factory["totalSqft"], step=500)
            form_sqftPerUnit = st.number_input("Sqft per Finished Unit", min_value=0, value=factory["sqftPerUnit"], step=10)
        with col2:
            form_totalLabor = st.slider("Labor Pool (workers)", 1, 200, factory["totalLabor"], step=1)
            form_hoursPerWeek = st.number_input("Production Hours per Week", min_value=1, max_value=168, value=factory["hoursPerWeek"], step=1)

        # Workcell editor
        st.subheader("Workcells")
        st.caption("Workcells with both Input and Output left blank are treated as fixed overhead (e.g. travel lanes, offices). "
                   "They are always allocated exactly 1 instance and their space/labor is deducted before optimization.")
        workcells = st.session_state.workcells
        edit_df = pd.DataFrame([{
            "Name": w["name"],
            "Inputs (type:qty,...)": w["inputType"],
            "Output Type": w["outputType"],
            "Rate/day": float(w["outputRate"]) if w["outputRate"] else None,
            "Labor": int(w["laborRequired"]) if w["laborRequired"] else None,
            "Sqft Mode": w.get("sqftMode", "fixed"),
            "Sqft Value": float(w.get("sqftValue", w["sqft"])),
        } for w in workcells])

        edited = st.data_editor(
            edit_df, num_rows="dynamic", use_container_width=True, hide_index=True,
            column_config={
                "Name": st.column_config.TextColumn(width="medium"),
                "Inputs (type:qty,...)": st.column_config.TextColumn(width="large", help="Comma-separated, e.g. raw_lumber:2,cut_sheets"),
                "Output Type": st.column_config.TextColumn(width="medium"),
                "Rate/day": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.4f", help="Leave 0 or blank for overhead areas"),
                "Labor": st.column_config.NumberColumn(min_value=0, step=1, help="Leave 0 or blank for overhead areas"),
                "Sqft Mode": st.column_config.SelectboxColumn(options=["fixed", "%"], help="'fixed' = absolute sqft, '%' = percentage of factory floor area"),
                "Sqft Value": st.column_config.NumberColumn(min_value=0.1, step=1.0, format="%.1f", help="Sqft if fixed, or % of factory if '%' mode"),
            },
            key="workcell_editor",
        )

        submitted = st.form_submit_button("Apply Changes", type="primary", use_container_width=True)

    # Sync form values to session state when submitted
    if submitted:
        factory["totalSqft"] = form_totalSqft
        factory["totalLabor"] = form_totalLabor
        factory["sqftPerUnit"] = form_sqftPerUnit
        factory["hoursPerWeek"] = form_hoursPerWeek

        total_factory_sqft = form_totalSqft
        new_workcells = []
        for i, row in edited.iterrows():
            if pd.isna(row["Name"]) or not str(row["Name"]).strip():
                continue
            wc_id = workcells[i]["id"] if i < len(workcells) else (max((w.get("id", 0) for w in workcells), default=0) + i + 1)
            mode = str(row["Sqft Mode"]).strip() if pd.notna(row["Sqft Mode"]) else "fixed"
            raw_val = float(row["Sqft Value"]) if pd.notna(row["Sqft Value"]) else 100.0
            if mode == "%":
                resolved_sqft = max(1, int(total_factory_sqft * raw_val / 100))
            else:
                resolved_sqft = max(1, int(raw_val))
            input_type = str(row["Inputs (type:qty,...)"]).strip() if pd.notna(row["Inputs (type:qty,...)"]) else ""
            output_type = str(row["Output Type"]).strip() if pd.notna(row["Output Type"]) else ""
            is_overhead = not input_type and not output_type
            new_workcells.append({
                "id": wc_id,
                "name": str(row["Name"]).strip(),
                "inputType": input_type,
                "outputType": output_type,
                "outputRate": float(row["Rate/day"]) if pd.notna(row["Rate/day"]) and row["Rate/day"] else (0 if is_overhead else 1.0),
                "laborRequired": int(row["Labor"]) if pd.notna(row["Labor"]) else (0 if is_overhead else 1),
                "sqft": resolved_sqft,
                "sqftMode": mode,
                "sqftValue": raw_val,
            })
        st.session_state.workcells = new_workcells

    workcells = st.session_state.workcells

    # Show resolved sqft values when any workcell uses % mode
    if any(w.get("sqftMode") == "%" for w in workcells):
        st.caption("Resolved sqft: " + " | ".join(
            f"**{w['name']}**: {w['sqftValue']:.1f}% = {w['sqft']:,} sqft" if w.get("sqftMode") == "%" else f"**{w['name']}**: {w['sqft']:,} sqft"
            for w in workcells
        ))

    # ── Save / Load Configuration ─────────────────────────────────────────
    with st.expander("Save / Load Configuration"):
        save_col, load_col = st.columns(2)

        # Save: download as JSON with a custom filename
        with save_col:
            st.markdown("**Save configuration**")
            save_name = st.text_input("Filename", value="factory_config", placeholder="e.g. baseline_v2", key="save_name")
            filename = (save_name.strip().replace(" ", "_") or "factory_config") + ".json"
            export_data = json.dumps({"version": 2, "factory": factory, "workcells": workcells}, indent=2)
            st.download_button("Download Config", export_data, filename, "application/json", use_container_width=True)

        # Load: upload a JSON file (track file ID to avoid reprocessing on rerun)
        with load_col:
            st.markdown("**Load configuration**")
            uploaded = st.file_uploader("Upload JSON config", type=["json"], key="config_upload")
            if uploaded and uploaded.file_id != st.session_state.get("_last_upload_id"):
                st.session_state._last_upload_id = uploaded.file_id
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

    # Throughput is already in units/day (outputRate is per-day)
    days_per_week = 5
    daily_throughput = result.throughput
    weekly_units = result.throughput * days_per_week
    yearly_sqft = result.weekly_sqft * 52

    if factory.get("sqftPerUnit", 0) > 0:
        st.metric("Weekly Throughput", f"{result.weekly_sqft:,.0f} sqft/week",
                   delta=f"{yearly_sqft:,.0f} sqft/year")

    # KPI cards
    tab_results, tab_space, tab_flow, tab_heatmap = st.tabs(["Optimization Results", "Space Allocation", "Material Flow", "Scenario Heatmap"])

    with tab_results:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Daily Rate", f"{daily_throughput:.2f} units/day")
        k2.metric("Weekly Units", f"{weekly_units:.1f} units (5 days)")
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
                "Capacity (units/day)": round(a.total_capacity, 1),
                "Effective Rate (units/day)": round(a.effective_rate, 1),
                "Utilization": f"{util_pct:.0f}%",
                "Total Sqft": f"{a.count * a.sqft:,}",
                "Total Labor": a.count * a.labor_required,
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        # Utilization bar chart
        st.subheader("Utilization by Workcell")
        chart_data = {a.name: a.utilization * 100 for a in active}
        st.bar_chart(chart_data, horizontal=True)

    with tab_space:
        import plotly.express as px
        st.subheader("Factory Floor Space Allocation")

        # Build treemap data: one row per workcell instance group, plus unused space
        treemap_rows = []
        for a in active:
            total_sq = a.count * a.sqft
            treemap_rows.append({
                "name": f"{a.name} (×{a.count})",
                "category": "Workcells",
                "sqft": total_sq,
                "label": f"{a.name}<br>×{a.count} — {total_sq:,} sqft",
            })

        unused_sqft = factory["totalSqft"] - result.total_sqft
        if unused_sqft > 0:
            treemap_rows.append({
                "name": "Unused",
                "category": "Unused",
                "sqft": unused_sqft,
                "label": f"Unused<br>{unused_sqft:,} sqft",
            })

        import pandas as pd
        df_tree = pd.DataFrame(treemap_rows)
        fig = px.treemap(
            df_tree, path=["category", "name"], values="sqft",
            color="sqft", color_continuous_scale="Blues",
            custom_data=["label"],
        )
        fig.update_traces(
            texttemplate="%{customdata[0]}",
            textposition="middle center",
        )
        fig.update_layout(
            margin=dict(t=30, l=10, r=10, b=10),
            height=500,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        st.caption(f"Total factory: {factory['totalSqft']:,} sqft — "
                   f"Allocated: {result.total_sqft:,} sqft ({result.total_sqft / factory['totalSqft'] * 100:.1f}%) — "
                   f"Unused: {unused_sqft:,} sqft")

    with tab_flow:
        import plotly.graph_objects as go
        st.subheader("Material Flow")

        # Build Sankey: nodes are workcell names + raw input types + final output types
        alloc_map = {a.name: a for a in result.allocation if a.count > 0}
        cells_parsed = [{"name": w["name"], "outputType": w["outputType"], "inputs": parse_inputs(w["inputType"])} for w in workcells]

        # Collect unique node labels: raw inputs → workcells → final outputs
        node_labels = []
        node_index = {}
        def get_node(label):
            if label not in node_index:
                node_index[label] = len(node_labels)
                node_labels.append(label)
            return node_index[label]

        # Register raw inputs first, then workcells, then final outputs
        for t in result.raw_types:
            get_node(t)
        for c in cells_parsed:
            if c["name"] in alloc_map:
                get_node(c["name"])
        for t in result.final_types:
            get_node(f"[{t}]")

        # Build links
        sources, targets, values, link_labels = [], [], [], []
        for c in cells_parsed:
            a = alloc_map.get(c["name"])
            if not a:
                continue
            # Links from inputs → this workcell
            for inp in c["inputs"]:
                if inp.type in result.raw_types:
                    src = get_node(inp.type)
                else:
                    # Find which workcell produces this input type
                    producer = next((w["name"] for w in workcells if w["outputType"] == inp.type and w["name"] in alloc_map), None)
                    if not producer:
                        continue
                    src = get_node(producer)
                tgt = get_node(c["name"])
                flow_rate = a.effective_rate * inp.qty
                sources.append(src)
                targets.append(tgt)
                values.append(max(flow_rate, 0.01))
                link_labels.append(f"{inp.type} ×{inp.qty:g} = {flow_rate:.2f}/day")

            # Link from this workcell → final output (if applicable)
            if a.output_type in result.final_types:
                sources.append(get_node(c["name"]))
                targets.append(get_node(f"[{a.output_type}]"))
                values.append(max(a.effective_rate, 0.01))
                link_labels.append(f"{a.effective_rate:.2f}/day")

        # Color nodes: grey for raw, blue for workcells, green for final, red for bottleneck
        node_colors = []
        for label in node_labels:
            if label == result.bottleneck:
                node_colors.append("#dc2626")
            elif label in result.raw_types:
                node_colors.append("#9ca3af")
            elif label.startswith("["):
                node_colors.append("#16a34a")
            else:
                node_colors.append("#2563eb")

        fig = go.Figure(go.Sankey(
            node=dict(
                pad=20, thickness=20,
                label=[f"{l} (×{alloc_map[l].count})" if l in alloc_map else l for l in node_labels],
                color=node_colors,
            ),
            link=dict(
                source=sources, target=targets, value=values,
                label=link_labels,
                color="rgba(100,100,100,0.15)",
            ),
        ))
        fig.update_layout(
            margin=dict(t=20, l=10, r=10, b=10),
            height=450,
            font=dict(size=12),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Legend
        col1, col2, col3 = st.columns(3)
        col1.markdown(f"**Raw inputs:** {', '.join(result.raw_types)}")
        col2.markdown(f"**Final outputs:** {', '.join(result.final_types)}")
        col3.markdown(f"**Bottleneck:** {result.bottleneck}")

    with tab_heatmap:
        st.subheader("Throughput Heatmap (units/day)")
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
