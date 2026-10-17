from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sheet:
    stock_id: int
    label: str
    width: float
    height: float
    quantity: int = 1


@dataclass(frozen=True)
class Part:
    label: str
    width: float
    height: float
    quantity: int = 1
    rotation_allowed: bool = True


@dataclass(frozen=True)
class Placement:
    label: str
    x: float
    y: float
    width: float
    height: float
    rotated: bool = False


@dataclass
class PlannedSheet:
    stock_id: int
    label: str
    width: float
    height: float
    placements: list[Placement] = field(default_factory=list)

    @property
    def used_area(self) -> float:
        return sum(item.width * item.height for item in self.placements)

    @property
    def efficiency(self) -> float:
        return self.used_area / (self.width * self.height) if self.width and self.height else 0


@dataclass(frozen=True)
class CuttingPlan:
    sheets: list[PlannedSheet]
    unplaced: list[Part]


def optimize_cutting(sheets: list[Sheet], parts: list[Part], kerf: float = 3.0) -> CuttingPlan:
    """Place rectangular parts using a deterministic best-area guillotine heuristic."""
    available = [
        PlannedSheet(sheet.stock_id, f"{sheet.label} #{copy_index + 1}", sheet.width, sheet.height)
        for sheet in sheets
        for copy_index in range(max(0, sheet.quantity))
    ]
    free_rectangles: list[list[tuple[float, float, float, float]]] = [
        [(0.0, 0.0, sheet.width, sheet.height)] for sheet in available
    ]
    requested = [
        Part(part.label, part.width, part.height, 1, part.rotation_allowed)
        for part in parts
        for _ in range(max(0, part.quantity))
    ]
    requested.sort(key=lambda item: (item.width * item.height, max(item.width, item.height)), reverse=True)
    unplaced: list[Part] = []
    gap = max(0.0, kerf)

    for part in requested:
        best: tuple[float, int, int, float, float, bool] | None = None
        orientations = [(part.width, part.height, False)]
        if part.rotation_allowed and part.width != part.height:
            orientations.append((part.height, part.width, True))
        for sheet_index, rectangles in enumerate(free_rectangles):
            for rectangle_index, (_x, _y, width, height) in enumerate(rectangles):
                for part_width, part_height, rotated in orientations:
                    if part_width <= width + 1e-8 and part_height <= height + 1e-8:
                        waste = width * height - part_width * part_height
                        candidate = (waste, sheet_index, rectangle_index, part_width, part_height, rotated)
                        if best is None or candidate < best:
                            best = candidate
        if best is None:
            unplaced.append(part)
            continue
        _waste, sheet_index, rectangle_index, part_width, part_height, rotated = best
        x, y, width, height = free_rectangles[sheet_index].pop(rectangle_index)
        available[sheet_index].placements.append(
            Placement(part.label, x, y, part_width, part_height, rotated)
        )
        right_width = width - part_width - gap
        lower_height = height - part_height - gap
        if right_width > 0:
            free_rectangles[sheet_index].append(
                (x + part_width + gap, y, right_width, part_height)
            )
        if lower_height > 0:
            free_rectangles[sheet_index].append((x, y + part_height + gap, width, lower_height))

    used = [sheet for sheet in available if sheet.placements]
    return CuttingPlan(used, unplaced)
