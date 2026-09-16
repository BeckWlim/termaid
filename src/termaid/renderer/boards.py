"""Terminal renderers for user journeys, kanban boards."""
from __future__ import annotations

from ..layout.scene import LayoutScene
from ..model.boards import Journey, Kanban
from ..utils import display_width, truncate_to_width
from .charset import ASCII, UNICODE, CharSet


# User journeys
# ------------------------------------------------------------------------
#
# Renders a horizontal journey with tasks as boxes along a timeline,
# grouped by sections, with satisfaction scores shown as emoji faces
# and actor indicators.

_FACE = {
    1: "😞",
    2: "😟",
    3: "😐",
    4: "😊",
    5: "😄",
}

_FACE_ASCII = {
    1: ":((",
    2: ":( ",
    3: ":-|",
    4: ":) ",
    5: ":D ",
}


def render_journey(
    diagram: Journey,
    *,
    use_ascii: bool = False,
    padding_x: int = 2,
    gap: int = 1,
    rounded: bool = True,
) -> LayoutScene:
    """Render a Journey model to a LayoutScene."""
    if not diagram.sections:
        return LayoutScene(1, 1)

    faces = _FACE_ASCII if use_ascii else _FACE
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    if use_ascii:
        tl, tr, bl, br = "+", "+", "+", "+"
    elif rounded:
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
    else:
        tl, tr, bl, br = "┌", "┐", "└", "┘"
    arrow = ">" if use_ascii else "▶"
    dot = "o" if use_ascii else "●"

    # Collect all tasks and compute widths
    all_tasks: list[tuple[str, list[dict]]] = []  # (section_title, tasks)
    all_actors: set[str] = set()
    task_width = max(8, padding_x * 4)  # minimum task box width

    for section in diagram.sections:
        tasks_data = []
        for task in section.tasks:
            w = max(task_width, display_width(task.title) + padding_x * 2)
            tasks_data.append({"title": task.title, "score": task.score,
                               "actors": task.actors, "width": w})
            for a in task.actors:
                all_actors.add(a)
        all_tasks.append((section.title, tasks_data))

    # Layout: compute x positions for each task
    task_gap = gap
    section_gap = gap + 2
    x_pos = 2  # starting x

    task_positions: list[tuple[int, int, dict, int]] = []  # (x, w, task_data, section_idx)
    section_spans: list[tuple[int, int, str]] = []  # (x_start, x_end, title)

    for si, (sec_title, tasks) in enumerate(all_tasks):
        if si > 0:
            x_pos += section_gap
        sec_start = x_pos
        for ti, td in enumerate(tasks):
            w = td["width"]
            task_positions.append((x_pos, w, td, si))
            x_pos += w + task_gap
        sec_end = x_pos - task_gap
        section_spans.append((sec_start, sec_end, sec_title))

    total_w = x_pos + 4
    actors_list = sorted(all_actors) if all_actors else []

    # Compute rows
    title_row = 0
    actor_row = 2 if diagram.title else 0
    section_row = actor_row + len(actors_list) + 1
    timeline_row = section_row + 2
    task_row = timeline_row  # task boxes on the timeline
    face_row = task_row + 3
    total_h = face_row + 2

    canvas = LayoutScene(total_w + 1, total_h + 1)

    # Title
    if diagram.title:
        canvas.put_text(title_row, 2, diagram.title, style="label")

    # Actor legend with distinct symbols
    _actor_symbols = ["●", "◆", "■", "▲", "★", "◉", "◈", "▶"] if not use_ascii else ["*", "+", "#", "^", "@", "o", "x", ">"]

    # Actor legend
    for ai, actor in enumerate(actors_list):
        row = actor_row + ai
        style = f"sectionfg:{ai}"
        sym = _actor_symbols[ai % len(_actor_symbols)]
        canvas.put(row, 2, sym, merge=False, style=style)
        canvas.put_text(row, 4, actor, style=style)

    # Section spans (above task boxes)
    for si, (sx, ex, title) in enumerate(section_spans):
        style = f"section:{si}"
        # Draw section bar
        canvas.put(section_row, sx, tl, merge=False, style=style)
        for c in range(sx + 1, ex):
            canvas.put(section_row, c, hz, merge=False, style=style)
        canvas.put(section_row, ex, tr, merge=False, style=style)
        # Center title in the bar, clearing the border chars underneath
        title_x = sx + (ex - sx - display_width(title)) // 2
        title_x = max(sx + 1, title_x)
        # Clear space for title (overwrite ─ with spaces)
        for c in range(title_x - 1, title_x + display_width(title) + 1):
            if sx < c < ex:
                canvas._grid[section_row][c] = " "
        canvas.put_text(section_row, title_x, title, style=style)

    # Timeline arrow
    for c in range(1, total_w - 1):
        canvas.put(timeline_row + 1, c, hz, merge=False, style="edge")
    canvas.put(timeline_row + 1, total_w - 1, arrow, merge=False, style="edge")

    # Task boxes on the timeline
    for x, w, td, si in task_positions:
        style = f"section:{si}"
        # Box
        canvas.put(task_row, x, tl, merge=False, style=style)
        for c in range(x + 1, x + w - 1):
            canvas.put(task_row, c, hz, merge=False, style=style)
        canvas.put(task_row, x + w - 1, tr, merge=False, style=style)

        canvas.put(task_row + 1, x, vt, merge=False, style=style)
        canvas.put(task_row + 1, x + w - 1, vt, merge=False, style=style)

        canvas.put(task_row + 2, x, bl, merge=False, style=style)
        for c in range(x + 1, x + w - 1):
            canvas.put(task_row + 2, c, hz, merge=False, style=style)
        canvas.put(task_row + 2, x + w - 1, br, merge=False, style=style)

        # Task title centered (clear interior first to remove timeline ─)
        title = td["title"]
        for c in range(x + 1, x + w - 1):
            canvas._grid[task_row + 1][c] = " "
        tx = x + (w - display_width(title)) // 2
        canvas.put_text(task_row + 1, tx, title, style=style)

        # Dot on timeline below the task box
        mid_x = x + w // 2

        # Actor symbols inside the task box (top-left corner)
        actor_x = x + 1
        for ai, actor in enumerate(actors_list):
            if actor in td["actors"]:
                sym = _actor_symbols[ai % len(_actor_symbols)]
                canvas.put(task_row, actor_x, sym, merge=False,
                          style=f"sectionfg:{ai}")
                actor_x += 1

        # Face below task
        score = td["score"]
        face = faces.get(score, faces[3])
        face_x = x + (w - display_width(face)) // 2
        canvas.put_text(face_row, face_x, face, style="edge_label")

    return canvas


# Kanban boards
# ------------------------------------------------------------------------
#
# Renders columns side by side with cards stacked vertically inside
# each column, using box-drawing characters for borders.

_COL_PAD = 2      # horizontal padding inside columns
_CARD_PAD = 1     # padding inside card borders
_COL_GAP = 2      # gap between columns
_CARD_GAP = 1     # gap between cards in a column


def render_kanban(
    diagram: Kanban,
    *,
    use_ascii: bool = False,
    padding_x: int = _CARD_PAD,
    gap: int = _COL_GAP,
) -> LayoutScene:
    """Render a Kanban model to a LayoutScene."""
    cs = ASCII if use_ascii else UNICODE

    if not diagram.columns:
        return LayoutScene(1, 1)

    # Compute column widths (based on widest card or column title).
    # Card text sits inside card borders, inset _COL_PAD from each column
    # edge; the centered title needs the column borders plus a space each
    # side. padding_x beyond the default adds extra slack.
    col_widths: list[int] = []
    for col in diagram.columns:
        title_w = display_width(col.title)
        card_w = max((display_width(card.title) + (display_width(card.metadata) + 1 if card.metadata else 0)
                      for card in col.cards), default=0)
        need = max(title_w + 4, card_w + 2 + 2 * _COL_PAD)
        col_widths.append(max(need + (padding_x - _CARD_PAD) * 2, 10))

    # Compute column heights (title + cards)
    col_heights: list[int] = []
    for col in diagram.columns:
        h = 3  # top border + title + separator
        for ci, card in enumerate(col.cards):
            h += 3  # card: top + content + bottom
            if ci < len(col.cards) - 1:
                h += _CARD_GAP
        h += 1  # bottom border
        col_heights.append(h)

    total_height = max(col_heights) if col_heights else 4
    total_width = sum(col_widths) + gap * (len(col_widths) - 1)

    canvas = LayoutScene(total_width + 1, total_height + 1)

    # Draw each column with a rotating section style
    x = 0
    for ci, col in enumerate(diagram.columns):
        w = col_widths[ci]
        section_style = f"section:{ci}"
        _draw_column(canvas, cs, col, x, 0, w, total_height, use_ascii, section_style)
        x += w + gap

    return canvas


def _draw_column(
    canvas: LayoutScene, cs: CharSet,
    col, x: int, y: int, w: int, h: int,
    use_ascii: bool,
    section_style: str = "subgraph",
) -> None:
    """Draw a single kanban column with its cards."""
    tl = "+" if use_ascii else "╭"
    tr = "+" if use_ascii else "╮"
    bl = "+" if use_ascii else "╰"
    br = "+" if use_ascii else "╯"
    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"

    # Fill entire column interior with section bg (for solid themes)
    card_style = section_style + ":deep"
    for r in range(y + 1, y + h - 1):
        for c in range(x + 1, x + w - 1):
            canvas._style_grid[r][c] = section_style

    # Column border
    canvas.put_text(y, x, tl + hz * (w - 2) + tr, style=section_style)
    canvas.put_text(y + h - 1, x, bl + hz * (w - 2) + br, style=section_style)
    for r in range(y + 1, y + h - 1):
        canvas.put(r, x, vt, merge=False, style=section_style)
        canvas.put(r, x + w - 1, vt, merge=False, style=section_style)

    # Column title (centered, bold)
    title = truncate_to_width(col.title, w - 4)
    title_x = x + (w - display_width(title)) // 2
    canvas.put_text(y + 1, title_x, title, style=section_style)

    # Separator under title
    sep = hz * (w - 2)
    canvas.put_text(y + 2, x + 1, sep, style=section_style)

    # Cards
    card_y = y + 3
    card_tl = "+" if use_ascii else "┌"
    card_tr = "+" if use_ascii else "┐"
    card_bl = "+" if use_ascii else "└"
    card_br = "+" if use_ascii else "┘"
    card_hz = "-" if use_ascii else "─"
    card_vt = "|" if use_ascii else "│"

    for ci, card in enumerate(col.cards):
        cw = w - 2 * _COL_PAD
        cx = x + _COL_PAD

        # Card box (lighter shade of column color)
        canvas.put_text(card_y, cx, card_tl + card_hz * (cw - 2) + card_tr, style=card_style)
        canvas.put(card_y + 1, cx, card_vt, merge=False, style=card_style)
        canvas.put(card_y + 1, cx + cw - 1, card_vt, merge=False, style=card_style)
        canvas.put_text(card_y + 2, cx, card_bl + card_hz * (cw - 2) + card_br, style=card_style)

        # Card interior bg
        for c in range(cx + 1, cx + cw - 1):
            canvas._style_grid[card_y + 1][c] = card_style

        # Card content
        text = card.title
        if card.metadata:
            text += " " + card.metadata
        text = truncate_to_width(text, cw - 2)
        canvas.put_text(card_y + 1, cx + 1, text, style=card_style)

        card_y += 3 + _CARD_GAP
