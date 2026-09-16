"""Renderer for sequence diagrams.

Measures a SequenceLayout before drawing geometry and committing validated
message labels. Sequence placement remains independent of flowchart routing.
"""
from __future__ import annotations

from typing import Union
from copy import deepcopy
from dataclasses import dataclass, replace

from ..model.sequence import ActivateEvent, Block, BlockSection, DestroyEvent, Event, Message, Note, Participant, SequenceDiagram
from ..layout.scene import LayoutScene
from .charset import ASCII, UNICODE, CharSet
from .shapes import draw_rectangle, draw_cylinder
from ..utils import display_width, wrap_display_text
from ..layout.labels import LabelPlan, TextPlacement


# ── layout constants ──────────────────────────────────────────────
_BOX_PAD = 4          # horizontal padding inside participant boxes
_BOX_HEIGHT = 3       # participant box height
_ACTOR_HEIGHT = 5     # actor stick-figure height (head, body, legs, gap, label)
_SELF_LOOP_WIDTH_RATIO = 0.15
_MIN_SELF_LOOP_WIDTH = 10  # Eight visible cells plus the two-cell lifeline offset.
_MIN_GAP = 16         # minimum gap between participant centers
_EVENT_ROW_H = 2      # rows per message event
_NOTE_ROW_H = 4       # rows per note event (3-row box + 1 gap)
_BLOCK_START_H = 3    # rows for block start (border + label + gap)
_BLOCK_SECTION_H = 2  # rows for section break (dashed line + gap)
_BLOCK_END_H = 2      # rows for block end (bottom border + gap)
_TOP_MARGIN = 0
_BOTTOM_MARGIN = 1

# Height per participant kind (for header sizing)
_KIND_HEIGHT = {
    "participant": 3,
    "actor": 5,
    "database": 5,
    "queue": 5,
    "boundary": 5,
    "control": 5,
    "entity": 5,
    "collections": 5,
}


# ── Sentinel types for flattened events ──────────────────────────
class _BlockStart:
    """Marker for block start in flattened event list."""
    def __init__(self, block: Block, depth: int) -> None:
        self.block = block
        self.depth = depth

class _BlockSectionBreak:
    """Marker for else/and section in flattened event list."""
    def __init__(self, section: BlockSection, block: Block, depth: int) -> None:
        self.block = block
        self.section = section
        self.depth = depth

class _BlockEnd:
    """Marker for block end in flattened event list."""
    def __init__(self, block: Block, depth: int) -> None:
        self.block = block
        self.depth = depth


_FlatEvent = Union[Event, _BlockStart, _BlockSectionBreak, _BlockEnd]


@dataclass(frozen=True)
class SequenceLayout:
    """Measured geometry and labels, independent of character painting."""
    col_centers: list[int]
    box_widths: list[int]
    width: int
    height: int
    header_height: int
    row_offsets: list[int]
    block_bounds: dict[int, tuple[int, int]]
    message_labels: dict[int, TextPlacement]
    loop_widths: dict[int, int]


def _flatten_events(events: list[Event], depth: int = 0) -> list[_FlatEvent]:
    """Recursively flatten Block events into a linear list with boundary markers."""
    result: list[_FlatEvent] = []
    for ev in events:
        if isinstance(ev, Block):
            result.append(_BlockStart(ev, depth))
            result.extend(_flatten_events(ev.events, depth + 1))
            for section in ev.sections:
                result.append(_BlockSectionBreak(section, ev, depth))
                result.extend(_flatten_events(section.events, depth + 1))
            result.append(_BlockEnd(ev, depth))
        elif isinstance(ev, ActivateEvent):
            # ActivateEvents don't take a row; processed separately
            result.append(ev)
        else:
            result.append(ev)
    return result


def _note_lines(note: Note) -> list[str]:
    """Split note text into lines."""
    return note.text.split("\n") if "\n" in note.text else [note.text]


def _label_lines(label: str) -> list[str]:
    return label.split("\n") if "\n" in label else [label]


def _wrap_sequence_events(events: list[Event], max_width: int) -> None:
    """Wrap event-owned text before sequence dimensions are computed."""
    for event in events:
        if isinstance(event, Message):
            event.label = "\n".join(wrap_display_text(event.label, max_width))
        elif isinstance(event, Note):
            event.text = "\n".join(wrap_display_text(event.text, max_width))
        elif isinstance(event, Block):
            _wrap_sequence_events(event.events, max_width)
            for section in event.sections:
                _wrap_sequence_events(section.events, max_width)


def _participant_height(participant: Participant) -> int:
    line_count = len(_label_lines(participant.label))
    if participant.kind == "participant":
        return line_count + 2
    return _KIND_HEIGHT.get(participant.kind, 3) + line_count - 1


def _participant_index(diagram: SequenceDiagram, pid: str) -> int:
    for i, p in enumerate(diagram.participants):
        if p.id == pid:
            return i
    return -1


def _effective_label(msg: Message, msg_number: int | None) -> str:
    """Return the displayed label, with optional autonumber prefix."""
    if msg_number is not None:
        prefix = f"{msg_number}: "
        return prefix + msg.label if msg.label else prefix.rstrip()
    return msg.label


def _self_message_width(label: str) -> int:
    """Space for a self-message label, independent of its capped loop stroke."""
    return max(max(display_width(line) for line in _label_lines(label)) + 4, _MIN_SELF_LOOP_WIDTH)


def _plan_message_labels(
    diagram: SequenceDiagram,
    flat_events: list[_FlatEvent],
    original_labels: dict[int, str],
    col_centers: list[int],
    self_message_widths: dict[int, int],
) -> dict[int, TextPlacement]:
    """Choose a clear interval between lifelines for each complete message.

    Prefer fewer wrapped rows, then proximity to the sender. A long arrow
    can cross intermediate lifelines; its label must occupy a single gap.
    Keep wrapped text in the layout instead of mutating the message model.
    """
    placements: dict[int, TextPlacement] = {}
    message_number = 0
    for event_index, event in enumerate(flat_events):
        if not isinstance(event, Message):
            continue
        message_number += 1
        source_index = _participant_index(diagram, event.source)
        target_index = _participant_index(diagram, event.target)
        if source_index < 0 or target_index < 0:
            continue
        prefix = f"{message_number}: " if diagram.autonumber else ""
        original_label = prefix + original_labels[event_index]
        if source_index == target_index:
            intervals = [(col_centers[source_index] + 2,
                          col_centers[source_index] + self_message_widths[event_index] - 1)]
        else:
            first_index, last_index = sorted((source_index, target_index))
            intervals = [(col_centers[index] + 2, col_centers[index + 1] - 1)
                         for index in range(first_index, last_index)]
        candidates = [TextPlacement(
            f"message:{event_index}", 0, left,
            tuple(wrap_display_text(original_label, max(1, right - left))),
        ) for left, right in intervals]
        placements[event_index] = min(candidates, key=lambda placement: (
            placement.height, abs(placement.col - col_centers[source_index]),
        ))
    return placements


def _compute_layout(
    diagram: SequenceDiagram,
    autonumber: bool,
    flat_events: list[_FlatEvent],
    padding_x: int = _BOX_PAD,
    min_gap: int = _MIN_GAP,
    wrap_scope_labels: bool = False,
    *,
    original_message_labels: dict[int, str],
    self_message_widths: dict[int, int],
) -> SequenceLayout:
    """Measure participants, frames, message rectangles, and final event rows."""
    n = len(diagram.participants)
    if n == 0:
        return SequenceLayout([], [], 0, 0, 0, [], {}, {}, {})

    # Box widths based on label length
    natural_box_widths = [
        max(display_width(line) for line in _label_lines(p.label))
        + padding_x + 2
        for p in diagram.participants
    ]  # +2 for borders

    # Match this header row without letting one long name widen every box.
    matched_width = min(max(natural_box_widths), 25)
    box_widths = [max(width, matched_width) for width in natural_box_widths]

    # Header height: tallest participant kind
    header_height = max(_participant_height(p) for p in diagram.participants)

    # Compute per-event heights and effective labels for gap computation
    event_heights: list[int] = []
    effective_labels: list[str] = []
    msg_counter = 0
    for ev in flat_events:
        if isinstance(ev, ActivateEvent):
            # No row needed
            event_heights.append(0)
            effective_labels.append("")
        elif isinstance(ev, DestroyEvent):
            event_heights.append(_EVENT_ROW_H)
            effective_labels.append("")
        elif isinstance(ev, Note):
            lines = _note_lines(ev)
            note_h = len(lines) + 2 + 1  # border top + content lines + border bottom + gap
            event_heights.append(note_h)
            effective_labels.append("")
        elif isinstance(ev, _BlockStart):
            event_heights.append(_BLOCK_START_H + len(_label_lines(ev.block.label)) - 1)
            effective_labels.append("")
        elif isinstance(ev, _BlockSectionBreak):
            event_heights.append(_BLOCK_SECTION_H + len(_label_lines(ev.section.label)) - 1)
            effective_labels.append("")
        elif isinstance(ev, _BlockEnd):
            event_heights.append(_BLOCK_END_H)
            effective_labels.append("")
        elif isinstance(ev, Message):
            msg_counter += 1
            eff = _effective_label(ev, msg_counter if autonumber else None)
            effective_labels.append(eff)
            label_line_count = len(_label_lines(eff))
            if ev.source == ev.target:
                # Self-messages draw a 2-row loop below the label row
                event_heights.append(_EVENT_ROW_H + label_line_count)
            else:
                event_heights.append(_EVENT_ROW_H + label_line_count - 1)
        else:
            event_heights.append(0)
            effective_labels.append("")

    # Compute per-gap minimum widths based on message labels between adjacent pairs
    gap_mins = [min_gap] * (n - 1) if n > 1 else []

    # Ensure gaps are wide enough that participant boxes don't overlap
    for i in range(n - 1):
        box_gap_need = (box_widths[i] + box_widths[i + 1]) // 2 + 2
        gap_mins[i] = max(gap_mins[i], box_gap_need)

    for ev_idx, ev in enumerate(flat_events):
        if isinstance(ev, Note):
            # Notes may need gap expansion
            lines = _note_lines(ev)
            note_width = max(display_width(line) for line in lines) + 4
            for pid in ev.participants:
                pi = _participant_index(diagram, pid)
                if pi < 0:
                    continue
                if ev.position == "rightof" and pi < n - 1:
                    gap_mins[pi] = max(gap_mins[pi], note_width + 4)
                elif ev.position == "leftof" and pi > 0:
                    gap_mins[pi - 1] = max(gap_mins[pi - 1], note_width + 4)
            if ev.position == "over" and len(ev.participants) == 2:
                p1i = _participant_index(diagram, ev.participants[0])
                p2i = _participant_index(diagram, ev.participants[1])
                if p1i >= 0 and p2i >= 0:
                    lo, hi = min(p1i, p2i), max(p1i, p2i)
                    spans = hi - lo
                    per_gap = (note_width + spans - 1) // spans
                    for g in range(lo, hi):
                        gap_mins[g] = max(gap_mins[g], per_gap)
            continue

        if not isinstance(ev, Message):
            continue

        eff = effective_labels[ev_idx]
        si = _participant_index(diagram, ev.source)
        ti = _participant_index(diagram, ev.target)
        if si < 0 or ti < 0:
            continue
        if si == ti:
            if si < n - 1:
                gap_mins[si] = max(gap_mins[si], _self_message_width(eff) + 2)
            continue
        lo, hi = min(si, ti), max(si, ti)
        label_need = max(display_width(line) for line in _label_lines(eff)) + 6
        spans = hi - lo
        per_gap = (label_need + spans - 1) // spans
        for g in range(lo, hi):
            gap_mins[g] = max(gap_mins[g], per_gap)

    # Build center positions cumulatively
    col_centers = [0] * n
    col_centers[0] = box_widths[0] // 2 + 1  # left margin
    for i in range(1, n):
        col_centers[i] = col_centers[i - 1] + gap_mins[i - 1]

    # Account for self-messages and notes extending beyond participant headers.
    max_right = col_centers[-1] + box_widths[-1] // 2 + 2
    for event_index, event in enumerate(flat_events):
        if isinstance(event, Message) and event.source == event.target:
            source_index = _participant_index(diagram, event.source)
            if source_index >= 0:
                message_width = _self_message_width(effective_labels[event_index])
                max_right = max(max_right, col_centers[source_index] + message_width + 1)
        elif isinstance(event, Note):
            note_bounds = _note_bounds(event, col_centers, diagram)
            if note_bounds is not None:
                note_left, note_right = note_bounds
                # Notes outside a scope retain the drawing path's edge clamping.
                note_width = note_right - note_left + 1
                max_right = max(max_right, max(0, note_left) + note_width + 1)

    # Measure scopes from their contents, then reserve enough space on both sides.
    # Moving lifelines together preserves message geometry and keeps outer frames
    # outside their children even when the first participant is near column zero.
    raw_block_bounds = _compute_block_bounds(
        diagram, flat_events, col_centers, effective_labels,
        wrap_scope_labels=wrap_scope_labels,
    )
    left_shift = max(0, -min((left for left, _ in raw_block_bounds.values()), default=0))
    shifted_centers = [center + left_shift for center in col_centers]
    block_bounds = {
        block_id: (left + left_shift, right + left_shift)
        for block_id, (left, right) in raw_block_bounds.items()
    }
    framed_right = max((right + 1 for _, right in block_bounds.values()), default=0)

    canvas_width = max(max_right + left_shift, framed_right)
    # Text reserves its own clear region. Loop strokes have a separate cap
    # based on the measured diagram width, even when the label is much longer.
    loop_width_limit = max(_MIN_SELF_LOOP_WIDTH, int(canvas_width * _SELF_LOOP_WIDTH_RATIO))
    loop_widths = {index: min(message_width, loop_width_limit)
                   for index, message_width in self_message_widths.items()}
    measured_labels = _plan_message_labels(
        diagram, flat_events, original_message_labels, shifted_centers, self_message_widths,
    )

    # Compute row offsets after the final label wrapping, keeping horizontal
    # geometry fixed so a longer annotation cannot stretch its arrow or frame.
    lifeline_start = _TOP_MARGIN + header_height
    row_offsets: list[int] = []
    cumulative = lifeline_start + 1
    positioned_labels: dict[int, TextPlacement] = {}
    for event_index, h in enumerate(event_heights):
        event = flat_events[event_index]
        label_extra = 0
        if isinstance(event, Message) and event_index in measured_labels:
            measured_label = measured_labels[event_index]
            label_extra = measured_label.height - 1
            positioned_labels[event_index] = replace(measured_label, row=cumulative - 1)
        row_offsets.append(cumulative + label_extra)
        if isinstance(event, Message):
            cumulative += _EVENT_ROW_H + label_extra + int(event.source == event.target)
        elif isinstance(event, _BlockStart):
            cumulative += _BLOCK_START_H + len(_label_lines(event.block.label)) - 1
        elif isinstance(event, _BlockSectionBreak):
            cumulative += _BLOCK_SECTION_H + len(_label_lines(event.section.label)) - 1
        else:
            cumulative += h

    # Final vertical dimensions
    lifeline_end_row = cumulative
    canvas_height = lifeline_end_row + _BOTTOM_MARGIN

    return SequenceLayout(shifted_centers, box_widths, canvas_width, canvas_height,
                          header_height, row_offsets, block_bounds, positioned_labels, loop_widths)


# ── Participant drawing functions ─────────────────────────────────

def _put_centered_lines(
    canvas: LayoutScene, start_row: int, center_col: int, text: str,
    style: str = "label",
) -> None:
    for offset, line in enumerate(_label_lines(text)):
        canvas.put_text(
            start_row + offset,
            center_col - display_width(line) // 2,
            line,
            style=style,
        )


def _draw_actor(canvas: LayoutScene, cx: int, y: int, label: str, use_ascii: bool) -> None:
    """Draw a stick-figure actor, bottom-aligned to y + _ACTOR_HEIGHT - 1."""
    style = "node"
    canvas.put(y, cx, "O", merge=False, style=style)
    canvas.put(y + 1, cx - 1, "/", merge=False, style=style)
    canvas.put(y + 1, cx, "|", merge=False, style=style)
    canvas.put(y + 1, cx + 1, "\\", merge=False, style=style)
    canvas.put(y + 2, cx - 1, "/", merge=False, style=style)
    canvas.put(y + 2, cx + 1, "\\", merge=False, style=style)
    _put_centered_lines(canvas, y + 4, cx, label)


def _draw_database(
    canvas: LayoutScene, cx: int, y: int, width: int, height: int,
    label: str, cs: CharSet,
) -> None:
    """Draw a cylinder (database) participant."""
    bx = cx - width // 2
    draw_cylinder(canvas, bx, y, width, height, label, cs, style="node")


def _draw_queue(
    canvas: LayoutScene, cx: int, y: int, width: int, height: int,
    label: str, cs: CharSet, use_ascii: bool,
) -> None:
    """Draw a queue participant — box with doubled right border."""
    bx = cx - width // 2
    style = "node"
    h = height

    # Top border
    canvas.put(y, bx, cs.top_left, style=style)
    for c in range(bx + 1, bx + width - 1):
        canvas.put(y, c, cs.horizontal, style=style)
    canvas.put(y, bx + width - 1, cs.round_top_right if not use_ascii else cs.top_right, style=style)

    # Bottom border
    canvas.put(y + h - 1, bx, cs.bottom_left, style=style)
    for c in range(bx + 1, bx + width - 1):
        canvas.put(y + h - 1, c, cs.horizontal, style=style)
    canvas.put(y + h - 1, bx + width - 1, cs.round_bottom_right if not use_ascii else cs.bottom_right, style=style)

    # Side borders
    for r in range(y + 1, y + h - 1):
        canvas.put(r, bx, cs.vertical, style=style)
        # Double right border
        if not use_ascii:
            canvas.put(r, bx + width - 1, "║", merge=False, style=style)
        else:
            canvas.put(r, bx + width - 1, cs.vertical, style=style)

    # Label centered
    lines = _label_lines(label)
    label_row = y + max(1, (h - len(lines)) // 2)
    _put_centered_lines(canvas, label_row, cx, label)


def _draw_boundary(canvas: LayoutScene, cx: int, y: int, label: str, cs: CharSet, use_ascii: bool) -> None:
    """Draw a boundary symbol: small box with horizontal bar extending left."""
    style = "node"
    # Small 3x3 box centered on cx
    box_left = cx - 1
    box_right = cx + 1

    # Top of box
    canvas.put(y, box_left, cs.top_left, style=style)
    canvas.put(y, cx, cs.horizontal, style=style)
    canvas.put(y, box_right, cs.top_right, style=style)

    # Middle row: bar extending left + box sides
    bar_start = cx - 3
    canvas.put(y + 1, bar_start, cs.horizontal, merge=False, style=style)
    canvas.put(y + 1, bar_start + 1, cs.horizontal, merge=False, style=style)
    canvas.put(y + 1, box_left, cs.tee_left if not use_ascii else cs.vertical, style=style)
    canvas.put(y + 1, cx, " ", merge=False, style=style)
    canvas.put(y + 1, box_right, cs.vertical, style=style)

    # Bottom of box
    canvas.put(y + 2, box_left, cs.bottom_left, style=style)
    canvas.put(y + 2, cx, cs.horizontal, style=style)
    canvas.put(y + 2, box_right, cs.bottom_right, style=style)

    # Label below
    _put_centered_lines(canvas, y + 4, cx, label)


def _draw_control(canvas: LayoutScene, cx: int, y: int, label: str, cs: CharSet, use_ascii: bool) -> None:
    """Draw a control symbol: small circle with arrowhead above."""
    style = "node"
    # Arrowhead
    if use_ascii:
        canvas.put(y, cx, "<", merge=False, style=style)
    else:
        canvas.put(y, cx, "◁", merge=False, style=style)

    # Small rounded box
    canvas.put(y + 1, cx - 1, cs.round_top_left if not use_ascii else cs.top_left, style=style)
    canvas.put(y + 1, cx, cs.horizontal, style=style)
    canvas.put(y + 1, cx + 1, cs.round_top_right if not use_ascii else cs.top_right, style=style)
    canvas.put(y + 2, cx - 1, cs.round_bottom_left if not use_ascii else cs.bottom_left, style=style)
    canvas.put(y + 2, cx, cs.horizontal, style=style)
    canvas.put(y + 2, cx + 1, cs.round_bottom_right if not use_ascii else cs.bottom_right, style=style)

    # Label below
    _put_centered_lines(canvas, y + 4, cx, label)


def _draw_entity(canvas: LayoutScene, cx: int, y: int, label: str, cs: CharSet, use_ascii: bool) -> None:
    """Draw an entity symbol: small circle with underline."""
    style = "node"
    # Small rounded box
    canvas.put(y, cx - 1, cs.round_top_left if not use_ascii else cs.top_left, style=style)
    canvas.put(y, cx, cs.horizontal, style=style)
    canvas.put(y, cx + 1, cs.round_top_right if not use_ascii else cs.top_right, style=style)
    canvas.put(y + 1, cx - 1, cs.round_bottom_left if not use_ascii else cs.bottom_left, style=style)
    canvas.put(y + 1, cx, cs.horizontal, style=style)
    canvas.put(y + 1, cx + 1, cs.round_bottom_right if not use_ascii else cs.bottom_right, style=style)

    # Underline
    canvas.put(y + 2, cx - 1, cs.horizontal, merge=False, style=style)
    canvas.put(y + 2, cx, cs.horizontal, merge=False, style=style)
    canvas.put(y + 2, cx + 1, cs.horizontal, merge=False, style=style)

    # Label below
    _put_centered_lines(canvas, y + 4, cx, label)


def _draw_collections(
    canvas: LayoutScene, cx: int, y: int, width: int, height: int,
    label: str, cs: CharSet, use_ascii: bool,
) -> None:
    """Draw a collections symbol: two overlapping rectangles."""
    style = "node"
    bx = cx - width // 2
    h = height

    # Back rectangle (offset +1 right, 0 up) — just top and right edges visible
    # Top edge of back rectangle
    for c in range(bx + 2, bx + width + 1):
        canvas.put(y, c, cs.horizontal, style=style)
    canvas.put(y, bx + 1, cs.top_left, style=style)
    canvas.put(y, bx + width, cs.top_right, style=style)
    # Right edge of back rectangle
    canvas.put(y + 1, bx + width, cs.vertical, style=style)

    # Front rectangle
    canvas.put(y + 1, bx, cs.top_left, style=style)
    for c in range(bx + 1, bx + width - 1):
        canvas.put(y + 1, c, cs.horizontal, style=style)
    # Top-right corner of front connects to back rect's right edge
    canvas.put(y + 1, bx + width - 1, cs.top_right, style=style)

    # Bottom of back rect merges with top-right of front
    canvas.put(y + 2, bx + width, cs.bottom_right, style=style)

    # Side borders of front
    for r in range(y + 2, y + h - 1):
        canvas.put(r, bx, cs.vertical, style=style)
        canvas.put(r, bx + width - 1, cs.vertical, style=style)

    # Bottom border of back rect stub
    canvas.put(y + 2, bx + width - 1, cs.tee_left if not use_ascii else cs.vertical, style=style)
    canvas.put(y + 2, bx + width, cs.bottom_right, style=style)

    # Bottom border of front
    canvas.put(y + h - 1, bx, cs.bottom_left, style=style)
    for c in range(bx + 1, bx + width - 1):
        canvas.put(y + h - 1, c, cs.horizontal, style=style)
    canvas.put(y + h - 1, bx + width - 1, cs.bottom_right, style=style)

    # Label centered in front rectangle
    lines = _label_lines(label)
    label_row = y + 1 + max(0, (h - 2 - len(lines)) // 2)
    _put_centered_lines(canvas, label_row, cx, label)


def _draw_participant_header(
    canvas: LayoutScene, cx: int, bw: int, header_height: int,
    participant, cs: CharSet, use_ascii: bool,
) -> None:
    """Dispatch to the correct participant drawing function."""
    kind = participant.kind
    label = participant.label
    participant_height = _participant_height(participant)

    if kind == "actor":
        actor_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_actor(canvas, cx, actor_y, label, use_ascii)
    elif kind == "database":
        db_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_database(canvas, cx, db_y, bw, participant_height, label, cs)
    elif kind == "queue":
        q_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_queue(canvas, cx, q_y, bw, participant_height, label, cs, use_ascii)
    elif kind == "boundary":
        b_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_boundary(canvas, cx, b_y, label, cs, use_ascii)
    elif kind == "control":
        c_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_control(canvas, cx, c_y, label, cs, use_ascii)
    elif kind == "entity":
        e_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_entity(canvas, cx, e_y, label, cs, use_ascii)
    elif kind == "collections":
        col_y = _TOP_MARGIN + (header_height - participant_height)
        _draw_collections(
            canvas, cx, col_y, bw, participant_height, label, cs, use_ascii,
        )
    else:
        # Default: participant box
        box_height = header_height
        box_y = _TOP_MARGIN
        bx = cx - bw // 2
        draw_rectangle(canvas, bx, box_y, bw, box_height, label, cs, style="node")


def _compute_activation_ranges(flat_events: list[_FlatEvent], row_offsets: list[int]) -> dict[str, list[tuple[int, int]]]:
    """Compute activation ranges per participant from flattened events.

    Returns {participant_id: [(start_row, end_row), ...]}.
    """
    # Track open activations per participant
    open_activations: dict[str, list[int]] = {}  # pid -> [start_rows...]
    ranges: dict[str, list[tuple[int, int]]] = {}

    for idx, ev in enumerate(flat_events):
        if not isinstance(ev, ActivateEvent):
            continue
        row = row_offsets[idx]
        pid = ev.participant
        if ev.active:
            open_activations.setdefault(pid, []).append(row)
        else:
            # Close the most recent activation
            if pid in open_activations and open_activations[pid]:
                start = open_activations[pid].pop()
                ranges.setdefault(pid, []).append((start, row))

    # Close any still-open activations at the last row
    max_row = max(row_offsets) + 1 if row_offsets else 0
    for pid, starts in open_activations.items():
        for start in starts:
            ranges.setdefault(pid, []).append((start, max_row))

    return ranges


def _is_activated(ranges: dict[str, list[tuple[int, int]]], pid: str, row: int) -> bool:
    """Check if a participant is activated at a given row."""
    for start, end in ranges.get(pid, []):
        if start <= row <= end:
            return True
    return False


def render_sequence(
    diagram: SequenceDiagram,
    *,
    use_ascii: bool = False,
    padding_x: int = 4,
    gap: int = 16,
    max_label_width: int | None = None,
) -> LayoutScene:
    """Render a SequenceDiagram to a LayoutScene."""
    layout_diagram = deepcopy(diagram)
    cs = ASCII if use_ascii else UNICODE
    flat_events = _flatten_events(layout_diagram.events)
    original_message_labels = {
        index: event.label for index, event in enumerate(flat_events)
        if isinstance(event, Message)
    }

    if max_label_width is not None:
        for participant in layout_diagram.participants:
            participant.label = "\n".join(
                wrap_display_text(participant.label, max_label_width)
            )
        _wrap_sequence_events(layout_diagram.events, max_label_width)

    # Reserve label space independently of the shorter loop geometry.
    self_message_widths: dict[int, int] = {}
    message_number = 0
    for event_index, event in enumerate(flat_events):
        if isinstance(event, Message):
            message_number += 1
            if event.source == event.target:
                self_message_widths[event_index] = _self_message_width(
                    _effective_label(event, message_number if layout_diagram.autonumber else None),
                )

    layout = _compute_layout(
        layout_diagram, layout_diagram.autonumber, flat_events, padding_x=padding_x, min_gap=gap,
        wrap_scope_labels=max_label_width is not None,
        original_message_labels=original_message_labels,
        self_message_widths=self_message_widths,
    )
    col_centers = layout.col_centers
    box_widths = layout.box_widths
    width, height = layout.width, layout.height
    header_height = layout.header_height
    row_offsets = layout.row_offsets
    block_bounds = layout.block_bounds
    if width == 0:
        return LayoutScene(1, 1)

    canvas = LayoutScene(width, height)

    # Compute activation ranges
    activation_ranges = _compute_activation_ranges(flat_events, row_offsets)

    # ── 1. Draw participant headers at top ────────────────────────
    for i, p in enumerate(layout_diagram.participants):
        cx = col_centers[i]
        bw = box_widths[i]
        _draw_participant_header(canvas, cx, bw, header_height, p, cs, use_ascii)

    # ── Compute destroyed participants and their destruction rows ──
    destroyed: dict[str, int] = {}  # participant -> row where destroyed
    for idx, ev in enumerate(flat_events):
        if isinstance(ev, DestroyEvent) and ev.participant not in destroyed:
            destroyed[ev.participant] = row_offsets[idx]

    # ── 2. Draw lifelines ─────────────────────────────────────────
    lifeline_start = _TOP_MARGIN + header_height
    lifeline_end = height - _BOTTOM_MARGIN - 1
    lifeline_char = ":" if use_ascii else "┆"
    active_char = "[" if use_ascii else "║"
    for i, p in enumerate(layout_diagram.participants):
        cx = col_centers[i]
        end_row = destroyed.get(p.id, lifeline_end + 1)
        for r in range(lifeline_start, min(end_row, lifeline_end + 1)):
            if _is_activated(activation_ranges, p.id, r):
                canvas.put(r, cx, active_char, merge=False, style="edge")
            else:
                canvas.put(r, cx, lifeline_char, merge=False, style="edge")

    # ── 2.5 Draw continuous block side borders ─────────────────────
    block_border_stack: list[tuple[int, int, int]] = []  # (left, right, start_row)
    for idx, ev in enumerate(flat_events):
        row = row_offsets[idx]
        if isinstance(ev, _BlockStart):
            left, right = block_bounds[id(ev.block)]
            block_border_stack.append((left, right, row))
        elif isinstance(ev, _BlockEnd):
            if block_border_stack:
                left, right, start_row = block_border_stack.pop()
                for r in range(start_row + 1, row):
                    canvas.put(r, left, cs.vertical, merge=False, style="subgraph")
                    if right < canvas.width:
                        canvas.put(r, right, cs.vertical, merge=False, style="subgraph")

    # ── 3. Draw events (messages, notes, blocks) ──────────────────
    for idx, ev in enumerate(flat_events):
        row = row_offsets[idx]

        if isinstance(ev, ActivateEvent):
            # No visual output needed (lifeline already handles it)
            continue

        if isinstance(ev, DestroyEvent):
            pi = _participant_index(layout_diagram, ev.participant)
            if pi >= 0:
                cx = col_centers[pi]
                x_char = "X" if use_ascii else "╳"
                canvas.put(row, cx, x_char, merge=False, style="arrow")
            continue

        if isinstance(ev, Note):
            _draw_note(canvas, ev, row, col_centers, layout_diagram, cs, use_ascii)
            continue

        if isinstance(ev, _BlockStart):
            _draw_block_start(canvas, ev, row, block_bounds[id(ev.block)], cs, use_ascii)
            continue

        if isinstance(ev, _BlockSectionBreak):
            _draw_block_section(canvas, ev, row, block_bounds[id(ev.block)], cs, use_ascii)
            continue

        if isinstance(ev, _BlockEnd):
            _draw_block_end(canvas, ev, row, block_bounds[id(ev.block)], cs, use_ascii)
            continue

        if isinstance(ev, Message):
            si = _participant_index(layout_diagram, ev.source)
            ti = _participant_index(layout_diagram, ev.target)
            if si < 0 or ti < 0:
                continue

            if si == ti:
                _draw_self_message(
                    canvas, col_centers[si], row, ev, cs, use_ascii,
                    loop_width=layout.loop_widths[idx],
                )
            else:
                _draw_message(canvas, col_centers[si], col_centers[ti], row, ev, cs, use_ascii)

    label_plan = LabelPlan(canvas, canvas.width)
    for placement in layout.message_labels.values():
        if not label_plan.add(placement):
            raise ValueError(f"Sequence label conflicts with geometry: {placement.owner}")
    label_plan.paint(canvas)
    return canvas


# ── Block frame drawing ──────────────────────────────────────────

def _compute_block_bounds(
    diagram: SequenceDiagram,
    flat_events: list[_FlatEvent],
    col_centers: list[int],
    effective_labels: list[str],
    *, wrap_scope_labels: bool = False,
) -> dict[int, tuple[int, int]]:
    """Measure each frame bottom-up, including every branch and child frame."""
    block_bounds: dict[int, tuple[int, int]] = {}
    content_stack: list[list[tuple[int, int]]] = []
    for event_index, event in enumerate(flat_events):
        if isinstance(event, _BlockStart):
            content_stack.append([])
            continue
        if isinstance(event, _BlockEnd):
            contents = content_stack.pop()
            content_left = min((left for left, _ in contents), default=col_centers[0])
            content_right = max((right for _, right in contents), default=content_left)
            frame_left = content_left - 2
            if wrap_scope_labels:
                # Scope headings span the measured contents, independently of
                # the narrow participant/message label budget. Measure children
                # first so their frames remain inside the parent.
                prefix = f"[{event.block.kind}] "
                title_budget = max(content_right + 2 - frame_left - 1, len(prefix) + 2)
                wrapped_title = "\n".join(wrap_display_text(
                    prefix + event.block.label, title_budget,
                ))
                event.block.label = wrapped_title[len(prefix):]
                for section in event.block.sections:
                    if section.label:
                        wrapped_section = "\n".join(wrap_display_text(
                            f"[{section.label}]", max(3, title_budget - 2),
                        ))
                        section.label = wrapped_section[1:-1]
            title = f"[{event.block.kind}] {event.block.label}".rstrip()
            title_width = max(display_width(line) for line in _label_lines(title))
            section_width = max((
                display_width(line) + 2
                for section in event.block.sections
                for line in _label_lines(f"[{section.label}]")
            ), default=0)
            frame_right = max(content_right + 2, frame_left + max(title_width, section_width) + 2)
            frame_bounds = (frame_left, frame_right)
            block_bounds[id(event.block)] = frame_bounds
            if content_stack:
                content_stack[-1].append(frame_bounds)
            continue
        if not content_stack:
            continue
        if isinstance(event, Message):
            source_index = _participant_index(diagram, event.source)
            target_index = _participant_index(diagram, event.target)
            if source_index < 0 or target_index < 0:
                continue
            message_left = min(col_centers[source_index], col_centers[target_index])
            label_width = max(display_width(line) for line in _label_lines(effective_labels[event_index]))
            message_right = max(col_centers[source_index], col_centers[target_index])
            if source_index == target_index:
                message_right = message_left + max(label_width + 4, 8) - 1
            else:
                message_right = max(message_right, message_left + 1 + label_width)
            content_stack[-1].append((message_left, message_right))
        elif isinstance(event, Note):
            note_bounds = _note_bounds(event, col_centers, diagram)
            if note_bounds is not None:
                content_stack[-1].append(note_bounds)
        elif isinstance(event, (ActivateEvent, DestroyEvent)):
            participant_index = _participant_index(diagram, event.participant)
            if participant_index >= 0:
                participant_column = col_centers[participant_index]
                content_stack[-1].append((participant_column, participant_column))
    return block_bounds


def _draw_block_start(
    canvas: LayoutScene,
    ev: _BlockStart,
    row: int,
    frame_bounds: tuple[int, int],
    cs: CharSet,
    use_ascii: bool,
) -> None:
    """Draw the top border of a block frame with kind label."""
    left, right = frame_bounds
    h_char = cs.horizontal
    style = "subgraph"

    # Top border
    canvas.put(row, left, cs.top_left, merge=False, style=style)
    for c in range(left + 1, min(right, canvas.width)):
        canvas.put(row, c, h_char, merge=False, style=style)
    if right < canvas.width:
        canvas.put(row, right, cs.top_right, merge=False, style=style)

    # Hide lifelines only underneath the hint; preserve the rest of the row.
    label = f"[{ev.block.kind}] {ev.block.label}" if ev.block.label else f"[{ev.block.kind}]"
    label_col = left + 1
    for label_offset, label_line in enumerate(_label_lines(label), start=1):
        label_row = row + label_offset
        if label_row >= canvas.height:
            break
        canvas.put(label_row, left, cs.vertical, merge=False, style=style)
        if right < canvas.width:
            canvas.put(label_row, right, cs.vertical, merge=False, style=style)
        canvas.put_text(label_row, label_col, label_line, style="subgraph_label", overwrite_spaces=True)


def _draw_block_section(
    canvas: LayoutScene,
    ev: _BlockSectionBreak,
    row: int,
    frame_bounds: tuple[int, int],
    cs: CharSet,
    use_ascii: bool,
) -> None:
    """Draw a dashed horizontal divider for else/and sections."""
    left, right = frame_bounds
    dash = "." if use_ascii else "┄"
    style = "subgraph"

    canvas.put(row, left, cs.vertical, merge=False, style=style)
    for c in range(left + 1, min(right, canvas.width)):
        canvas.put(row, c, dash, merge=False, style=style)
    if right < canvas.width:
        canvas.put(row, right, cs.vertical, merge=False, style=style)

    # Section label after left border
    if ev.section.label:
        for label_offset, label_line in enumerate(_label_lines(f"[{ev.section.label}]")):
            canvas.put_text(
                row + label_offset, left + 2, label_line,
                style="subgraph_label", overwrite_spaces=True,
            )


def _draw_block_end(
    canvas: LayoutScene,
    ev: _BlockEnd,
    row: int,
    frame_bounds: tuple[int, int],
    cs: CharSet,
    use_ascii: bool,
) -> None:
    """Draw the bottom border of a block frame."""
    left, right = frame_bounds
    h_char = cs.horizontal
    style = "subgraph"

    canvas.put(row, left, cs.bottom_left, merge=False, style=style)
    for c in range(left + 1, min(right, canvas.width)):
        canvas.put(row, c, h_char, merge=False, style=style)
    if right < canvas.width:
        canvas.put(row, right, cs.bottom_right, merge=False, style=style)


# ── Note drawing ─────────────────────────────────────────────────

def _note_bounds(
    note: Note, col_centers: list[int], diagram: SequenceDiagram,
) -> tuple[int, int] | None:
    """Return inclusive note columns before canvas-edge clamping."""
    if not note.participants:
        return None
    lines = _note_lines(note)
    note_width = max(display_width(line) for line in lines) + 4
    # Determine horizontal placement
    if note.position == "rightof":
        pi = _participant_index(diagram, note.participants[0])
        if pi < 0:
            return None
        note_x = col_centers[pi] + 2
    elif note.position == "leftof":
        pi = _participant_index(diagram, note.participants[0])
        if pi < 0:
            return None
        note_x = col_centers[pi] - 2 - note_width
    elif note.position == "over":
        if len(note.participants) == 2:
            p1i = _participant_index(diagram, note.participants[0])
            p2i = _participant_index(diagram, note.participants[1])
            if p1i < 0 or p2i < 0:
                return None
            center = (col_centers[p1i] + col_centers[p2i]) // 2
            # Ensure spanning note covers both lifelines
            span_width = abs(col_centers[p1i] - col_centers[p2i]) + 4
            note_width = max(note_width, span_width)
        else:
            pi = _participant_index(diagram, note.participants[0])
            if pi < 0:
                return None
            center = col_centers[pi]
        note_x = center - note_width // 2
    else:
        return None

    return note_x, note_x + note_width - 1


def _draw_note(
    canvas: LayoutScene,
    note: Note,
    row: int,
    col_centers: list[int],
    diagram: SequenceDiagram,
    cs: CharSet,
    use_ascii: bool,
) -> None:
    """Draw a note box at the given row."""
    lines = _note_lines(note)
    note_height = len(lines) + 2
    note_bounds = _note_bounds(note, col_centers, diagram)
    if note_bounds is None:
        return
    raw_left, raw_right = note_bounds
    note_x = max(0, raw_left)
    note_width = raw_right - raw_left + 1

    # Clear the interior so lifeline chars don't bleed through
    for r in range(row, row + note_height):
        for c in range(note_x, note_x + note_width):
            if 0 <= r < canvas.height and 0 <= c < canvas.width:
                canvas._grid[r][c] = " "

    draw_rectangle(canvas, note_x, row, note_width, note_height, note.text, cs, style="node")


# ── Message drawing ──────────────────────────────────────────────

def _draw_message(
    canvas: LayoutScene,
    src_col: int,
    tgt_col: int,
    row: int,
    msg: Message,
    cs: CharSet,
    use_ascii: bool,
) -> None:
    """Draw a horizontal message arrow between two lifelines."""
    # One blank cell separates each arrow end from its participant lifeline.
    left = min(src_col, tgt_col) + 2
    right = max(src_col, tgt_col) - 2
    going_right = tgt_col > src_col

    # Line character
    if msg.line_type == "dotted":
        h_char = "." if use_ascii else "┄"
    else:
        h_char = "-" if use_ascii else "─"

    # Unavoidable crossings through uninvolved lifelines stay distinguishable
    # from endpoints; the participant lines at either end remain untouched.
    for c in range(left + 1, right):
        existing_character = canvas.get(row, c)
        crossing = existing_character in ("┆", "║", ":", "[")
        segment_character = "x" if crossing else h_char
        canvas.put(row, c, segment_character, merge=False, style="edge")

    # Arrowhead at target
    if msg.arrow_type == "bidirectional":
        # Arrowheads at both ends
        if use_ascii:
            canvas.put(row, left, "<", merge=False, style="arrow")
            canvas.put(row, right, ">", merge=False, style="arrow")
        else:
            canvas.put(row, left, "◀", merge=False, style="arrow")
            canvas.put(row, right, "▶", merge=False, style="arrow")
    elif msg.arrow_type == "arrow":
        if going_right:
            arrow = ">" if use_ascii else "▶"
            canvas.put(row, right, arrow, merge=False, style="arrow")
            canvas.put(row, left, h_char, merge=False, style="edge")
        else:
            arrow = "<" if use_ascii else "◀"
            canvas.put(row, left, arrow, merge=False, style="arrow")
            canvas.put(row, right, h_char, merge=False, style="edge")
    elif msg.arrow_type == "cross":
        if going_right:
            canvas.put(row, right, "x", merge=False, style="arrow")
            canvas.put(row, left, h_char, merge=False, style="edge")
        else:
            canvas.put(row, left, "x", merge=False, style="arrow")
            canvas.put(row, right, h_char, merge=False, style="edge")
    elif msg.arrow_type == "async":
        if going_right:
            canvas.put(row, right, ")", merge=False, style="arrow")
            canvas.put(row, left, h_char, merge=False, style="edge")
        else:
            canvas.put(row, left, "(", merge=False, style="arrow")
            canvas.put(row, right, h_char, merge=False, style="edge")
    else:
        # "open" — no arrowhead, just line to endpoints
        canvas.put(row, left, h_char, merge=False, style="edge")
        canvas.put(row, right, h_char, merge=False, style="edge")



def _draw_self_message(
    canvas: LayoutScene,
    col: int,
    row: int,
    msg: Message,
    cs: CharSet,
    use_ascii: bool,
    *, loop_width: int,
) -> None:
    """Draw a self-referencing message (loop to the right)."""

    if msg.line_type == "dotted":
        h_char = "." if use_ascii else "┄"
        v_char = ":" if use_ascii else "┆"
    else:
        h_char = "-" if use_ascii else "─"
        v_char = "|" if use_ascii else "│"

    # Top horizontal line going right
    for c in range(col + 2, col + loop_width):
        canvas.put(row, c, h_char, merge=False, style="edge")

    # Vertical line going down
    right_col = col + loop_width - 1
    canvas.put(row + 1, right_col, v_char, merge=False, style="edge")

    # Bottom horizontal line going left back to lifeline
    for c in range(col + 2, col + loop_width):
        canvas.put(row + 1, c, h_char, merge=False, style="edge")

    # Arrowhead pointing back at lifeline
    if msg.arrow_type == "arrow":
        arrow = "<" if use_ascii else "◀"
        canvas.put(row + 1, col + 2, arrow, merge=False, style="arrow")
    elif msg.arrow_type == "cross":
        canvas.put(row + 1, col + 2, "x", merge=False, style="arrow")
    elif msg.arrow_type == "async":
        canvas.put(row + 1, col + 2, "(", merge=False, style="arrow")
    else:
        canvas.put(row + 1, col + 2, h_char, merge=False, style="edge")

    # Corners
    if not use_ascii:
        canvas.put(row, right_col, "┐", merge=False, style="edge")
        canvas.put(row + 1, right_col, "┘", merge=False, style="edge")
    else:
        canvas.put(row, right_col, "+", merge=False, style="edge")
        canvas.put(row + 1, right_col, "+", merge=False, style="edge")
