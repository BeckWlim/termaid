"""Timelines diagrams: models, parsing, layout, and drawing."""
from __future__ import annotations

from termaid.core.contracts import ParsedSource, RenderConfig, RenderResult

from dataclasses import dataclass, field
from datetime import date
import re
from datetime import datetime, timedelta
from termaid.core.canvas import Canvas
from termaid.utils import display_width, truncate_to_width
from termaid.renderer.charset import ASCII, UNICODE, CharSet


# Model
# ------------------------------------------------------------------------

# Gantt schedules
# ------------------------------------------------------------------------

@dataclass
class GanttTask:
    id: str = ""
    title: str = ""
    start: date | None = None
    end: date | None = None
    is_done: bool = False
    is_active: bool = False
    is_crit: bool = False
    is_milestone: bool = False
    after: str = ""  # task ID dependency

    @property
    def duration_days(self) -> int:
        if self.start and self.end:
            return (self.end - self.start).days
        return 0


@dataclass
class GanttSection:
    title: str
    tasks: list[GanttTask] = field(default_factory=list)


@dataclass
class Gantt:
    title: str = ""
    date_format: str = "YYYY-MM-DD"
    sections: list[GanttSection] = field(default_factory=list)
    vertical_markers: list[date] = field(default_factory=list)
    today_marker: bool = True
    warnings: list[str] = field(default_factory=list)


# Timelines
# ------------------------------------------------------------------------

@dataclass
class TimelineEvent:
    title: str
    details: list[str] = field(default_factory=list)


@dataclass
class TimelineSection:
    title: str
    events: list[TimelineEvent] = field(default_factory=list)


@dataclass
class Timeline:
    title: str = ""
    sections: list[TimelineSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Parsing
# ------------------------------------------------------------------------

# Gantt schedules
# ------------------------------------------------------------------------
#
# Syntax:
#     gantt
#         title Project Plan
#         dateFormat YYYY-MM-DD
#         section Design
#             Wireframes     :done, des1, 2024-01-01, 2024-01-14
#             Prototypes     :active, des2, 2024-01-08, 2024-01-21
#         section Development
#             Frontend       :dev1, after des2, 30d
#             Backend        :crit, dev2, 2024-01-15, 2024-03-01

# Mermaid (dayjs) date format tokens -> strptime directives
_FORMAT_TOKENS = {
    "YYYY": "%Y", "YY": "%y",
    "MM": "%m", "M": "%m",
    "DD": "%d", "D": "%d",
    "HH": "%H", "H": "%H",
    "mm": "%M", "ss": "%S",
}
_FORMAT_TOKEN_RE = re.compile("|".join(sorted(_FORMAT_TOKENS, key=len, reverse=True)))


def parse_gantt(text: str) -> Gantt:
    """Parse a mermaid gantt diagram definition."""
    lines = text.strip().splitlines()
    gantt = Gantt()

    if not lines:
        return gantt

    current_section: GanttSection | None = None
    tasks_by_id: dict[str, GanttTask] = {}

    for line in lines[1:]:  # skip "gantt" header
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        if lower.startswith("title "):
            gantt.title = stripped[6:].strip()
            continue

        if lower.startswith("dateformat "):
            gantt.date_format = stripped[11:].strip()
            continue

        if lower.startswith("axisformat ") or lower.startswith("excludes ") or lower.startswith("tickinterval ") or lower.startswith("weekend "):
            continue  # skip formatting directives

        if lower.startswith("todaymarker "):
            if "off" in lower:
                gantt.today_marker = False
            continue

        # Vertical marker: vert 2024-02-15
        if lower.startswith("vert "):
            d = _parse_date(stripped[5:].strip(), gantt.date_format)
            if d:
                gantt.vertical_markers.append(d)
            continue

        if lower.startswith("section "):
            current_section = GanttSection(title=stripped[8:].strip())
            gantt.sections.append(current_section)
            continue

        # Task line: "Title :tags, id, start, end/duration"
        if ":" in stripped:
            task = _parse_task(stripped, tasks_by_id, gantt.date_format)
            if task:
                if current_section is None:
                    current_section = GanttSection(title="")
                    gantt.sections.append(current_section)

                # Auto-chain: if no start and no after, start after the previous task
                if task.start is None and not task.after and current_section.tasks:
                    prev = current_section.tasks[-1]
                    if prev.end:
                        task.start = prev.end
                        if task.end is None and hasattr(task, '_duration_days'):
                            task.end = task.start + timedelta(days=task._duration_days)

                current_section.tasks.append(task)
                if task.id:
                    tasks_by_id[task.id] = task

    # Resolve "after" dependencies (multiple passes for chains)
    for _ in range(len(tasks_by_id) + 1):
        changed = False
        for section in gantt.sections:
            for task in section.tasks:
                if task.after and task.start is None:
                    # Multiple IDs: "after task1 task2" - use latest end date
                    after_ids = task.after.split()
                    latest_end: date | None = None
                    all_resolved = True
                    for aid in after_ids:
                        dep = tasks_by_id.get(aid)
                        if dep and dep.end:
                            if latest_end is None or dep.end > latest_end:
                                latest_end = dep.end
                        else:
                            all_resolved = False
                    if all_resolved and latest_end:
                        task.start = latest_end
                        if task.end is None and hasattr(task, '_duration_days'):
                            task.end = task.start + timedelta(days=task._duration_days)
                        changed = True
        if not changed:
            break

    return gantt


def _parse_task(line: str, tasks_by_id: dict[str, GanttTask], date_format: str) -> GanttTask | None:
    """Parse a task line like 'Title :done, id1, 2024-01-01, 2024-01-14'."""
    colon_idx = line.find(":")
    if colon_idx < 0:
        return None

    title = line[:colon_idx].strip()
    rest = line[colon_idx + 1:].strip()

    task = GanttTask(title=title)

    parts = [p.strip() for p in rest.split(",")]

    # Extract tags (done, active, crit, milestone)
    remaining: list[str] = []
    for part in parts:
        low = part.lower()
        if low == "done":
            task.is_done = True
        elif low == "active":
            task.is_active = True
        elif low == "crit":
            task.is_crit = True
        elif low == "milestone":
            task.is_milestone = True
        else:
            remaining.append(part)

    # Parse remaining: [id], [start|after X], [end|duration]
    for i, part in enumerate(remaining):
        low = part.lower()

        if low.startswith("after "):
            # Support multiple: "after task1 task2" - store all IDs
            task.after = part[6:].strip()
            continue

        # Try as duration (e.g., "30d", "2w")
        dur = _parse_duration(part)
        if dur is not None:
            task._duration_days = dur  # type: ignore[attr-defined]
            if task.start:
                task.end = task.start + timedelta(days=dur)
            continue

        # Try as date
        d = _parse_date(part, date_format)
        if d:
            if task.start is None:
                task.start = d
            else:
                task.end = d
            continue

        # Must be an ID
        if not task.id and re.match(r'^[a-zA-Z_]\w*$', part):
            task.id = part

    # Auto-generate ID if missing
    if not task.id:
        task.id = re.sub(r'[^a-zA-Z0-9]', '_', title.lower())[:20]

    return task


def _parse_date(text: str, date_format: str) -> date | None:
    """Parse a date string, honoring the diagram's dateFormat directive."""
    date_text = text.strip()
    # Try the declared dateFormat first (Mermaid/dayjs tokens)
    if date_format:
        fmt = _FORMAT_TOKEN_RE.sub(lambda m: _FORMAT_TOKENS[m.group(0)], date_format)
        try:
            return datetime.strptime(date_text, fmt).date()
        except ValueError:
            pass
    # Try ISO format
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', date_text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # Try MM/DD/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _parse_duration(text: str) -> int | None:
    """Parse a duration like '30d', '2w', '3m'."""
    duration_text = text.strip().lower()
    m = re.match(r'^(\d+)\s*(d|day|days|w|week|weeks|m|month|months)$', duration_text)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)[0]
    if unit == 'd':
        return val
    elif unit == 'w':
        return val * 7
    elif unit == 'm':
        return val * 30
    return None


# Timelines
# ------------------------------------------------------------------------
#
# Syntax:
#     timeline
#         title My Project
#         section Phase 1
#             Design : Wireframes, Mockups
#             Review : Stakeholder sign-off
#         section Phase 2
#             Build : Frontend, Backend

def parse_timeline(text: str) -> Timeline:
    """Parse a mermaid timeline definition."""
    lines = text.strip().splitlines()
    tl = Timeline()

    if not lines:
        return tl

    current_section: TimelineSection | None = None

    for line in lines[1:]:  # skip "timeline" header
        # Strip comments
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.strip()
        if not stripped:
            continue

        # Title
        if stripped.lower().startswith("title "):
            tl.title = stripped[6:].strip()
            continue

        # Section
        if stripped.lower().startswith("section "):
            current_section = TimelineSection(title=stripped[8:].strip())
            tl.sections.append(current_section)
            continue

        # Event: "Event name : detail1, detail2" or just "Event name"
        if current_section is None:
            # Auto-create a default section
            current_section = TimelineSection(title="")
            tl.sections.append(current_section)

        if " : " in stripped:
            title, details_str = stripped.split(" : ", 1)
            details = [d.strip() for d in details_str.split(",") if d.strip()]
        else:
            title = stripped
            details = []

        current_section.events.append(TimelineEvent(
            title=title.strip(),
            details=details,
        ))

    return tl


# Layout and drawing
# ------------------------------------------------------------------------

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
) -> Canvas:
    """Render a Gantt model to a Canvas."""
    if not diagram.sections:
        return Canvas(1, 1)

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
        return Canvas(1, 1)

    # Ensure at least 1 day range
    total_days = (max_date - min_date).days
    if total_days <= 0:
        total_days = 1
        max_date = min_date + timedelta(days=1)

    # Layout: labels start at column 3 and need a blank column before the axis
    margin_l = max_label_width + 4
    chart_w = max(10, width - margin_l - 1)

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

    canvas = Canvas(max(total_w + 1, display_width(diagram.title)), total_h + 1)

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
    n_ticks = max(1, min(6, total_days, chart_w // 8))
    for i in range(n_ticks + 1):
        d = min_date + timedelta(days=int(i / n_ticks * total_days))
        label = d.strftime("%b %d")
        col = margin_l + 1 + int(i / n_ticks * (chart_w - 2))
        # Tick mark
        canvas.put(axis_row, col, "+" if use_ascii else "┬", merge=False, style="edge")
        # Date label
        label_x = max(0, min(total_w - display_width(label),
                             col - display_width(label) // 2))
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
) -> Canvas:
    """Render a Timeline model to a Canvas."""
    cs = ASCII if use_ascii else UNICODE

    if not diagram.sections:
        return Canvas(1, 1)

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
    canvas = Canvas(width, height)
    for r, (line, style) in enumerate(styled_lines):
        canvas.put_text(r, 0, line, style=style)

    return canvas


def render_gantt_source(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.body
    options = {"width": config.max_width} if config.max_width is not None else {}
    canvas = render_gantt(parse_gantt(text), use_ascii=config.use_ascii, **options)
    return RenderResult(canvas)


def render_timeline_source(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.body
    canvas = render_timeline(parse_timeline(text), use_ascii=config.use_ascii)
    return RenderResult(canvas)
