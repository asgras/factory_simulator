"""CAPEX calculation from station and resource configurations."""


# Resource CAPEX per unit
RESOURCE_CAPEX = {
    "gantry_crane_module_matrix": 25_000,
    "forklift": 35_000,
    "tugger": 25_000,
    "field_lift_pro": 15_000,
    "scissor_lift": 8_000,
    "wav": 10_000,
    "panel_cart": 2_000,
    "material_cart": 500,
}


def compute_capex(station_counts: dict[str, int], station_defs: dict, resource_counts: dict[str, int]) -> dict:
    """Compute total CAPEX from station definitions and resource counts."""
    total = 0.0
    breakdown = {}

    for station_type, count in station_counts.items():
        if station_type in station_defs:
            sdef = station_defs[station_type]
            unit_cost = sdef.get("capex_cost", 0)
            install = sdef.get("install_cost", 0)
            line_total = count * (unit_cost + install)
            breakdown[station_type] = {
                "count": count,
                "unit_capex": unit_cost,
                "install_cost": install,
                "line_total": line_total,
            }
            total += line_total

    resource_capex = {}
    resource_total = 0.0
    for res_name, count in resource_counts.items():
        per_unit = RESOURCE_CAPEX.get(res_name, 0)
        cost = count * per_unit
        resource_capex[res_name] = {"count": count, "per_unit": per_unit, "total": cost}
        resource_total += cost

    breakdown["shared_resources"] = resource_capex
    total += resource_total

    return {"total": total, "breakdown": breakdown, "resource_total": resource_total}
