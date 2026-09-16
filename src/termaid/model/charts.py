"""Data models for pie charts, quadrant charts, xy charts."""
from __future__ import annotations

from dataclasses import dataclass, field


# Pie charts
# ------------------------------------------------------------------------

@dataclass
class PieSlice:
    label: str
    value: float


@dataclass
class PieChart:
    title: str = ""
    show_data: bool = False
    slices: list[PieSlice] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Quadrant charts
# ------------------------------------------------------------------------

@dataclass
class QuadrantPoint:
    label: str
    x: float  # 0.0 to 1.0
    y: float  # 0.0 to 1.0


@dataclass
class QuadrantChart:
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    quadrant_1: str = "Q1"  # top-right
    quadrant_2: str = "Q2"  # top-left
    quadrant_3: str = "Q3"  # bottom-left
    quadrant_4: str = "Q4"  # bottom-right
    points: list[QuadrantPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# XY charts
# ------------------------------------------------------------------------

@dataclass
class XYDataset:
    label: str = ""
    values: list[float] = field(default_factory=list)
    chart_type: str = "bar"  # "bar" or "line"


@dataclass
class XYChart:
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    x_categories: list[str] = field(default_factory=list)
    x_range: tuple[float, float] | None = None  # min --> max
    y_range: tuple[float, float] | None = None
    datasets: list[XYDataset] = field(default_factory=list)
    horizontal: bool = False
    warnings: list[str] = field(default_factory=list)
