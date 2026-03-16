"""Distance-based movement time calculations between stations."""

import math

# Movement speeds and setup times
MOVEMENT_SPEEDS = {
    "forklift":      {"speed_fps": 5, "setup_sec": 120},
    "tugger":        {"speed_fps": 2, "setup_sec": 600},
    "panel_cart":    {"speed_fps": 3, "setup_sec": 60},
    "material_cart": {"speed_fps": 3, "setup_sec": 30},
    "crane":         {"speed_fps": 1, "setup_sec": 180},
    "walk":          {"speed_fps": 4, "setup_sec": 0},
}


def euclidean_distance(from_pos: tuple[float, float], to_pos: tuple[float, float]) -> float:
    return math.sqrt((to_pos[0] - from_pos[0]) ** 2 + (to_pos[1] - from_pos[1]) ** 2)


def movement_time_seconds(from_pos: tuple[float, float], to_pos: tuple[float, float], movement_type: str) -> float:
    """Calculate movement time in seconds between two positions."""
    distance = euclidean_distance(from_pos, to_pos)
    s = MOVEMENT_SPEEDS[movement_type]
    return s["setup_sec"] + (distance / s["speed_fps"])


def movement_time_minutes(from_pos: tuple[float, float], to_pos: tuple[float, float], movement_type: str) -> float:
    """Calculate movement time in minutes between two positions."""
    return movement_time_seconds(from_pos, to_pos, movement_type) / 60.0
