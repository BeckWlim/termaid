"""Charts diagrams: models, parsing, layout, and drawing."""
from __future__ import annotations

from termaid.core.contracts import ParsedSource, RenderConfig, RenderResult

from dataclasses import dataclass, field
import re
from termaid.core.canvas import Canvas
from termaid.utils import display_width
from termaid.renderer.charset import ASCII, UNICODE, CharSet


# Model
# ------------------------------------------------------------------------

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


# Parsing
# ------------------------------------------------------------------------

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


# Layout and drawing
# ------------------------------------------------------------------------

# Pie charts
# ------------------------------------------------------------------------
#
# Draws per-slice horizontal bars with right-aligned labels,
# percentages, and optional raw values.

_FILL_CHARS = ["█", "░", "▒", "▚", "▞", "▄", "▀", "▌"]
_FILL_CHARS_ASCII = ["#", "*", "+", "~", ":", ".", "o", "="]

_PIECHART_BAR_WIDTH = 40
_MARGIN = 2


def render_pie_chart(
    diagram: PieChart,
    *,
    use_ascii: bool = False,
    max_width: int | None = None,
) -> Canvas:
    """Render a PieChart as a horizontal bar chart on a Canvas."""

    if not diagram.slices:
        canvas = Canvas(1, 1)
        return canvas

    total = sum(s.value for s in diagram.slices)
    fills = _FILL_CHARS_ASCII if use_ascii else _FILL_CHARS

    # Compute label column width
    max_label_len = max(display_width(s.label) for s in diagram.slices)
    label_col_w = max_label_len + _MARGIN

    # Compute suffix (percentage + optional value)
    suffixes: list[str] = []
    for s in diagram.slices:
        pct = s.value / total * 100
        if diagram.show_data:
            suffixes.append(f" {pct:5.1f}%  [{s.value:g}]")
        else:
            suffixes.append(f" {pct:5.1f}%")
    max_suffix_len = max(len(sf) for sf in suffixes)

    bar_left = label_col_w
    bar_width = _PIECHART_BAR_WIDTH
    if max_width is not None:
        bar_width = min(bar_width, max(1, max_width - bar_left - max_suffix_len - _MARGIN))
    canvas_w = max(bar_left + bar_width + max_suffix_len + _MARGIN,
                   display_width(diagram.title))
    title_rows = 2 if diagram.title else 0

    # Layout: title, stacked bar (3 rows), blank, per-slice bars
    stacked_top = _MARGIN + title_rows
    bars_top = stacked_top + 4  # stacked bar + labels row + blank
    canvas_h = bars_top + len(diagram.slices) + _MARGIN

    canvas = Canvas(canvas_w, canvas_h)

    # Title
    if diagram.title:
        title_col = max(0, (canvas_w - len(diagram.title)) // 2)
        canvas.put_text(_MARGIN, title_col, diagram.title, style="label")

    # Stacked bar showing parts of a whole
    stacked_w = bar_width
    stacked_left = bar_left + 1
    col = 0
    label_parts: list[tuple[int, int, str, str]] = []  # (start, width, label, fill)
    for i, s in enumerate(diagram.slices):
        fill = fills[i % len(fills)]
        seg_w = min(stacked_w - col, max(1, round(s.value / total * stacked_w)))
        # Clamp last segment to fill exactly
        if i == len(diagram.slices) - 1:
            seg_w = stacked_w - col
        if seg_w <= 0:
            continue
        for c in range(seg_w):
            canvas.put(stacked_top, stacked_left + col + c, fill, merge=False, style="node")
        pct = s.value / total * 100
        short_label = f"{s.label} {pct:.0f}%"
        label_parts.append((col, seg_w, short_label, fill))
        col += seg_w

    # Labels below the stacked bar: try full label, then just percentage
    label_row = stacked_top + 1
    for start, seg_w, short_label, fill in label_parts:
        lw = display_width(short_label)
        if lw <= seg_w:
            lx = stacked_left + start + (seg_w - lw) // 2
            canvas.put_text(label_row, lx, short_label, style="label")
        elif seg_w >= 4:
            # Show just the fill character as a legend marker
            pct_only = short_label.split()[-1]  # e.g. "40%"
            pw = display_width(pct_only)
            if pw <= seg_w:
                lx = stacked_left + start + (seg_w - pw) // 2
                canvas.put_text(label_row, lx, pct_only, style="label")

    # Per-slice bars (uniform fill)
    for i, s in enumerate(diagram.slices):
        row = bars_top + i
        fill = fills[i % len(fills)]
        bar_len = max(1, round(s.value / total * bar_width))

        # Label (right-aligned)
        label_text = s.label.rjust(max_label_len)
        canvas.put_text(row, _MARGIN, label_text, style="label")

        # Bar
        if use_ascii:
            canvas.put(row, bar_left, "|", merge=False, style="edge")
        else:
            canvas.put(row, bar_left, "┃", merge=False, style="edge")
        for c in range(bar_len):
            canvas.put(row, bar_left + 1 + c, fill, merge=False, style="node")

        # Suffix
        canvas.put_text(row, bar_left + 1 + bar_len, suffixes[i], style="label")

    return canvas


# Quadrant charts
# ------------------------------------------------------------------------
#
# Renders a 2x2 grid with labeled quadrants and data points plotted
# at their (x, y) positions using marker characters.

_QUADRANT_CHART_W = 60  # chart area width
_QUADRANT_CHART_H = 20  # chart area height
_QUADRANT_MARGIN_L = 2  # left margin for y-axis label
_MARGIN_B = 2  # bottom margin for x-axis label


def render_quadrant(
    diagram: QuadrantChart,
    *,
    use_ascii: bool = False,
    max_width: int | None = None,
) -> Canvas:
    """Render a QuadrantChart model to a Canvas."""
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    cross = "+" if use_ascii else "┼"
    marker = "*" if use_ascii else "●"
    corner = "+" if use_ascii else "└"
    chart_w = (_QUADRANT_CHART_W if max_width is None else
               min(_QUADRANT_CHART_W, max(8, max_width - _QUADRANT_MARGIN_L)))
    chart_h = _QUADRANT_CHART_H

    lines: list[str] = []

    # Title
    if diagram.title:
        pad = (_QUADRANT_MARGIN_L + chart_w - display_width(diagram.title)) // 2
        lines.append(" " * max(0, pad) + diagram.title)
        lines.append("")

    # Build the chart grid
    # Quadrant labels centered in their quadrant
    q2_label = diagram.quadrant_2  # top-left
    q1_label = diagram.quadrant_1  # top-right
    q3_label = diagram.quadrant_3  # bottom-left
    q4_label = diagram.quadrant_4  # bottom-right

    half_w = chart_w // 2
    half_h = chart_h // 2

    # Create empty grid
    grid: list[list[str]] = [[" " for _ in range(chart_w)] for _ in range(chart_h)]

    # Place quadrant labels (centered in each quadrant)
    _place_label(grid, q2_label, half_w // 2, half_h // 2)     # top-left
    _place_label(grid, q1_label, half_w + half_w // 2, half_h // 2)  # top-right
    _place_label(grid, q3_label, half_w // 2, half_h + half_h // 2)  # bottom-left
    _place_label(grid, q4_label, half_w + half_w // 2, half_h + half_h // 2)  # bottom-right

    # Draw axes (center lines)
    for c in range(chart_w):
        grid[half_h][c] = hz
    for r in range(chart_h):
        grid[r][half_w] = vt
    grid[half_h][half_w] = cross

    # Plot points
    for point in diagram.points:
        px = int(point.x * (chart_w - 1))
        py = int((1 - point.y) * (chart_h - 1))  # y is inverted (0=bottom)
        px = max(0, min(chart_w - 1, px))
        py = max(0, min(chart_h - 1, py))
        grid[py][px] = marker
        # Place label to the right of the marker (with 1 char gap)
        label = " " + point.label
        start = px + 1
        if start + display_width(label) > chart_w:
            # Doesn't fit on right, try left
            start = px - display_width(label)
        if start >= 0:
            for i, ch in enumerate(label):
                if 0 <= start + i < chart_w:
                    grid[py][start + i] = ch

    # Build a style grid matching the char grid
    style_grid: list[list[str]] = [["default" for _ in range(chart_w)] for _ in range(chart_h)]
    for r in range(chart_h):
        for c in range(chart_w):
            if r < half_h and c < half_w:
                style_grid[r][c] = "section:1"   # Q2 top-left
            elif r < half_h and c >= half_w:
                style_grid[r][c] = "section:0"   # Q1 top-right
            elif r >= half_h and c < half_w:
                style_grid[r][c] = "section:2"   # Q3 bottom-left
            else:
                style_grid[r][c] = "section:3"   # Q4 bottom-right
    # Axes get edge style
    for c in range(chart_w):
        style_grid[half_h][c] = "edge"
    for r in range(chart_h):
        style_grid[r][half_w] = "edge"

    # Render grid with left margin
    title_lines = len(lines)  # lines added before the grid (title)

    # X-axis label
    x_label_line = ""
    if diagram.x_label:
        x_pad = _QUADRANT_MARGIN_L + (chart_w - display_width(diagram.x_label)) // 2
        x_label_line = " " * max(0, x_pad) + diagram.x_label

    # Compute canvas size
    total_h = title_lines + chart_h + (2 if x_label_line else 0)
    width = max(_QUADRANT_MARGIN_L + chart_w,
                display_width(diagram.title), display_width(diagram.x_label))
    canvas = Canvas(width, total_h)

    # Write title lines
    for r, line in enumerate(lines):
        canvas.put_text(r, 0, line, style="label")

    # Write ALL grid cells (including spaces) so backgrounds fill
    # the entire quadrant region. For non-space chars, use put().
    # For spaces, write the style directly since put() skips them.
    for r in range(chart_h):
        row_y = title_lines + r
        for c in range(chart_w):
            col_x = _QUADRANT_MARGIN_L + c
            ch = grid[r][c]
            style = style_grid[r][c]
            if ch != " ":
                canvas.put(row_y, col_x, ch, merge=False, style=style)
            else:
                canvas._style_grid[row_y][col_x] = style

    # Write x-axis label
    if x_label_line:
        canvas.put_text(title_lines + chart_h + 1, 0, x_label_line, style="edge_label")

    return canvas


def _place_label(grid: list[list[str]], label: str, cx: int, cy: int) -> None:
    """Place a label centered at (cx, cy) in the grid."""
    start_x = cx - display_width(label) // 2
    w = len(grid[0]) if grid else 0
    for i, ch in enumerate(label):
        x = start_x + i
        if 0 <= x < w and 0 <= cy < len(grid):
            grid[cy][x] = ch


# XY charts
# ------------------------------------------------------------------------
#
# Renders bar charts and line charts on labeled axes.
# Supports vertical (default) and horizontal orientations.

_XYCHART_CHART_H = 15     # chart area height (rows for data) in vertical mode
_XYCHART_CHART_W = 50     # chart area width in horizontal mode
_BAR_CHAR = "█"
_BAR_HALF = "▄"
_BAR_HALF_H = "▌"  # half block for horizontal bars
_LINE_MARKER = "●"
_XYCHART_BAR_WIDTH = 4    # width of each bar in vertical mode
_BAR_GAP = 2      # gap between bars
_XYCHART_MARGIN_L = 8     # left margin for y-axis labels


def render_xychart(
    diagram: XYChart,
    *,
    use_ascii: bool = False,
    rounded: bool = True,
    max_width: int | None = None,
) -> Canvas:
    """Render an XYChart model to a Canvas."""
    if not diagram.datasets:
        return Canvas(1, 1)

    # Horizontal mode only applies to bar-only charts.
    # Line charts always render vertically since they need a
    # continuous axis to show trends.
    has_line = any(ds.chart_type == "line" for ds in diagram.datasets)
    if diagram.horizontal and not has_line:
        return _render_horizontal(diagram, use_ascii=use_ascii, max_width=max_width)
    return _render_vertical(diagram, use_ascii=use_ascii, rounded=rounded,
                            max_width=max_width)


# ---------------------------------------------------------------------------
# Vertical chart (default)
# ---------------------------------------------------------------------------

def _render_vertical(diagram: XYChart, use_ascii: bool = False,
                     rounded: bool = True, max_width: int | None = None) -> Canvas:
    bar_char = "#" if use_ascii else _BAR_CHAR
    bar_half = "=" if use_ascii else _BAR_HALF
    marker = "*" if use_ascii else _LINE_MARKER
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    corner = "+" if use_ascii else "└"
    tick = "+" if use_ascii else "┬"
    left_tick = "+" if use_ascii else "┤"

    # Compute value range
    all_values: list[float] = []
    for ds in diagram.datasets:
        all_values.extend(ds.values)
    if not all_values:
        return Canvas(1, 1)

    max_val = max(all_values)
    min_val = min(0, min(all_values))
    if diagram.y_range:
        min_val, max_val = diagram.y_range
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1

    n_points = max(len(ds.values) for ds in diagram.datasets)

    # Categories
    categories = list(diagram.x_categories[:n_points])
    if diagram.x_range and not categories:
        lo, hi = diagram.x_range
        step = (hi - lo) / max(n_points - 1, 1)
        categories = [_format_val(lo + i * step) for i in range(n_points)]
    while len(categories) < n_points:
        categories.append(str(len(categories) + 1))

    cat_width = max(display_width(c) for c in categories) if categories else 2
    col_width = max(_XYCHART_BAR_WIDTH, cat_width + 1)
    bar_gap = _BAR_GAP
    if max_width is not None and n_points:
        available = max_width - _XYCHART_MARGIN_L - 4
        if n_points * (col_width + bar_gap) - bar_gap > available:
            bar_gap = 1
            col_width = max(cat_width, min(col_width, (available - bar_gap * (n_points - 1)) // n_points))

    chart_w = n_points * (col_width + bar_gap) - bar_gap
    total_w = _XYCHART_MARGIN_L + 1 + chart_w + 2

    title_lines = 2 if diagram.title else 0
    total_h = _XYCHART_CHART_H + 4

    canvas = Canvas(max(total_w + 1, display_width(diagram.title),
                             display_width(diagram.x_label)), total_h + title_lines + 1)
    row_offset = title_lines

    # Title
    if diagram.title:
        title_x = _XYCHART_MARGIN_L + (chart_w - display_width(diagram.title)) // 2
        canvas.put_text(0, max(0, title_x), diagram.title, style="label")

    # Y-axis labels
    n_ticks = 5
    for i in range(n_ticks + 1):
        val = min_val + val_range * (n_ticks - i) / n_ticks
        label = _format_val(val)
        label_x = _XYCHART_MARGIN_L - display_width(label) - 1
        row = row_offset + i * _XYCHART_CHART_H // n_ticks
        canvas.put_text(row, max(0, label_x), label, style="edge_label")
        canvas.put(row, _XYCHART_MARGIN_L, left_tick, merge=False, style="edge")

    # Y-axis line
    for r in range(row_offset, row_offset + _XYCHART_CHART_H + 1):
        canvas.put(r, _XYCHART_MARGIN_L, vt, merge=False, style="edge")

    # X-axis line
    axis_row = row_offset + _XYCHART_CHART_H
    canvas.put(axis_row, _XYCHART_MARGIN_L, corner, merge=False, style="edge")
    for c in range(_XYCHART_MARGIN_L + 1, _XYCHART_MARGIN_L + 1 + chart_w):
        canvas.put(axis_row, c, hz, merge=False, style="edge")

    # Draw datasets
    for ds in diagram.datasets:
        for i, val in enumerate(ds.values):
            if i >= n_points:
                break
            col_x = _XYCHART_MARGIN_L + 1 + i * (col_width + bar_gap)
            bar_h = int((val - min_val) / val_range * _XYCHART_CHART_H)

            if ds.chart_type == "bar":
                for r in range(bar_h):
                    row = row_offset + _XYCHART_CHART_H - 1 - r
                    for c in range(col_width):
                        canvas.put(row, col_x + c, bar_char, merge=False,
                                  style=f"section:{i % 8}")
                frac = (val - min_val) / val_range * _XYCHART_CHART_H - bar_h
                if frac > 0.3 and bar_h < _XYCHART_CHART_H:
                    row = row_offset + _XYCHART_CHART_H - 1 - bar_h
                    for c in range(col_width):
                        canvas.put(row, col_x + c, bar_half, merge=False,
                                  style=f"section:{i % 8}")
            else:
                row = row_offset + _XYCHART_CHART_H - 1 - max(0, bar_h - 1)
                mid_x = col_x + col_width // 2
                # Place a line segment at the data point position
                line_ch = "-" if use_ascii else "─"
                canvas.put(row, mid_x, line_ch, merge=False, style="edge")

                if i > 0:
                    prev_val = ds.values[i - 1]
                    prev_h = int((prev_val - min_val) / val_range * _XYCHART_CHART_H)
                    prev_row = row_offset + _XYCHART_CHART_H - 1 - max(0, prev_h - 1)
                    prev_x = _XYCHART_MARGIN_L + 1 + (i - 1) * (col_width + bar_gap) + col_width // 2
                    _draw_line_v(canvas, prev_x, prev_row, mid_x, row, use_ascii, rounded)

    # X-axis ticks and labels
    for i, cat in enumerate(categories):
        col_x = _XYCHART_MARGIN_L + 1 + i * (col_width + bar_gap) + col_width // 2
        canvas.put(axis_row, col_x, tick, merge=False, style="edge")
        label_x = col_x - display_width(cat) // 2
        canvas.put_text(axis_row + 1, max(0, label_x), cat, style="edge_label")

    if diagram.x_label:
        lx = _XYCHART_MARGIN_L + 1 + (chart_w - display_width(diagram.x_label)) // 2
        canvas.put_text(axis_row + 2, max(0, lx), diagram.x_label, style="edge_label")

    return canvas


# ---------------------------------------------------------------------------
# Horizontal chart
# ---------------------------------------------------------------------------

def _render_horizontal(diagram: XYChart, use_ascii: bool = False,
                       max_width: int | None = None) -> Canvas:
    bar_char = "#" if use_ascii else _BAR_CHAR
    bar_half = "|" if use_ascii else _BAR_HALF_H
    marker = "*" if use_ascii else _LINE_MARKER
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    corner = "+" if use_ascii else "└"
    tick = "+" if use_ascii else "├"
    bottom_tick = "+" if use_ascii else "┬"

    all_values: list[float] = []
    for ds in diagram.datasets:
        all_values.extend(ds.values)
    if not all_values:
        return Canvas(1, 1)

    max_val = max(all_values)
    min_val = min(0, min(all_values))
    if diagram.y_range:
        min_val, max_val = diagram.y_range
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1

    n_points = max(len(ds.values) for ds in diagram.datasets)

    # Categories (displayed on the y-axis in horizontal mode)
    categories = list(diagram.x_categories[:n_points])
    if diagram.x_range and not categories:
        lo, hi = diagram.x_range
        step = (hi - lo) / max(n_points - 1, 1)
        categories = [_format_val(lo + i * step) for i in range(n_points)]
    while len(categories) < n_points:
        categories.append(str(len(categories) + 1))

    cat_width = max(display_width(c) for c in categories) if categories else 2
    margin_l = cat_width + 2  # space for category labels + padding

    bar_height = 1  # each bar is 1 row tall
    row_gap = 1     # gap between rows
    chart_h = n_points * (bar_height + row_gap) - row_gap
    chart_w = (_XYCHART_CHART_W if max_width is None else
               min(_XYCHART_CHART_W, max(8, max_width - margin_l - 4)))

    title_lines = 2 if diagram.title else 0
    total_h = title_lines + chart_h + 3  # chart + axis + value labels
    total_w = margin_l + 1 + chart_w + 2

    canvas = Canvas(max(total_w + 1, display_width(diagram.title),
                             display_width(diagram.x_label)), total_h + 1)
    row_offset = title_lines

    # Title
    if diagram.title:
        title_x = margin_l + (chart_w - display_width(diagram.title)) // 2
        canvas.put_text(0, max(0, title_x), diagram.title, style="label")

    # Y-axis (categories on the left)
    for r in range(row_offset, row_offset + chart_h + 1):
        canvas.put(r, margin_l, vt, merge=False, style="edge")

    # X-axis (values on the bottom)
    axis_row = row_offset + chart_h
    canvas.put(axis_row, margin_l, corner, merge=False, style="edge")
    for c in range(margin_l + 1, margin_l + 1 + chart_w):
        canvas.put(axis_row, c, hz, merge=False, style="edge")

    # X-axis value labels (bottom)
    n_ticks = max(1, min(5, chart_w // 8))
    for i in range(n_ticks + 1):
        val = min_val + val_range * i / n_ticks
        label = _format_val(val)
        col = margin_l + 1 + int(i / n_ticks * (chart_w - 1))
        canvas.put(axis_row, col, bottom_tick, merge=False, style="edge")
        label_x = max(0, min(total_w - display_width(label),
                             col - display_width(label) // 2))
        canvas.put_text(axis_row + 1, max(0, label_x), label, style="edge_label")

    if diagram.x_label:
        lx = margin_l + 1 + (chart_w - display_width(diagram.x_label)) // 2
        canvas.put_text(axis_row + 2, max(0, lx), diagram.x_label, style="edge_label")

    # Draw datasets
    for ds in diagram.datasets:
        for i, val in enumerate(ds.values):
            if i >= n_points:
                break
            row = row_offset + i * (bar_height + row_gap)
            bar_w = int((val - min_val) / val_range * chart_w)

            # Category label
            cat = categories[i] if i < len(categories) else ""
            label_x = margin_l - display_width(cat) - 1
            canvas.put_text(row, max(0, label_x), cat, style="edge_label")
            # Don't draw tick on category rows; the axis │ is enough

            for c in range(bar_w):
                canvas.put(row, margin_l + 1 + c, bar_char, merge=False,
                          style=f"section:{i % 8}")

    return canvas


# ---------------------------------------------------------------------------
# Line drawing helpers
# ---------------------------------------------------------------------------

def _draw_line_v(canvas: Canvas, x1: int, y1: int, x2: int, y2: int, use_ascii: bool, rounded: bool = True) -> None:
    """Draw a connecting line between two markers (vertical chart)."""
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    if use_ascii:
        tl, tr, bl, br = "+", "+", "+", "+"
    elif rounded:
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
    else:
        tl, tr, bl, br = "┌", "┐", "└", "┘"

    if y1 == y2:
        for x in range(x1 + 1, x2):
            canvas.put(y1, x, hz, merge=False, style="edge")
    else:
        mid_x = (x1 + x2) // 2
        going_up = y2 < y1

        for x in range(x1 + 1, mid_x):
            canvas.put(y1, x, hz, merge=False, style="edge")

        if going_up:
            canvas.put(y1, mid_x, br, merge=False, style="edge")
        else:
            canvas.put(y1, mid_x, tr, merge=False, style="edge")

        r_min, r_max = min(y1, y2), max(y1, y2)
        for r in range(r_min + 1, r_max):
            canvas.put(r, mid_x, vt, merge=False, style="edge")

        if going_up:
            canvas.put(y2, mid_x, tl, merge=False, style="edge")
        else:
            canvas.put(y2, mid_x, bl, merge=False, style="edge")

        for x in range(mid_x + 1, x2):
            canvas.put(y2, x, hz, merge=False, style="edge")


def _draw_line_h(canvas: Canvas, x1: int, y1: int, x2: int, y2: int, use_ascii: bool) -> None:
    """Draw a connecting line between two markers (horizontal chart)."""
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    if use_ascii:
        tl, tr, bl, br = "+", "+", "+", "+"
    else:
        tl, tr, bl, br = "╭", "╮", "╰", "╯"

    if x1 == x2:
        for r in range(y1 + 1, y2):
            canvas.put(r, x1, vt, merge=False, style="edge")
    else:
        mid_y = (y1 + y2) // 2
        going_right = x2 > x1

        for r in range(y1 + 1, mid_y):
            canvas.put(r, x1, vt, merge=False, style="edge")

        if going_right:
            canvas.put(mid_y, x1, bl, merge=False, style="edge")
        else:
            canvas.put(mid_y, x1, br, merge=False, style="edge")

        c_min, c_max = min(x1, x2), max(x1, x2)
        for c in range(c_min + 1, c_max):
            canvas.put(mid_y, c, hz, merge=False, style="edge")

        if going_right:
            canvas.put(mid_y, x2, tr, merge=False, style="edge")
        else:
            canvas.put(mid_y, x2, tl, merge=False, style="edge")

        for r in range(mid_y + 1, y2):
            canvas.put(r, x2, vt, merge=False, style="edge")


def _format_val(val: float) -> str:
    if val == int(val):
        return str(int(val))
    return f"{val:.1f}"


def render_pie_source(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.body
    canvas = render_pie_chart(
        parse_pie_chart(text), use_ascii=config.use_ascii, max_width=config.max_width,
    )
    return RenderResult(canvas)


def render_xychart_source(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.body
    canvas = render_xychart(
        parse_xychart(text), use_ascii=config.use_ascii, rounded=config.rounded_edges,
        max_width=config.max_width,
    )
    return RenderResult(canvas)


def render_quadrant_source(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.body
    canvas = render_quadrant(
        parse_quadrant(text), use_ascii=config.use_ascii, max_width=config.max_width,
    )
    return RenderResult(canvas)
