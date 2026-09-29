"""Packet diagrams: models, parsing, layout, and drawing."""
from __future__ import annotations

from termaid.core.contracts import ParsedSource, RenderConfig, RenderResult

from dataclasses import dataclass, field
import re
from termaid.utils import display_width, truncate_to_width, wrap_display_text
from termaid.core.canvas import Canvas


# Model
# ------------------------------------------------------------------------

@dataclass
class PacketField:
    start: int
    end: int  # inclusive
    label: str

    @property
    def bits(self) -> int:
        return self.end - self.start + 1


@dataclass
class Packet:
    fields: list[PacketField] = field(default_factory=list)
    row_bits: int = 32  # bits per row (standard network packet)
    warnings: list[str] = field(default_factory=list)


# Parsing
# ------------------------------------------------------------------------

def parse_packet(text: str) -> Packet:
    """Parse a mermaid packet diagram definition."""
    lines = text.strip().splitlines()
    packet = Packet()

    if not lines:
        return packet

    next_bit = 0

    for line in lines[1:]:  # skip "packet-beta" header
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.strip()
        if not stripped:
            continue

        # Try: start-end: "label" or start-end: label
        m = re.match(r'^(\d+)\s*-\s*(\d+)\s*:\s*"?([^"]*)"?', stripped)
        if m:
            start = int(m.group(1))
            end = int(m.group(2))
            label = m.group(3).strip()
            packet.fields.append(PacketField(start=start, end=end, label=label))
            next_bit = end + 1
            continue

        # Try: +N: "label" (auto-increment)
        m = re.match(r'^\+(\d+)\s*:\s*"?([^"]*)"?', stripped)
        if m:
            count = int(m.group(1))
            label = m.group(2).strip()
            start = next_bit
            end = start + count - 1
            packet.fields.append(PacketField(start=start, end=end, label=label))
            next_bit = end + 1
            continue

        # Try: start: "label" (single bit)
        m = re.match(r'^(\d+)\s*:\s*"?([^"]*)"?', stripped)
        if m:
            start = int(m.group(1))
            label = m.group(2).strip()
            packet.fields.append(PacketField(start=start, end=start, label=label))
            next_bit = start + 1
            continue

    return packet


# Layout and drawing
# ------------------------------------------------------------------------

_BITS_PER_COL = 3  # character columns per bit


def render_packet(
    diagram: Packet,
    *,
    use_ascii: bool = False,
    rounded: bool = True,
    padding_y: int = 1,
    max_width: int | None = None,
) -> Canvas:
    """Render a Packet model to a Canvas."""
    if not diagram.fields:
        return Canvas(1, 1)

    row_bits = diagram.row_bits
    if max_width is not None:
        while row_bits > max(1, max_width - 2):
            row_bits = max(1, row_bits // 2)
    bits_per_col = (_BITS_PER_COL if max_width is None else
                    max(1, min(_BITS_PER_COL, (max_width - 2) // row_bits)))
    cols_per_row = row_bits * bits_per_col

    hz = "-" if use_ascii else "─"
    vt = "|" if use_ascii else "│"
    if use_ascii:
        tl, tr, bl, br = "+", "+", "+", "+"
        tj, bj = "+", "+"
    elif rounded:
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
        tj, bj = "┬", "┴"
    else:
        tl, tr, bl, br = "┌", "┐", "└", "┘"
        tj, bj = "┬", "┴"

    margin = 1

    # Group fields into rows
    rows: list[list[tuple[int, int, str]]] = []
    for field in diagram.fields:
        bit = field.start
        remaining_label = field.label
        while bit <= field.end:
            row_idx = bit // row_bits
            col_in_row = bit % row_bits
            bits_in_this_row = min(field.end - bit + 1, row_bits - col_in_row)
            col_start = col_in_row
            col_end = col_in_row + bits_in_this_row - 1

            while len(rows) <= row_idx:
                rows.append([])

            rows[row_idx].append((col_start, col_end, remaining_label))
            remaining_label = ""
            bit += bits_in_this_row

    # Each row: 1 (numbers) + 1 (top border) + padding_y (content) + 1 (bottom border)
    row_h = 3 + padding_y
    total_h = len(rows) * row_h
    total_w = margin + cols_per_row + 1

    canvas = Canvas(total_w + 4, total_h + 10)  # extra for legend

    for ri, row_fields in enumerate(rows):
        y_nums = ri * row_h
        y_top = ri * row_h + 1
        y_bottom = ri * row_h + 2 + padding_y
        y_content = y_top + (padding_y + 1) // 2
        row_start_bit = ri * row_bits

        # --- Bit numbers ---
        placed_nums: set[int] = set()

        # Only show bit numbers for fields wide enough to display them
        # without crowding. Skip intermediate numbers for narrow fields.
        min_field_cols = 4  # minimum columns to show a number

        # End label of the entire row (right-aligned, always shown)
        if row_fields:
            last_ce = row_fields[-1][1]
            end_bit = row_start_bit + last_ce
            end_label = str(end_bit)
            ex = margin + (last_ce + 1) * bits_per_col - display_width(end_label)
            canvas.put_text(y_nums, ex, end_label, style="edge_label")
            for px in range(ex, ex + display_width(end_label) + 1):
                placed_nums.add(px)

        # Start label of the entire row (left-aligned, always shown)
        if row_fields:
            first_cs = row_fields[0][0]
            start_bit = row_start_bit + first_cs
            start_label = str(start_bit)
            sx = margin + first_cs * bits_per_col
            if sx + display_width(start_label) < ex:
                canvas.put_text(y_nums, sx, start_label, style="edge_label")
                for px in range(sx, sx + display_width(start_label)):
                    placed_nums.add(px)

        # Intermediate boundary numbers (only when fields are wide enough)
        for fi in range(1, len(row_fields)):
            cs, ce, _ = row_fields[fi]
            prev_cs, prev_ce, _ = row_fields[fi - 1]
            prev_width = (prev_ce - prev_cs + 1) * bits_per_col
            cur_width = (ce - cs + 1) * bits_per_col

            # Show end of previous field
            if prev_width >= min_field_cols:
                end_bit = row_start_bit + prev_ce
                end_label = str(end_bit)
                ex = margin + (prev_ce + 1) * bits_per_col - display_width(end_label)
                if not any(p in placed_nums for p in range(ex, ex + display_width(end_label) + 1)):
                    canvas.put_text(y_nums, ex, end_label, style="edge_label")
                    for px in range(ex, ex + display_width(end_label) + 1):
                        placed_nums.add(px)

            # Show start of current field
            if cur_width >= min_field_cols:
                start_bit = row_start_bit + cs
                start_label = str(start_bit)
                sx = margin + cs * bits_per_col + 1
                if not any(p in placed_nums for p in range(sx, sx + display_width(start_label))):
                    canvas.put_text(y_nums, sx, start_label, style="edge_label")
                    for px in range(sx, sx + display_width(start_label)):
                        placed_nums.add(px)

        # --- Top border ---
        canvas.put(y_top, margin, tl, merge=False, style="node")
        for c in range(1, cols_per_row):
            canvas.put(y_top, margin + c, hz, merge=False, style="node")
        canvas.put(y_top, margin + cols_per_row, tr, merge=False, style="node")

        # Field separators on top border
        for cs, ce, _ in row_fields:
            if cs > 0:
                canvas.put(y_top, margin + cs * bits_per_col, tj, merge=False, style="node")

        # --- Content rows ---
        for py in range(padding_y):
            yr = y_top + 1 + py
            canvas.put(yr, margin, vt, merge=False, style="node")
            canvas.put(yr, margin + cols_per_row, vt, merge=False, style="node")
            for cs, ce, _ in row_fields:
                if cs > 0:
                    canvas.put(yr, margin + cs * bits_per_col, vt, merge=False, style="node")

        # Labels centered
        for cs, ce, label in row_fields:
            x_start = margin + cs * bits_per_col
            x_end = margin + (ce + 1) * bits_per_col
            field_w = x_end - x_start

            if label:
                avail = field_w - 2
                disp_label = truncate_to_width(label, avail)
                lx = x_start + 1 + (avail - display_width(disp_label)) // 2
                canvas.put_text(y_content, lx, disp_label, style="label")

        # --- Bottom border ---
        canvas.put(y_bottom, margin, bl, merge=False, style="node")
        for c in range(1, cols_per_row):
            canvas.put(y_bottom, margin + c, hz, merge=False, style="node")
        canvas.put(y_bottom, margin + cols_per_row, br, merge=False, style="node")

        # Field separators on bottom border
        for cs, ce, _ in row_fields:
            if cs > 0:
                canvas.put(y_bottom, margin + cs * bits_per_col, bj, merge=False, style="node")

    # Legend for truncated labels
    truncated: list[tuple[str, str, int, int]] = []
    for field in diagram.fields:
        first_row_bits = min(field.bits, row_bits - field.start % row_bits)
        avail = first_row_bits * bits_per_col - 2
        if avail < display_width(field.label) and field.label:
            short = truncate_to_width(field.label, avail)
            truncated.append((short, field.label, field.start, field.end))

    if truncated:
        y_legend = total_h + 1
        legend_lines: list[str] = []
        for short, full, start, end in truncated:
            bits = f"[{start}]" if start == end else f"[{start}-{end}]"
            entry = f"{short} = {full} {bits}"
            if max_width is None:
                legend_lines.append(entry)
            else:
                legend_lines.extend(wrap_display_text(entry, max(1, max_width - margin)))
        needed_h = y_legend + len(legend_lines) + 1
        if needed_h > canvas.height:
            canvas.resize(canvas.width, needed_h)
        for i, line in enumerate(legend_lines):
            canvas.put_text(y_legend + i, margin, line, style="edge_label")

    return canvas


def render(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.body
    packet_extra: dict[str, int] = {}
    if config.padding_y != 2:
        packet_extra["padding_y"] = config.padding_y
    canvas = render_packet(
        parse_packet(text),
        use_ascii=config.use_ascii,
        rounded=config.rounded_edges,
        max_width=config.max_width,
        **packet_extra,
    )
    return RenderResult(canvas)
