"""Default factory configurations for each ramp phase."""

RAMP_PLAN = {
    "day_1": {
        "station_counts": {
            "easy_frame_saw": 1,
            "hundegger_saw": 0,
            "onsrud_cnc": 1,
            "manual_framing_table": 2,
            "acadia_workcell": 0,
            "floor_cassette_bay": 1,
            "integration_bay": 1,
            "finishing_bay": 3,
            "kitting_area": 1,
            "module_exit": 1,
        },
        "target_sf_per_week": 1000,
        "total_headcount_estimate": 25,
        "crew_skill_factor": 1.3,  # new crews are 30% slower
    },
    "day_90": {
        "station_counts": {
            "easy_frame_saw": 1,
            "hundegger_saw": 0,
            "onsrud_cnc": 1,
            "manual_framing_table": 4,
            "acadia_workcell": 0,
            "floor_cassette_bay": 2,
            "integration_bay": 2,
            "finishing_bay": 6,
            "kitting_area": 1,
            "module_exit": 1,
        },
        "target_sf_per_week": 2000,
        "total_headcount_estimate": 45,
        "crew_skill_factor": 1.1,
    },
    "day_180": {
        "station_counts": {
            "easy_frame_saw": 0,
            "hundegger_saw": 1,
            "onsrud_cnc": 1,
            "manual_framing_table": 4,
            "acadia_workcell": 1,
            "floor_cassette_bay": 3,
            "integration_bay": 3,
            "finishing_bay": 12,
            "kitting_area": 1,
            "module_exit": 1,
        },
        "target_sf_per_week": 4000,
        "total_headcount_estimate": 70,
        "crew_skill_factor": 1.0,
    },
}

DEFAULT_MODULE = {
    "name": "CCW Module",
    "width_ft": 13.5,
    "length_ft": 54,
    "sf": 715,
    "panels_per_module": 40,
    "weight_tons": 15,
}

DEFAULT_SHIFT = {
    "hours_per_shift": 9,
    "shifts_per_day": 1,
    "production_days_per_week": 5,
}

DEFAULT_BUFFERS = {
    "cut_lumber": {"capacity": 40, "storage_method": "material_cart", "position": (90, 90)},
    "cut_sheets": {"capacity": 16, "storage_method": "material_cart", "position": (170, 90)},
    "panel_buffer": {"capacity": 60, "storage_method": "panel_cart", "position": (180, 160)},
    "floor_cassette": {"capacity": 1, "storage_method": "floor", "position": (80, 190)},
    "module_staging": {"capacity": 1, "storage_method": "floor", "position": (120, 220)},
    "module_yard": {"capacity": 8, "storage_method": "mod_cribs", "position": (200, 275)},
}

DEFAULT_FACILITY = {
    "width_ft": 400,
    "depth_ft": 275,
    "usable_production_sf": 65_000,
}

DEFAULT_ABSENTEEISM_RATE = 0.08

DEFAULT_BREAKDOWN = {
    "easy_frame_saw": {"mtbf_hours": 200, "repair_hours": 4},
    "hundegger_saw": {"mtbf_hours": 300, "repair_hours": 6},
    "onsrud_cnc": {"mtbf_hours": 300, "repair_hours": 6},
}
