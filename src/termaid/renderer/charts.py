"""Terminal renderers for pie charts, quadrant charts, xy charts."""
from __future__ import annotations

from ..layout.scene import LayoutScene
from ..model.charts import PieChart, QuadrantChart, XYChart
from ..utils import display_width
from .charset import ASCII, UNICODE, CharSet


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
) -> LayoutScene:
    """Render a PieChart as a horizontal bar chart on a LayoutScene."""

    if not diagram.slices:
        canvas = LayoutScene(1, 1)
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
    canvas_w = bar_left + _PIECHART_BAR_WIDTH + max_suffix_len + _MARGIN
    title_rows = 2 if diagram.title else 0

    # Layout: title, stacked bar (3 rows), blank, per-slice bars
    stacked_top = _MARGIN + title_rows
    bars_top = stacked_top + 4  # stacked bar + labels row + blank
    canvas_h = bars_top + len(diagram.slices) + _MARGIN

    canvas = LayoutScene(canvas_w, canvas_h)

    # Title
    if diagram.title:
        title_col = max(0, (canvas_w - len(diagram.title)) // 2)
        canvas.put_text(_MARGIN, title_col, diagram.title, style="label")

    # Stacked bar showing parts of a whole
    stacked_w = _PIECHART_BAR_WIDTH
    stacked_left = bar_left + 1
    col = 0
    label_parts: list[tuple[int, int, str, str]] = []  # (start, width, label, fill)
    for i, s in enumerate(diagram.slices):
        fill = fills[i % len(fills)]
        seg_w = max(1, round(s.value / total * stacked_w))
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
        bar_len = max(1, round(s.value / total * _PIECHART_BAR_WIDTH))

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
) -> LayoutScene:
    """Render a QuadrantChart model to a LayoutScene."""
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    cross = "+" if use_ascii else "┼"
    marker = "*" if use_ascii else "●"
    corner = "+" if use_ascii else "└"

    lines: list[str] = []

    # Title
    if diagram.title:
        pad = (_QUADRANT_MARGIN_L + _QUADRANT_CHART_W - len(diagram.title)) // 2
        lines.append(" " * max(0, pad) + diagram.title)
        lines.append("")

    # Build the chart grid
    # Quadrant labels centered in their quadrant
    q2_label = diagram.quadrant_2  # top-left
    q1_label = diagram.quadrant_1  # top-right
    q3_label = diagram.quadrant_3  # bottom-left
    q4_label = diagram.quadrant_4  # bottom-right

    half_w = _QUADRANT_CHART_W // 2
    half_h = _QUADRANT_CHART_H // 2

    # Create empty grid
    grid: list[list[str]] = [[" " for _ in range(_QUADRANT_CHART_W)] for _ in range(_QUADRANT_CHART_H)]

    # Place quadrant labels (centered in each quadrant)
    _place_label(grid, q2_label, half_w // 2, half_h // 2)     # top-left
    _place_label(grid, q1_label, half_w + half_w // 2, half_h // 2)  # top-right
    _place_label(grid, q3_label, half_w // 2, half_h + half_h // 2)  # bottom-left
    _place_label(grid, q4_label, half_w + half_w // 2, half_h + half_h // 2)  # bottom-right

    # Draw axes (center lines)
    for c in range(_QUADRANT_CHART_W):
        grid[half_h][c] = hz
    for r in range(_QUADRANT_CHART_H):
        grid[r][half_w] = vt
    grid[half_h][half_w] = cross

    # Plot points
    for point in diagram.points:
        px = int(point.x * (_QUADRANT_CHART_W - 1))
        py = int((1 - point.y) * (_QUADRANT_CHART_H - 1))  # y is inverted (0=bottom)
        px = max(0, min(_QUADRANT_CHART_W - 1, px))
        py = max(0, min(_QUADRANT_CHART_H - 1, py))
        grid[py][px] = marker
        # Place label to the right of the marker (with 1 char gap)
        label = " " + point.label
        start = px + 1
        if start + display_width(label) > _QUADRANT_CHART_W:
            # Doesn't fit on right, try left
            start = px - display_width(label)
        if start >= 0:
            for i, ch in enumerate(label):
                if 0 <= start + i < _QUADRANT_CHART_W:
                    grid[py][start + i] = ch

    # Build a style grid matching the char grid
    style_grid: list[list[str]] = [["default" for _ in range(_QUADRANT_CHART_W)] for _ in range(_QUADRANT_CHART_H)]
    for r in range(_QUADRANT_CHART_H):
        for c in range(_QUADRANT_CHART_W):
            if r < half_h and c < half_w:
                style_grid[r][c] = "section:1"   # Q2 top-left
            elif r < half_h and c >= half_w:
                style_grid[r][c] = "section:0"   # Q1 top-right
            elif r >= half_h and c < half_w:
                style_grid[r][c] = "section:2"   # Q3 bottom-left
            else:
                style_grid[r][c] = "section:3"   # Q4 bottom-right
    # Axes get edge style
    for c in range(_QUADRANT_CHART_W):
        style_grid[half_h][c] = "edge"
    for r in range(_QUADRANT_CHART_H):
        style_grid[r][half_w] = "edge"

    # Render grid with left margin
    title_lines = len(lines)  # lines added before the grid (title)

    # X-axis label
    x_label_line = ""
    if diagram.x_label:
        x_pad = _QUADRANT_MARGIN_L + (_QUADRANT_CHART_W - len(diagram.x_label)) // 2
        x_label_line = " " * max(0, x_pad) + diagram.x_label

    # Compute canvas size
    total_h = title_lines + _QUADRANT_CHART_H + (2 if x_label_line else 0)
    width = _QUADRANT_MARGIN_L + _QUADRANT_CHART_W + 1
    canvas = LayoutScene(width, total_h)

    # Write title lines
    for r, line in enumerate(lines):
        canvas.put_text(r, 0, line, style="label")

    # Write ALL grid cells (including spaces) so backgrounds fill
    # the entire quadrant region. For non-space chars, use put().
    # For spaces, write the style directly since put() skips them.
    for r in range(_QUADRANT_CHART_H):
        row_y = title_lines + r
        for c in range(_QUADRANT_CHART_W):
            col_x = _QUADRANT_MARGIN_L + c
            ch = grid[r][c]
            style = style_grid[r][c]
            if ch != " ":
                canvas.put(row_y, col_x, ch, merge=False, style=style)
            else:
                canvas._style_grid[row_y][col_x] = style

    # Write x-axis label
    if x_label_line:
        canvas.put_text(title_lines + _QUADRANT_CHART_H + 1, 0, x_label_line, style="edge_label")

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
) -> LayoutScene:
    """Render an XYChart model to a LayoutScene."""
    if not diagram.datasets:
        return LayoutScene(1, 1)

    # Horizontal mode only applies to bar-only charts.
    # Line charts always render vertically since they need a
    # continuous axis to show trends.
    has_line = any(ds.chart_type == "line" for ds in diagram.datasets)
    if diagram.horizontal and not has_line:
        return _render_horizontal(diagram, use_ascii=use_ascii)
    return _render_vertical(diagram, use_ascii=use_ascii, rounded=rounded)


# ---------------------------------------------------------------------------
# Vertical chart (default)
# ---------------------------------------------------------------------------

def _render_vertical(diagram: XYChart, use_ascii: bool = False, rounded: bool = True) -> LayoutScene:
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
        return LayoutScene(1, 1)

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

    chart_w = n_points * (col_width + _BAR_GAP) - _BAR_GAP
    total_w = _XYCHART_MARGIN_L + 1 + chart_w + 2

    title_lines = 2 if diagram.title else 0
    total_h = _XYCHART_CHART_H + 4

    canvas = LayoutScene(total_w + 1, total_h + title_lines + 1)
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
            col_x = _XYCHART_MARGIN_L + 1 + i * (col_width + _BAR_GAP)
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
                    prev_x = _XYCHART_MARGIN_L + 1 + (i - 1) * (col_width + _BAR_GAP) + col_width // 2
                    _draw_line_v(canvas, prev_x, prev_row, mid_x, row, use_ascii, rounded)

    # X-axis ticks and labels
    for i, cat in enumerate(categories):
        col_x = _XYCHART_MARGIN_L + 1 + i * (col_width + _BAR_GAP) + col_width // 2
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

def _render_horizontal(diagram: XYChart, use_ascii: bool = False) -> LayoutScene:
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
        return LayoutScene(1, 1)

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
    chart_w = _XYCHART_CHART_W

    title_lines = 2 if diagram.title else 0
    total_h = title_lines + chart_h + 3  # chart + axis + value labels
    total_w = margin_l + 1 + chart_w + 2

    canvas = LayoutScene(total_w + 1, total_h + 1)
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
    n_ticks = 5
    for i in range(n_ticks + 1):
        val = min_val + val_range * i / n_ticks
        label = _format_val(val)
        col = margin_l + 1 + int(i / n_ticks * (chart_w - 1))
        canvas.put(axis_row, col, bottom_tick, merge=False, style="edge")
        label_x = col - display_width(label) // 2
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

def _draw_line_v(canvas: LayoutScene, x1: int, y1: int, x2: int, y2: int, use_ascii: bool, rounded: bool = True) -> None:
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


def _draw_line_h(canvas: LayoutScene, x1: int, y1: int, x2: int, y2: int, use_ascii: bool) -> None:
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
