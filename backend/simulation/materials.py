"""Material types that flow through the factory and are consumed/transformed."""

from dataclasses import dataclass, field
from enum import Enum


class MaterialType(str, Enum):
    RAW_LUMBER = "raw_lumber"
    RAW_SHEET_GOODS = "raw_sheet_goods"
    CUT_LUMBER = "cut_lumber"
    CUT_SHEETS = "cut_sheets"
    INSULATION = "insulation"
    DRYWALL_SHEETS = "drywall_sheets"
    MEP_ROUGH_MATERIALS = "mep_rough_materials"
    TRIM_MATERIALS = "trim_materials"
    FASTENERS = "fasteners"
    LVL_BEAMS = "lvl_beams"
    TJI_JOISTS = "tji_joists"


MATERIAL_UNITS = {
    MaterialType.RAW_LUMBER: "board-feet",
    MaterialType.RAW_SHEET_GOODS: "sheets",
    MaterialType.CUT_LUMBER: "cut pieces",
    MaterialType.CUT_SHEETS: "cut pieces",
    MaterialType.INSULATION: "batts",
    MaterialType.DRYWALL_SHEETS: "sheets",
    MaterialType.MEP_ROUGH_MATERIALS: "kits",
    MaterialType.TRIM_MATERIALS: "kits",
    MaterialType.FASTENERS: "boxes",
    MaterialType.LVL_BEAMS: "pieces",
    MaterialType.TJI_JOISTS: "pieces",
}


@dataclass
class Material:
    material_type: MaterialType
    quantity: float
    created_at: float = 0.0  # sim time
    id: str = ""

    @property
    def unit(self) -> str:
        return MATERIAL_UNITS.get(self.material_type, "units")
