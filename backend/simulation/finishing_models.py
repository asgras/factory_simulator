"""Finishing bay schedule providers — simple model and scheduler import."""

import json
from typing import Protocol
from .distributions import NormalDistribution, FixedDistribution, Distribution
from .entities import Entity


class FinishingBayScheduleProvider(Protocol):
    """Interface for providing detailed finishing bay schedules."""

    def get_bay_duration(self, module: Entity) -> Distribution: ...

    def get_daily_crew_requirements(self, module: Entity, day_in_bay: int) -> dict[str, int]: ...

    def get_resource_requirements(self, module: Entity, day_in_bay: int) -> list[str]: ...


class SimpleFinishingModel:
    """Default: 9 production days, flat crew of 2-3 per bay."""

    def get_bay_duration(self, module: Entity) -> NormalDistribution:
        return NormalDistribution(mean=4320, std=480)  # 9 days in minutes

    def get_daily_crew_requirements(self, module: Entity, day_in_bay: int) -> dict[str, int]:
        return {"general_finisher": 3}

    def get_resource_requirements(self, module: Entity, day_in_bay: int) -> list[str]:
        if day_in_bay in [1, 2]:  # MEP rough
            return ["scissor_lift"]
        return []


class SchedulerImportModel:
    """Advanced: imports per-day finishing schedule from JSON."""

    def __init__(self, schedule_path: str):
        with open(schedule_path) as f:
            self.schedule = json.load(f)

    def get_bay_duration(self, module: Entity) -> FixedDistribution:
        total_days = len(self.schedule["finishing_schedule"])
        return FixedDistribution(total_days * 540)  # days × minutes per shift

    def get_daily_crew_requirements(self, module: Entity, day_in_bay: int) -> dict[str, int]:
        entries = self.schedule["finishing_schedule"]
        if day_in_bay < len(entries):
            return entries[day_in_bay]["crew"]
        return {}

    def get_resource_requirements(self, module: Entity, day_in_bay: int) -> list[str]:
        entries = self.schedule["finishing_schedule"]
        if day_in_bay < len(entries):
            return entries[day_in_bay]["resources"]
        return []
