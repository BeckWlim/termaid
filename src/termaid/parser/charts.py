"""Mermaid parsers for pie charts, quadrant charts, xy charts."""
from __future__ import annotations

import re

from ..model.charts import PieChart, PieSlice, QuadrantChart, QuadrantPoint, XYChart, XYDataset


# Pie charts
# ------------------------------------------------------------------------
#
# Syntax:
#     pie [showData]
#         [title <text>]
#         "<label>" : <value>
#         ...

_SLICE_RE = re.compile(r'^\s*"([^"]+)"\s*:\s*([0-9]+(?:\.[0-9]*)?)$')


def parse_pie_chart(text: str) -> PieChart:
    """Parse a mermaid pie chart definition."""
    lines = text.strip().splitlines()
    chart = PieChart()

    if not lines:
        return chart

    # Parse header line: pie [showData]
    header = lines[0].strip()
    if "showData" in header:
        chart.show_data = True

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        # Strip comments
        comment_idx = stripped.find("%%")
        if comment_idx >= 0:
            stripped = stripped[:comment_idx].strip()
            if not stripped:
                continue

        # Title
        if stripped.lower().startswith("title "):
            chart.title = stripped[6:].strip()
            continue

        # Slice: "Label" : value
        m = _SLICE_RE.match(stripped)
        if m:
            label = m.group(1)
            value = float(m.group(2))
            if value <= 0:
                chart.warnings.append(f"Pie slice value must be positive: {label} = {value}")
                continue
            chart.slices.append(PieSlice(label=label, value=value))
            continue

        # Unrecognized line
        if stripped:
            chart.warnings.append(f"Unrecognized line: {stripped}")

    return chart


# Quadrant charts
# ------------------------------------------------------------------------
#
# Syntax:
#     quadrantChart
#         title Effort vs Impact
#         x-axis Low Effort --> High Effort
#         y-axis Low Impact --> High Impact
#         quadrant-1 Do First
#         quadrant-2 Plan
#         quadrant-3 Delegate
#         quadrant-4 Eliminate
#         Task A: [0.8, 0.9]
#         Task B: [0.2, 0.3]

def parse_quadrant(text: str) -> QuadrantChart:
    """Parse a mermaid quadrant chart definition."""
    lines = text.strip().splitlines()
    qc = QuadrantChart()

    if not lines:
        return qc

    for line in lines[1:]:  # skip "quadrantChart" header
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        if lower.startswith("title "):
            qc.title = stripped[6:].strip()
        elif lower.startswith("x-axis "):
            # "x-axis Low --> High" or just "x-axis Label"
            label = stripped[7:].strip()
            qc.x_label = label.replace(" --> ", " -> ")
        elif lower.startswith("y-axis "):
            label = stripped[7:].strip()
            qc.y_label = label.replace(" --> ", " -> ")
        elif lower.startswith("quadrant-1 "):
            qc.quadrant_1 = stripped[11:].strip()
        elif lower.startswith("quadrant-2 "):
            qc.quadrant_2 = stripped[11:].strip()
        elif lower.startswith("quadrant-3 "):
            qc.quadrant_3 = stripped[11:].strip()
        elif lower.startswith("quadrant-4 "):
            qc.quadrant_4 = stripped[11:].strip()
        else:
            # Try to parse as a point: "Label: [x, y]"
            m = re.match(r'^(.+?):\s*\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]', stripped)
            if m:
                label = m.group(1).strip()
                x = float(m.group(2))
                y = float(m.group(3))
                qc.points.append(QuadrantPoint(label=label, x=x, y=y))

    return qc


# XY charts
# ------------------------------------------------------------------------
#
# Syntax:
#     xychart-beta [horizontal]
#         title "Revenue"
#         x-axis [Q1, Q2, Q3, Q4]
#         x-axis "Month" [Jan, Feb, Mar]
#         x-axis "Score" 0 --> 100
#         y-axis "Revenue (M)"
#         y-axis "Value" 0 --> 50
#         bar [10, 25, 18, 32]
#         line [8, 20, 15, 30]

# A number that float() is guaranteed to accept (rejects e.g. "0.1.2")
_NUM = r"-?\d+(?:\.\d+)?"


def parse_xychart(text: str) -> XYChart:
    """Parse a mermaid XY chart definition."""
    lines = text.strip().splitlines()
    chart = XYChart()

    if not lines:
        return chart

    # Parse header for orientation
    header = lines[0].strip().lower()
    if "horizontal" in header:
        chart.horizontal = True

    for line in lines[1:]:
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        if lower.startswith("title "):
            chart.title = _strip_quotes(stripped[6:].strip())
        elif lower.startswith("x-axis "):
            _parse_axis(stripped[7:].strip(), chart, is_x=True)
        elif lower.startswith("y-axis "):
            _parse_axis(stripped[7:].strip(), chart, is_x=False)
        elif lower.startswith("bar "):
            values = _parse_number_list(stripped[4:].strip())
            if values:
                chart.datasets.append(XYDataset(values=values, chart_type="bar"))
        elif lower.startswith("line "):
            values = _parse_number_list(stripped[5:].strip())
            if values:
                chart.datasets.append(XYDataset(values=values, chart_type="line"))

    return chart


def _parse_axis(rest: str, chart: XYChart, is_x: bool) -> None:
    """Parse axis config: title, categories, or numeric range."""
    # Try: "title" [cat1, cat2, ...]
    m = re.match(r'^"([^"]+)"\s*\[(.+)\]', rest)
    if m:
        if is_x:
            chart.x_label = m.group(1)
            chart.x_categories = [_strip_quotes(c.strip()) for c in m.group(2).split(",")]
        else:
            chart.y_label = m.group(1)
        return

    # Try: [cat1, cat2, ...]
    bracket = _parse_bracket_list(rest)
    if bracket is not None:
        if is_x:
            chart.x_categories = bracket
        return

    # Try: title min --> max  or  "title" min --> max
    m = re.match(rf'^(?:"([^"]+)"|(\S+))\s+({_NUM})\s*-->\s*({_NUM})', rest)
    if m:
        label = m.group(1) or m.group(2)
        lo, hi = float(m.group(3)), float(m.group(4))
        if is_x:
            chart.x_label = label
            chart.x_range = (lo, hi)
        else:
            chart.y_label = label
            chart.y_range = (lo, hi)
        return

    # Try: min --> max (no title)
    m = re.match(rf'^({_NUM})\s*-->\s*({_NUM})', rest)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if is_x:
            chart.x_range = (lo, hi)
        else:
            chart.y_range = (lo, hi)
        return

    # Just a title/label
    if is_x:
        chart.x_label = _strip_quotes(rest)
    else:
        chart.y_label = _strip_quotes(rest)


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _parse_bracket_list(text: str) -> list[str] | None:
    """Parse [item1, item2, ...] into a list of strings."""
    m = re.match(r'\[(.+)\]', text)
    if not m:
        return None
    items = m.group(1).split(",")
    return [_strip_quotes(item.strip()) for item in items if item.strip()]


def _parse_number_list(text: str) -> list[float]:
    """Parse [1, 2, 3] into a list of floats."""
    m = re.match(r'\[(.+)\]', text)
    if not m:
        return []
    items = m.group(1).split(",")
    result: list[float] = []
    for item in items:
        item = item.strip().lstrip("+")
        try:
            result.append(float(item))
        except ValueError:
            continue
    return result
