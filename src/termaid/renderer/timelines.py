"""Terminal renderers for gantt schedules, timelines."""
from __future__ import annotations

from datetime import date, timedelta

from ..layout.scene import LayoutScene
from ..model.timelines import Gantt, Timeline
from ..utils import display_width, truncate_to_width
from .charset import ASCII, UNICODE, CharSet


# Gantt schedules
# ------------------------------------------------------------------------
#
# Renders horizontal bar chart with tasks along the y-axis and time
# along the x-axis. Tasks are grouped by sections. Each task's bar
# shows its duration proportionally.

_DEFAULT_WIDTH = 80
_BAR_CHAR = "█"
_ACTIVE_CHAR = "▓"
_DONE_CHAR = "░"
_CRIT_CHAR = "█"
_MILESTONE_CHAR = "◆"


def render_gantt(
    diagram: Gantt,
    *,
    use_ascii: bool = False,
    width: int = _DEFAULT_WIDTH,
) -> LayoutScene:
    """Render a Gantt model to a LayoutScene."""
    if not diagram.sections:
        return LayoutScene(1, 1)

    bar_char = "#" if use_ascii else _BAR_CHAR
    active_char = "=" if use_ascii else _ACTIVE_CHAR
    done_char = "." if use_ascii else _DONE_CHAR
    crit_char = "!" if use_ascii else _CRIT_CHAR
    milestone_char = "*" if use_ascii else _MILESTONE_CHAR
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    today_char = "|" if use_ascii else "▏"

    # Collect all tasks and find date range
    all_tasks: list[tuple[str, list[tuple[str, date | None, date | None, str]]]] = []
    min_date: date | None = None
    max_date: date | None = None
    max_label_width = 0

    for section in diagram.sections:
        section_tasks: list[tuple[str, date | None, date | None, str]] = []
        for task in section.tasks:
            # Determine bar style
            if task.is_milestone:
                style = "milestone"
            elif task.is_done:
                style = "done"
            elif task.is_active:
                style = "active"
            elif task.is_crit:
                style = "crit"
            else:
                style = "normal"

            section_tasks.append((task.title, task.start, task.end, style))
            max_label_width = max(max_label_width, display_width(task.title))

            if task.start:
                if min_date is None or task.start < min_date:
                    min_date = task.start
            if task.end:
                if max_date is None or task.end > max_date:
                    max_date = task.end

        all_tasks.append((section.title, section_tasks))
        max_label_width = max(max_label_width, display_width(section.title) + 2)

    if min_date is None or max_date is None:
        return LayoutScene(1, 1)

    # Ensure at least 1 day range
    total_days = (max_date - min_date).days
    if total_days <= 0:
        total_days = 1
        max_date = min_date + timedelta(days=1)

    # Layout: labels start at column 3 and need a blank column before the axis
    margin_l = max_label_width + 4
    chart_w = width - margin_l - 1
    if chart_w < 10:
        chart_w = 10

    # Compute rows
    title_rows = 2 if diagram.title else 0
    task_rows = 0
    for section_title, tasks in all_tasks:
        if section_title:
            task_rows += 1  # section header
        task_rows += len(tasks)

    axis_rows = 2  # axis line + date labels
    total_h = title_rows + task_rows + axis_rows + 1
    total_w = margin_l + chart_w + 1

    canvas = LayoutScene(total_w + 1, total_h + 1)

    # Title
    if diagram.title:
        tx = margin_l + (chart_w - display_width(diagram.title)) // 2
        canvas.put_text(0, max(0, tx), diagram.title, style="label")

    # Draw tasks
    row = title_rows
    section_idx = 0
    for section_title, tasks in all_tasks:
        if section_title:
            canvas.put_text(row, 1, section_title, style=f"sectionfg:{section_idx}")
            row += 1

        for title, start, end, style in tasks:
            # Task label (indented, truncated if needed)
            avail = margin_l - 4
            disp = truncate_to_width(title, avail)
            canvas.put_text(row, 3, disp, style="edge_label")

            if start and end:
                # Compute bar position
                start_offset = (start - min_date).days
                end_offset = (end - min_date).days
                bar_start = margin_l + 1 + int(start_offset / total_days * (chart_w - 1))
                bar_end = margin_l + 1 + int(end_offset / total_days * (chart_w - 1))
                bar_end = max(bar_end, bar_start + 1)

                # Choose bar character
                if style == "milestone":
                    mid = (bar_start + bar_end) // 2
                    canvas.put(row, mid, milestone_char, merge=False,
                              style=f"section:{section_idx}")
                else:
                    ch = bar_char
                    if style == "done":
                        ch = done_char
                    elif style == "active":
                        ch = active_char
                    elif style == "crit":
                        ch = crit_char

                    task_style = f"section:{section_idx}"
                    for c in range(bar_start, bar_end):
                        if c < total_w:
                            canvas.put(row, c, ch, merge=False, style=task_style)

            row += 1
        section_idx += 1

    # Continuous y-axis line
    axis_row = row
    for r in range(title_rows, axis_row):
        canvas.put(r, margin_l, vt, merge=False, style="edge")

    # X-axis
    canvas.put(axis_row, margin_l, "+" if use_ascii else "└", merge=False, style="edge")
    for c in range(margin_l + 1, margin_l + chart_w):
        canvas.put(axis_row, c, hz, merge=False, style="edge")

    # Vertical markers with date labels at top
    marker_vt = "|" if use_ascii else "┊"
    for marker_date in diagram.vertical_markers:
        offset = (marker_date - min_date).days
        if 0 <= offset <= total_days:
            col = margin_l + 1 + int(offset / total_days * (chart_w - 1))
            # Date label above the chart
            label = marker_date.strftime("%b %d")
            label_x = col - display_width(label) // 2
            label_row = title_rows - 1 if title_rows > 0 else 0
            # Make room if needed
            if label_row < 0:
                label_row = 0
            canvas.put_text(label_row, max(margin_l + 1, label_x), label, style="edge_label")
            # Vertical line
            for r in range(title_rows, axis_row):
                existing = canvas.get(r, col)
                if existing == " " or existing == hz:
                    canvas.put(r, col, marker_vt, merge=False, style="edge_label")

    # Today marker
    if diagram.today_marker:
        today = date.today()
        offset = (today - min_date).days
        if 0 <= offset <= total_days:
            today_vt = "|" if use_ascii else "▎"
            col = margin_l + 1 + int(offset / total_days * (chart_w - 1))
            for r in range(title_rows, axis_row):
                existing = canvas.get(r, col)
                if existing == " ":
                    canvas.put(r, col, today_vt, merge=False, style="arrow")

    # Date labels on x-axis
    n_ticks = min(6, total_days)
    if n_ticks < 2:
        n_ticks = 2
    for i in range(n_ticks + 1):
        d = min_date + timedelta(days=int(i / n_ticks * total_days))
        label = d.strftime("%b %d")
        col = margin_l + 1 + int(i / n_ticks * (chart_w - 2))
        # Tick mark
        canvas.put(axis_row, col, "+" if use_ascii else "┬", merge=False, style="edge")
        # Date label
        label_x = col - display_width(label) // 2
        canvas.put_text(axis_row + 1, max(0, label_x), label, style="edge_label")

    return canvas


# Timelines
# ------------------------------------------------------------------------
#
# Renders a vertical timeline with sections and events connected by
# a central vertical line.

def render_timeline(
    diagram: Timeline,
    *,
    use_ascii: bool = False,
) -> LayoutScene:
    """Render a Timeline model to a LayoutScene."""
    cs = ASCII if use_ascii else UNICODE

    if not diagram.sections:
        return LayoutScene(1, 1)

    # Build lines with per-section styles
    styled_lines: list[tuple[str, str]] = []  # (text, style_key)

    # Title
    if diagram.title:
        styled_lines.append((diagram.title, "label"))
        styled_lines.append(("", "default"))

    v = "|" if use_ascii else "│"
    h = "-" if use_ascii else "─"
    bullet = "o" if use_ascii else "●"
    section_marker = "=" if use_ascii else "═"

    for si, section in enumerate(diagram.sections):
        style = f"sectionfg:{si}"

        # Section header
        if section.title:
            header = f" {section_marker}{section_marker} {section.title} {section_marker}{section_marker}"
            styled_lines.append((header, style))
            styled_lines.append((f" {v}", style))

        for ei, event in enumerate(section.events):
            is_last_event = ei == len(section.events) - 1
            is_last_section = si == len(diagram.sections) - 1

            styled_lines.append((f" {bullet}{h}{h} {event.title}", style))

            for detail in event.details:
                styled_lines.append((f" {v}   {detail}", "edge_label"))

            if not (is_last_event and is_last_section):
                styled_lines.append((f" {v}", style))

    # Write to canvas
    width = max((display_width(line) for line, _ in styled_lines), default=1) + 1
    height = len(styled_lines)
    canvas = LayoutScene(width, height)
    for r, (line, style) in enumerate(styled_lines):
        canvas.put_text(r, 0, line, style=style)

    return canvas
