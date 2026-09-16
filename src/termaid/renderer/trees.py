"""Terminal renderers for mindmaps, treemaps."""
from __future__ import annotations

from dataclasses import dataclass

from ..layout.scene import LayoutScene
from ..model.trees import Mindmap, MindmapNode, Treemap, TreemapNode
from ..utils import display_width, truncate_to_width
from .charset import ASCII, UNICODE, CharSet


# Mindmaps
# ------------------------------------------------------------------------
#
# Renders a tree radiating from a central root node. Children branch to
# the right by default. When the root has many children (> threshold),
# the first few overflow to the left so the diagram stays balanced.
#
# Each subtree is rendered recursively as a block of text lines with a
# designated connection row where the parent attaches.

# When root has more children than this, spill some to the left
_OVERFLOW_THRESHOLD = 6


@dataclass(frozen=True)
class _Chars:
    """Branch drawing characters, varying by ascii/rounded mode."""
    h: str    # horizontal line
    v: str    # vertical continuation
    tl: str   # top-left corner (first child)
    bl: str   # bottom-left corner (last child)
    tee: str  # tee junction (middle child)
    tj: str   # junction when connect row falls between children
    # mirrored (for left-branching)
    tr: str   # top-right
    br: str   # bottom-right
    tee_l: str  # left-facing tee
    tj_l: str   # left-facing junction


def _make_chars(use_ascii: bool, rounded: bool) -> _Chars:
    if use_ascii:
        return _Chars(
            h="-", v="|", tl="+", bl="+", tee="+", tj="+",
            tr="+", br="+", tee_l="+", tj_l="+",
        )
    if rounded:
        return _Chars(
            h="─", v="│", tl="╭", bl="╰", tee="├", tj="┤",
            tr="╮", br="╯", tee_l="┤", tj_l="├",
        )
    return _Chars(
        h="─", v="│", tl="┌", bl="└", tee="├", tj="┤",
        tr="┐", br="┘", tee_l="┤", tj_l="├",
    )


def render_mindmap(
    diagram: Mindmap,
    *,
    use_ascii: bool = False,
    rounded: bool = True,
) -> LayoutScene:
    """Render a Mindmap model to a LayoutScene."""
    if diagram.root is None:
        return LayoutScene(1, 1)

    ch = _make_chars(use_ascii, rounded)
    root = diagram.root

    if not root.children:
        lines = [root.label]
    else:
        left_children, right_children = _split_children(root.children)
        if not left_children:
            right_block, _ = _render_subtree_right(
                MindmapNode(label=root.label, children=right_children), ch)
            lines = right_block
        else:
            lines = _render_both_sides(root.label, left_children, right_children, ch)

    width = max((display_width(line) for line in lines), default=1)
    height = len(lines)
    canvas = LayoutScene(width + 1, height)
    for r, line in enumerate(lines):
        canvas.put_text(r, 0, line, style="node")
    return canvas


def _split_children(
    children: list[MindmapNode],
) -> tuple[list[MindmapNode], list[MindmapNode]]:
    """Split children into left-overflow and right groups."""
    if len(children) <= _OVERFLOW_THRESHOLD:
        return [], children
    n_left = len(children) // 3
    n_left = max(1, min(n_left, len(children) - 1))
    return children[:n_left], children[n_left:]


# ---------------------------------------------------------------------------
# Right-branching subtree
# ---------------------------------------------------------------------------

def _render_subtree_right(node: MindmapNode, ch: _Chars) -> tuple[list[str], int]:
    """Render a node with children branching to the right.

    Returns (lines, connect_row).
    """
    if not node.children:
        return [node.label], 0

    child_block, child_conn = _stack_right(node.children, ch)

    connector = node.label + " " + ch.h + ch.h
    pad = " " * len(connector)
    result: list[str] = []
    for i, line in enumerate(child_block):
        if i == child_conn:
            result.append(connector + line)
        else:
            result.append(pad + line)
    return result, child_conn


def _stack_right(children: list[MindmapNode], ch: _Chars) -> tuple[list[str], int]:
    """Stack child subtrees vertically with branch chars on the left."""
    if len(children) == 1:
        sub, sc = _render_subtree_right(children[0], ch)
        result = []
        for i, line in enumerate(sub):
            if i == sc:
                result.append(ch.h + ch.h + " " + line)
            else:
                result.append("   " + line)
        return result, sc

    blocks: list[tuple[list[str], int]] = []
    for child in children:
        blocks.append(_render_subtree_right(child, ch))

    result: list[str] = []
    conn_rows: list[int] = []

    for idx, (block, bc) in enumerate(blocks):
        is_first = idx == 0
        is_last = idx == len(blocks) - 1
        base = len(result)

        for li, line in enumerate(block):
            if li == bc:
                conn_rows.append(base + li)
                if is_first:
                    result.append(ch.tl + ch.h + " " + line)
                elif is_last:
                    result.append(ch.bl + ch.h + " " + line)
                else:
                    result.append(ch.tee + ch.h + " " + line)
            else:
                result.append(ch.v + "  " + line)

    # Replace │ with space for rows outside the connection range
    first_conn = conn_rows[0]
    last_conn = conn_rows[-1]
    for i in range(0, first_conn):
        if result[i][0] == ch.v:
            result[i] = " " + result[i][1:]
    for i in range(last_conn + 1, len(result)):
        if result[i][0] == ch.v:
            result[i] = " " + result[i][1:]

    mid = (conn_rows[0] + conn_rows[-1]) // 2
    if mid not in conn_rows:
        if result[mid][0] == ch.v:
            result[mid] = ch.tj + result[mid][1:]

    return result, mid


# ---------------------------------------------------------------------------
# Left-branching subtree (mirrored)
# ---------------------------------------------------------------------------

def _render_subtree_left(node: MindmapNode, ch: _Chars) -> tuple[list[str], int]:
    """Render a node with children branching to the left (mirrored)."""
    if not node.children:
        return [node.label], 0

    child_block, child_conn = _stack_left(node.children, ch)
    child_width = max(display_width(line) for line in child_block)
    child_block = [line.rjust(child_width) for line in child_block]

    connector = ch.h + ch.h + " " + node.label
    pad = " " * len(connector)
    result: list[str] = []
    for i, line in enumerate(child_block):
        if i == child_conn:
            result.append(line + connector)
        else:
            result.append(line + pad)
    return result, child_conn


def _stack_left(children: list[MindmapNode], ch: _Chars) -> tuple[list[str], int]:
    """Stack child subtrees with branch chars on the right (mirrored)."""
    if len(children) == 1:
        sub, sc = _render_subtree_left(children[0], ch)
        w = max(display_width(line) for line in sub)
        result = []
        for i, line in enumerate(sub):
            if i == sc:
                result.append(line.rjust(w) + " " + ch.h + ch.h)
            else:
                result.append(line.rjust(w) + "   ")
        return result, sc

    blocks: list[tuple[list[str], int]] = []
    for child in children:
        blocks.append(_render_subtree_left(child, ch))

    max_w = max(max(display_width(line) for line in block) for block, _ in blocks)
    result: list[str] = []
    conn_rows: list[int] = []

    for idx, (block, bc) in enumerate(blocks):
        is_first = idx == 0
        is_last = idx == len(blocks) - 1
        base = len(result)

        for li, line in enumerate(block):
            padded = line.rjust(max_w)
            if li == bc:
                conn_rows.append(base + li)
                if is_first:
                    result.append(padded + " " + ch.h + ch.tr)
                elif is_last:
                    result.append(padded + " " + ch.h + ch.br)
                else:
                    result.append(padded + " " + ch.h + ch.tee_l)
            else:
                if is_last:
                    result.append(padded + "   ")
                else:
                    result.append(padded + "  " + ch.v)

    first_conn = conn_rows[0]
    last_conn = conn_rows[-1]
    for i in range(0, first_conn):
        if result[i].endswith(ch.v):
            result[i] = result[i][:-1] + " "
    for i in range(last_conn + 1, len(result)):
        if result[i].endswith(ch.v):
            result[i] = result[i][:-1] + " "

    mid = (conn_rows[0] + conn_rows[-1]) // 2
    if mid not in conn_rows:
        if result[mid].endswith(ch.v):
            result[mid] = result[mid][:-1] + ch.tj_l

    return result, mid


# ---------------------------------------------------------------------------
# Root with both sides
# ---------------------------------------------------------------------------

def _render_both_sides(
    root_label: str,
    left_children: list[MindmapNode],
    right_children: list[MindmapNode],
    ch: _Chars,
) -> list[str]:
    """Render root in the center with left and right subtrees."""
    right_block, _ = _stack_right(right_children, ch)
    left_block, _ = _stack_left(left_children, ch)

    left_width = max((display_width(line) for line in left_block), default=0)
    rh = len(right_block)
    lh = len(left_block)
    total = max(rh, lh)

    r_off = (total - rh) // 2
    l_off = (total - lh) // 2
    root_row = total // 2

    root_part = ch.h + ch.h + " " + root_label + " " + ch.h + ch.h
    pad = " " * len(root_part)

    result: list[str] = []
    for row in range(total):
        li = row - l_off
        left = left_block[li].ljust(left_width) if 0 <= li < lh else " " * left_width
        ri = row - r_off
        right = right_block[ri] if 0 <= ri < rh else ""
        center = root_part if row == root_row else pad
        result.append(left + center + right)

    return result


# Treemaps
# ------------------------------------------------------------------------
#
# Renders a Treemap as nested rectangles on a LayoutScene using a
# squarified layout algorithm for readable proportions.
# Section nodes use dashed borders; leaf nodes use solid borders.

_MIN_BOX_W = 4
_MIN_BOX_H = 3
_GAP = 1  # gap between sibling boxes
_LABEL_PAD = 0  # minimum padding around label text inside a box


def render_treemap(
    diagram: Treemap,
    *,
    use_ascii: bool = False,
) -> LayoutScene:
    """Render a Treemap model to a LayoutScene."""
    cs = ASCII if use_ascii else UNICODE

    if not diagram.roots:
        return LayoutScene(1, 1)

    total = diagram.total_value
    if total <= 0:
        return LayoutScene(1, 1)

    canvas_h = _compute_height(diagram.roots)
    min_w = _compute_min_width(diagram.roots)

    # Scale width: proportional for small diagrams, tight for large ones
    # Cap at 120 unless the minimum requires more
    canvas_w = max(min_w, min(120, max(60, int(min_w * 1.6))))

    canvas = LayoutScene(canvas_w, canvas_h)
    _layout_nodes(canvas, cs, diagram.roots, 0, 0, canvas_w, canvas_h, depth=0)

    return canvas


def _compute_height(nodes: list[TreemapNode]) -> int:
    """Compute the minimum height needed to render a list of nodes."""
    max_h = 0
    for node in nodes:
        if node.children:
            child_h = _compute_height(node.children)
            h = child_h + 4  # top border + label + child area + bottom border
        else:
            h = 4  # top border + label + value + bottom border
        max_h = max(max_h, h)
    return max_h


def _compute_min_width(nodes: list[TreemapNode]) -> int:
    """Compute the minimum width needed to render sibling nodes side by side."""
    total = 0
    for node in nodes:
        if node.children:
            child_w = _compute_min_width(node.children)
            # borders (2) + child content
            node_w = child_w + 2
        else:
            # borders (2) + label padding
            label_w = display_width(node.label) + _LABEL_PAD
            node_w = max(_MIN_BOX_W, label_w + 2)
        total += node_w

    # Add gaps between siblings
    total += _GAP * max(0, len(nodes) - 1)
    return total


def _layout_nodes(
    canvas: LayoutScene,
    cs: CharSet,
    nodes: list[TreemapNode],
    x: int, y: int, w: int, h: int,
    depth: int,
) -> None:
    """Recursively lay out nodes into the given rectangle."""
    if not nodes or w < _MIN_BOX_W or h < _MIN_BOX_H:
        return

    total = sum(n.total_value for n in nodes)
    if total <= 0:
        return

    # Sort by value descending for better layout
    sorted_nodes = sorted(nodes, key=lambda n: n.total_value, reverse=True)

    _slice_layout(canvas, cs, sorted_nodes, x, y, w, h, total, depth)


def _slice_layout(
    canvas: LayoutScene,
    cs: CharSet,
    nodes: list[TreemapNode],
    x: int, y: int, w: int, h: int,
    total: float,
    depth: int,
) -> None:
    """Lay out nodes side by side horizontally with gaps."""
    n_gaps = len(nodes) - 1
    total_gap_w = _GAP * n_gaps
    usable_w = w - total_gap_w

    if usable_w < _MIN_BOX_W * len(nodes):
        # Not enough space for gaps, drop them
        total_gap_w = 0
        usable_w = w
        n_gaps = 0

    # Compute minimum widths for each node
    min_widths = []
    for node in nodes:
        if node.children:
            mw = _compute_min_width(node.children) + 2
        else:
            mw = _MIN_BOX_W
        min_widths.append(mw)

    # Distribute width proportionally, respecting minimums
    raw_sizes = []
    for node in nodes:
        raw_sizes.append(node.total_value / total * usable_w)

    # Adjust: ensure minimums are met, redistribute excess
    sizes = list(raw_sizes)
    for _ in range(3):  # iterate to stabilize
        deficit = 0
        surplus_total = 0
        for i in range(len(sizes)):
            if sizes[i] < min_widths[i]:
                deficit += min_widths[i] - sizes[i]
                sizes[i] = min_widths[i]
            else:
                surplus_total += sizes[i] - min_widths[i]
        if deficit > 0 and surplus_total > 0:
            scale = max(0, 1 - deficit / surplus_total)
            for i in range(len(sizes)):
                if sizes[i] > min_widths[i]:
                    excess = sizes[i] - min_widths[i]
                    sizes[i] = min_widths[i] + excess * scale

    # Round to integers
    int_sizes = [max(min_widths[i], round(sizes[i])) for i in range(len(sizes))]

    # Fix total to match usable_w
    current_total = sum(int_sizes)
    if current_total != usable_w:
        diff = usable_w - current_total
        # Adjust the largest node
        largest_idx = max(range(len(int_sizes)), key=lambda i: int_sizes[i])
        int_sizes[largest_idx] = max(min_widths[largest_idx], int_sizes[largest_idx] + diff)

    # Draw each node
    pos_x = x
    for i, node in enumerate(nodes):
        bw = int_sizes[i]
        # Clamp to available space
        bw = min(bw, x + w - pos_x)
        if bw < _MIN_BOX_W:
            break

        _draw_node(canvas, cs, node, pos_x, y, bw, h, depth)
        pos_x += bw + (_GAP if i < n_gaps else 0)


def _draw_node(
    canvas: LayoutScene,
    cs: CharSet,
    node: TreemapNode,
    x: int, y: int, w: int, h: int,
    depth: int,
) -> None:
    """Draw a single node box and recurse into children."""
    if w < _MIN_BOX_W or h < _MIN_BOX_H:
        return

    is_section = bool(node.children)

    # Section nodes (with children) get dashed borders
    if is_section:
        hz = cs.line_dotted_h
        vt = cs.line_dotted_v
    else:
        hz = cs.horizontal
        vt = cs.vertical

    tl = cs.top_left
    tr = cs.top_right
    bl = cs.bottom_left
    br = cs.bottom_right

    style = "subgraph" if is_section else "node"

    # Top border
    canvas.put(y, x, tl, merge=False, style=style)
    for c in range(x + 1, x + w - 1):
        canvas.put(y, c, hz, merge=False, style=style)
    canvas.put(y, x + w - 1, tr, merge=False, style=style)

    # Bottom border
    canvas.put(y + h - 1, x, bl, merge=False, style=style)
    for c in range(x + 1, x + w - 1):
        canvas.put(y + h - 1, c, hz, merge=False, style=style)
    canvas.put(y + h - 1, x + w - 1, br, merge=False, style=style)

    # Side borders
    for r in range(y + 1, y + h - 1):
        canvas.put(r, x, vt, merge=False, style=style)
        canvas.put(r, x + w - 1, vt, merge=False, style=style)

    # Label — centered on the first inner row
    label = node.label
    inner_w = w - 2
    label = truncate_to_width(label, inner_w, ellipsis="…")
    label_col = x + 1 + max(0, (inner_w - display_width(label)) // 2)
    canvas.put_text(y + 1, label_col, label, style="label")

    # Value (for leaves only)
    if not node.children and node.value > 0 and h >= 4:
        val_str = f"{node.value:g}"
        if len(val_str) > inner_w:
            val_str = val_str[:inner_w]
        val_col = x + 1 + max(0, (inner_w - len(val_str)) // 2)
        canvas.put_text(y + 2, val_col, val_str, style="edge_label")

    # Recurse into children
    if node.children:
        inner_x = x + 1
        inner_y = y + 2  # skip border + label
        inner_w_val = w - 2
        inner_h = h - 3  # top border + label + bottom border

        if inner_w_val >= _MIN_BOX_W and inner_h >= _MIN_BOX_H:
            _layout_nodes(canvas, cs, node.children, inner_x, inner_y, inner_w_val, inner_h, depth + 1)
