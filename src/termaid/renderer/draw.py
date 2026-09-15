"""Draw orchestrator: combines layout, routing, and rendering into final output.

Drawing order (back to front):
1. Subgraphs (background)
2. Nodes (boxes)
3. Edge lines
4. Edge corners
5. Arrow heads
6. T-junctions (where edges leave nodes)
7. Edge labels
8. Subgraph labels
"""
from __future__ import annotations

from dataclasses import replace

from ..graph.model import ArrowType, Direction, EdgeStyle, Graph, GraphNote
from ..graph.shapes import NodeShape
from ..layout.grid import GridLayout, NodePlacement, compute_layout
from ..routing.router import AttachDir, RoutedEdge, route_edges
from .canvas import Canvas, DOWN, LEFT, RIGHT, UP
from ..utils import display_width, wrap_display_text
from .charset import ASCII, UNICODE, CharSet
from .shapes import SHAPE_RENDERERS, draw_rectangle


def render_graph(
    graph: Graph,
    use_ascii: bool = False,
    padding_x: int = 4,
    padding_y: int = 2,
    rounded_edges: bool = True,
    gap: int = 4,
    inline_edge_labels: bool = False,
    max_label_width: int | None = None,
    uniform_nodes: bool = False,
    arrow_position: str = "end",
    max_width: int | None = None,
) -> str:
    """Render a graph to a string.

    Args:
        graph: The parsed graph model
        use_ascii: Use ASCII characters instead of Unicode
        padding_x: Horizontal padding inside node boxes
        padding_y: Vertical padding inside node boxes
        rounded_edges: Use rounded corners on edge turns (╭╮╰╯ vs ┌┐└┘)
        gap: Space between nodes (default: 4)
        inline_edge_labels: Attach labels directly to their edge segments

    Returns:
        The rendered diagram as a string
    """
    canvas = render_graph_canvas(
        graph, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap,
        inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width,
        uniform_nodes=uniform_nodes,
        max_width=max_width,
        arrow_position=arrow_position,
    )
    if canvas is None:
        return ""
    return canvas.to_string()


def render_graph_canvas(
    graph: Graph,
    use_ascii: bool = False,
    padding_x: int = 4,
    padding_y: int = 2,
    rounded_edges: bool = True,
    gap: int = 4,
    inline_edge_labels: bool = False,
    max_label_width: int | None = None,
    uniform_nodes: bool = False,
    arrow_position: str = "end",
    max_width: int | None = None,
) -> Canvas | None:
    """Render a graph and return the Canvas (with style info).

    Returns None for empty graphs.
    """
    if max_width is not None and max_width < 1:
        raise ValueError("max_width must be positive")
    if arrow_position not in ("end", "middle"):
        raise ValueError("arrow_position must be end or middle")
    if not graph.node_order:
        return None

    cs = ASCII if use_ascii else UNICODE

    # Need to handle BT/RL by rendering as TB/LR then flipping
    direction = graph.direction
    needs_v_flip = direction == Direction.BT
    needs_h_flip = direction == Direction.RL

    # Normalize direction for layout
    if needs_v_flip:
        graph.direction = Direction.TB
    elif needs_h_flip:
        graph.direction = Direction.LR

    # Layout
    layout = compute_layout(
        graph, padding_x, padding_y, gap,
        max_label_width=max_label_width,
        uniform_nodes=uniform_nodes,
    )

    # Route edges
    routed = route_edges(graph, layout)

    # Create canvas (add some margin)
    # Account for edge paths that may extend beyond node boundaries
    # (e.g. back edges routed to the right/below of all nodes)
    width = layout.canvas_width + 4
    height = layout.canvas_height + 4
    for re in routed:
        for x, y in re.draw_path:
            width = max(width, x + 2)
            height = max(height, y + 2)
    canvas = Canvas(width, height)

    # 1. Draw subgraph borders (background layer)
    _draw_subgraph_borders(canvas, layout, cs)

    # 2. Draw nodes
    _draw_nodes(canvas, graph, layout, cs)

    # 3. Draw edges
    label_references = _draw_edges(
        canvas, graph, layout, routed, cs,
        rounded_edges=rounded_edges,
        inline_edge_labels=inline_edge_labels,
        arrow_position=arrow_position,
        max_width=max_width,
    )

    # 4. Draw subgraph labels (on top of everything else)
    _draw_subgraph_labels(canvas, layout, cs)

    # 5. Draw notes (on top of everything else)
    _draw_notes(canvas, graph, layout, cs)

    # Flip if needed
    if needs_v_flip:
        canvas.flip_vertical()
        graph.direction = Direction.BT
    elif needs_h_flip:
        canvas.flip_horizontal()
        graph.direction = Direction.RL

    # References are added after direction flips, always below the diagram.
    # Full label text stays available without changing node layout or routes.
    if label_references:
        drawing_lines = canvas.to_string().splitlines()
        drawing_width = max((display_width(line) for line in drawing_lines), default=0)
        footer_width = max(3, max_width if max_width is not None else drawing_width)
        footer_row = len(drawing_lines) + 1
        for reference, label_text in label_references:
            prefix = reference + " "
            # Keep the reference intact even in a very narrow output budget.
            if display_width(prefix) >= footer_width:
                footer_lines = [reference, *wrap_display_text(label_text, footer_width)]
            else:
                wrapped_lines = wrap_display_text(label_text, footer_width - display_width(prefix))
                footer_lines = [prefix + wrapped_lines[0]]
                footer_lines.extend(" " * display_width(prefix) + line for line in wrapped_lines[1:])
            for footer_line in footer_lines:
                canvas.resize(max(canvas.width, display_width(footer_line)), max(canvas.height, footer_row + 1))
                canvas.put_text(footer_row, 0, footer_line, style="edge_label", overwrite_spaces=True)
                footer_row += 1

    return canvas


def _draw_subgraph_borders(canvas: Canvas, layout: GridLayout, cs: CharSet) -> None:
    """Draw subgraph border boxes (background layer)."""
    for sb in layout.subgraph_bounds:
        x, y = sb.x, sb.y
        w, h = sb.width, sb.height

        if w <= 0 or h <= 0:
            continue

        # Ensure bounds are valid
        x = max(0, x)
        y = max(0, y)

        # Top border
        canvas.put(y, x, cs.sg_top_left, style="subgraph")
        for c in range(x + 1, x + w - 1):
            canvas.put(y, c, cs.sg_horizontal, style="subgraph")
        canvas.put(y, x + w - 1, cs.sg_top_right, style="subgraph")

        # Bottom border
        canvas.put(y + h - 1, x, cs.sg_bottom_left, style="subgraph")
        for c in range(x + 1, x + w - 1):
            canvas.put(y + h - 1, c, cs.sg_horizontal, style="subgraph")
        canvas.put(y + h - 1, x + w - 1, cs.sg_bottom_right, style="subgraph")

        # Side borders
        for r in range(y + 1, y + h - 1):
            canvas.put(r, x, cs.sg_vertical, style="subgraph")
            canvas.put(r, x + w - 1, cs.sg_vertical, style="subgraph")


def _draw_subgraph_labels(canvas: Canvas, layout: GridLayout, cs: CharSet) -> None:
    """Draw subgraph labels (on top of everything else)."""
    for sb in layout.subgraph_bounds:
        x, y = sb.x, sb.y
        w, h = sb.width, sb.height

        if w <= 0 or h <= 0:
            continue

        x = max(0, x)
        y = max(0, y)

        label = sb.subgraph.label
        if label:
            canvas.put_text(y + 1, x + 2, label, style="subgraph_label")


def _draw_nodes(canvas: Canvas, graph: Graph, layout: GridLayout, cs: CharSet) -> None:
    """Draw all node boxes."""
    for nid in graph.node_order:
        if nid not in layout.placements:
            continue
        node = graph.nodes[nid]
        p = layout.placements[nid]

        # Resolve style key: inline style > :::className > classDef default > "node"
        if nid in graph.node_styles:
            style = f"nodestyle:{nid}"
        elif node.style_class and node.style_class in graph.class_defs:
            style = f"class:{node.style_class}"
        elif "default" in graph.class_defs:
            style = "class:default"
        else:
            style = "node"

        renderer = SHAPE_RENDERERS.get(node.shape, SHAPE_RENDERERS[NodeShape.RECTANGLE])
        renderer(canvas, p.draw_x, p.draw_y, p.draw_width, p.draw_height, node.label, cs, style=style)

        # Protect node cells so edge lines don't overwrite borders
        for r in range(p.draw_y, p.draw_y + p.draw_height):
            for c in range(p.draw_x, p.draw_x + p.draw_width):
                canvas.protect(r, c)

        # Overwrite label with styled text if markdown segments exist
        if node.label_segments:
            label_row = p.draw_y + p.draw_height // 2
            total_len = sum(display_width(seg.text) for seg in node.label_segments)
            label_col = p.draw_x + (p.draw_width - total_len) // 2
            styled_segs: list[tuple[str, str]] = []
            for seg in node.label_segments:
                if seg.bold:
                    seg_style = "bold_label"
                elif seg.italic:
                    seg_style = "italic_label"
                else:
                    seg_style = "label"
                styled_segs.append((seg.text, seg_style))
            canvas.put_styled_text(label_row, label_col, styled_segs)


def _draw_edges(
    canvas: Canvas, graph: Graph, layout: GridLayout, routed: list[RoutedEdge], cs: CharSet,
    rounded_edges: bool = True,
    inline_edge_labels: bool = False,
    arrow_position: str = "end",
    max_width: int | None = None,
) -> list[tuple[str, str]]:
    """Draw all edge lines, corners, arrows, and labels.

    Labels are drawn in a second pass so they aren't overwritten by
    later edges' line segments.
    """
    # Pass 1a: lines and corners
    for re in routed:
        if len(re.draw_path) < 2:
            continue

        edge = re.edge

        # Resolve per-edge style key
        if re.index in graph.link_styles:
            edge_style_key = f"linkstyle:{re.index}"
        elif -1 in graph.link_styles:
            edge_style_key = f"linkstyle:{re.index}"
        else:
            edge_style_key = "edge"

        # Select line characters based on edge style
        h_char, v_char = _edge_line_chars(edge.style, cs)
        n_segs = len(re.draw_path) - 1

        # Draw line segments, clipping endpoints at node borders and turn
        # points so that corners/junctions own their cells and get correct
        # direction bits when the directional canvas merges overlapping edges.
        for i in range(n_segs):
            x1, y1 = re.draw_path[i]
            x2, y2 = re.draw_path[i + 1]

            dx = 0 if x2 == x1 else (1 if x2 > x1 else -1)
            dy = 0 if y2 == y1 else (1 if y2 > y1 else -1)

            # Clip start: 1 cell away from node border or turn point
            x1, y1 = x1 + dx, y1 + dy
            # Extra clip for start arrow on first segment
            if i == 0 and edge.has_arrow_start and (arrow_position == "end" or edge.arrow_type_start != ArrowType.ARROW):
                x1, y1 = x1 + dx, y1 + dy

            # Clip end: 1 cell away from target border or turn point
            x2, y2 = x2 - dx, y2 - dy

            # Use original direction (dx/dy) for classification, not clipped
            # coordinates, since clipping can reduce a segment to a single
            # point where both y1==y2 and x1==x2 are true.
            if dy == 0:
                # Horizontal: skip if clipping reversed the segment
                if (dx > 0 and x1 > x2) or (dx < 0 and x1 < x2):
                    continue
                canvas.draw_horizontal(y1, x1, x2, h_char, style=edge_style_key)
            elif dx == 0:
                # Vertical: skip if clipping reversed the segment
                if (dy > 0 and y1 > y2) or (dy < 0 and y1 < y2):
                    continue
                canvas.draw_vertical(x1, y1, y2, v_char, style=edge_style_key)
            else:
                # Diagonal (shouldn't happen with A*, but handle gracefully)
                _draw_diagonal(canvas, x1, y1, x2, y2, h_char)

        # Draw corners at path turns
        for i in range(1, len(re.draw_path) - 1):
            x_prev, y_prev = re.draw_path[i - 1]
            x_curr, y_curr = re.draw_path[i]
            x_next, y_next = re.draw_path[i + 1]

            corner = _get_corner_char(x_prev, y_prev, x_curr, y_curr, x_next, y_next, cs, rounded=rounded_edges)
            if corner:
                canvas.put(y_curr, x_curr, corner, style=edge_style_key)

    _draw_crossings(canvas, routed, cs)

    # Pass 1b: arrows and T-junctions (drawn after all lines so they
    # aren't overwritten by later edges' line segments)
    for re in routed:
        if len(re.draw_path) < 2:
            continue

        edge = re.edge

        if re.index in graph.link_styles:
            edge_style_key = f"linkstyle:{re.index}"
        elif -1 in graph.link_styles:
            edge_style_key = f"linkstyle:{re.index}"
        else:
            edge_style_key = "edge"

        arrow_style_key = edge_style_key if edge_style_key != "edge" else "arrow"

        # Draw arrow heads
        if edge.has_arrow_end and (arrow_position == "end" or edge.arrow_type_end != ArrowType.ARROW):
            _draw_arrow_head(canvas, re.draw_path[-2], re.draw_path[-1], cs, style=arrow_style_key, arrow_type=edge.arrow_type_end)
        if edge.has_arrow_start and (arrow_position == "end" or edge.arrow_type_start != ArrowType.ARROW):
            _draw_arrow_head(canvas, re.draw_path[1], re.draw_path[0], cs, style=arrow_style_key, arrow_type=edge.arrow_type_start)

        # Draw T-junctions where edges leave node borders
        if len(re.draw_path) >= 2:
            if not edge.has_arrow_start or (arrow_position == "middle" and edge.arrow_type_start == ArrowType.ARROW):
                _draw_box_start(canvas, re.draw_path[0], re.draw_path[1], re, layout, cs)
            if not edge.has_arrow_end or (arrow_position == "middle" and edge.arrow_type_end == ArrowType.ARROW):
                _draw_box_start(canvas, re.draw_path[-1], re.draw_path[-2], re, layout, cs)

    if arrow_position == "middle":
        _draw_middle_arrows(canvas, graph, routed, cs)

    label_area_width = canvas.width
    # Real labels get first choice of space. Failure markers must not crowd
    # out another edge's complete label.
    placed_labels: list[tuple[int, int, int]] = []
    failed_routes: list[RoutedEdge] = []
    for route in routed:
        if route.label and not _draw_edge_label(
            canvas, route, placed_labels,
            inline=inline_edge_labels, use_ascii=cs is ASCII,
            max_width=max_width, preferred_width=label_area_width,
        ):
            failed_routes.append(route)
    label_references: list[tuple[str, str]] = []
    for reference_number, route in enumerate(sorted(failed_routes, key=lambda item: item.index), start=1):
        reference = f"[{reference_number}]"
        marker_route = replace(route, label=reference)
        marker_placed = _draw_edge_label(
            canvas, marker_route, placed_labels, use_ascii=cs is ASCII, max_width=max_width,
        )
        needs_edge_identity = not marker_placed
        if not marker_placed:
            # A short segment may not span the reference. A nearby blank
            # position can still identify it without touching the connector.
            reference_positions = (
                (y + row_offset, x + col_offset)
                for radius in range(1, 4)
                for x, y in reversed(route.draw_path)
                for row_offset in range(-radius, radius + 1)
                for col_offset in range(-radius, radius + 1)
                if max(abs(row_offset), abs(col_offset)) == radius
            )
            marker_placed = any(
                _try_place_label(canvas, row, col, reference, placed_labels, max_width=max_width)
                for row, col in reference_positions
            )
        # If even the reference cannot fit safely, identify its edge in the
        # list instead of overwriting a connector or dropping the label.
        label_text = f"{route.edge.source} to {route.edge.target}: {route.label}" if needs_edge_identity else route.label
        label_references.append((reference, label_text))
    return label_references


def _draw_middle_arrows(
    canvas: Canvas, graph: Graph, routed: list[RoutedEdge], cs: CharSet,
) -> None:
    """Place directional heads on straight cells, preferring unshared paths.

    Allocate scarce short routes first. Junctions, crossings, node borders,
    and existing endpoint markers are avoided. Short routes fall back to
    endpoint heads when their only cell is a shared bend. Circle/cross endpoints keep
    their endpoint meaning and are drawn by the caller.
    """
    # (x, y, dx, dy, distance along route)
    cells_by_route: list[list[tuple[int, int, int, int, int]]] = []
    owners: dict[tuple[int, int], set[int]] = {}
    lengths: list[int] = []
    for route_index, route in enumerate(routed):
        route_cells: list[tuple[int, int, int, int, int]] = []
        distance = 0
        for first, last in zip(route.draw_path, route.draw_path[1:]):
            dx = (last[0] > first[0]) - (last[0] < first[0])
            dy = (last[1] > first[1]) - (last[1] < first[1])
            segment_length = abs(last[0] - first[0]) + abs(last[1] - first[1])
            for step in range(1, segment_length):
                x, y = first[0] + step * dx, first[1] + step * dy
                owners.setdefault((x, y), set()).add(route_index)
                if not canvas.is_protected(y, x) and canvas.get(y, x) in "─┄━│┆┃-|":
                    route_cells.append((x, y, dx, dy, distance + step))
            distance += segment_length
        cells_by_route.append(route_cells)
        lengths.append(distance)

    # Each request is (route index, reverse direction). A bidirectional edge
    # gets two distinct heads in the appropriate halves of the line.
    requests: list[tuple[int, bool]] = []
    for route_index, route in enumerate(routed):
        if route.edge.style == EdgeStyle.INVISIBLE:
            continue
        if route.edge.has_arrow_start and route.edge.arrow_type_start == ArrowType.ARROW:
            requests.append((route_index, True))
        if route.edge.has_arrow_end and route.edge.arrow_type_end == ArrowType.ARROW:
            requests.append((route_index, False))
    requests.sort(key=lambda request: len(cells_by_route[request[0]]))
    occupied: set[tuple[int, int]] = set()
    for route_index, reverse in requests:
        route = routed[route_index]
        bidirectional = route.edge.has_arrow_start and route.edge.has_arrow_end
        fraction = (1 / 3 if reverse else 2 / 3) if bidirectional else 1 / 2
        target_distance = lengths[route_index] * fraction
        available_cells = [cell for cell in cells_by_route[route_index] if (cell[0], cell[1]) not in occupied]
        candidates = sorted(available_cells, key=lambda cell: (
            len(owners[(cell[0], cell[1])]),
            abs(cell[4] - target_distance),
        ))
        if not candidates and len(route.draw_path) >= 2:
            # A one-cell gap can itself be a shared bend. Preserve the normal
            # endpoint head there when no straight middle cell exists.
            adjacent, endpoint = (route.draw_path[1], route.draw_path[0]) if reverse else (route.draw_path[-2], route.draw_path[-1])
            endpoint_dx = (endpoint[0] > adjacent[0]) - (endpoint[0] < adjacent[0])
            endpoint_dy = (endpoint[1] > adjacent[1]) - (endpoint[1] < adjacent[1])
            head_x, head_y = endpoint[0] - endpoint_dx, endpoint[1] - endpoint_dy
            if not canvas.is_protected(head_y, head_x) and canvas.get(head_y, head_x) not in "►◄▲▼><^vo×╳x":
                candidates.append((head_x, head_y, -endpoint_dx if reverse else endpoint_dx,
                                   -endpoint_dy if reverse else endpoint_dy, 0))
        for x, y, dx, dy, distance in candidates:
            if (x, y) in occupied:
                continue
            arrow_dx, arrow_dy = (-dx, -dy) if reverse else (dx, dy)
            style = f"linkstyle:{route.index}" if route.index in graph.link_styles or -1 in graph.link_styles else "arrow"
            _draw_arrow_head(canvas, (x, y), (x + arrow_dx, y + arrow_dy), cs, style=style)
            occupied.add((x, y))
            break


def _draw_crossings(canvas: Canvas, routed: list[RoutedEdge], cs: CharSet) -> None:
    """Distinguish unrelated crossing lines from connected branch junctions.

    Track graph ownership in drawing cells: a shared source or target may
    form a junction, but orthogonal routes between unrelated endpoints do
    not connect. Mark crossings before arrowheads and labels are drawn.
    """
    directions_by_cell: dict[tuple[int, int], dict[int, int]] = {}
    edges_by_index = {index: route.edge for index, route in enumerate(routed)}
    for edge_index, route in enumerate(routed):
        if route.edge.style == EdgeStyle.INVISIBLE:
            continue
        for first, last in zip(route.draw_path, route.draw_path[1:]):
            if first[0] != last[0] and first[1] != last[1]:
                continue
            delta_col = (last[0] > first[0]) - (last[0] < first[0])
            delta_row = (last[1] > first[1]) - (last[1] < first[1])
            distance = abs(last[0] - first[0]) + abs(last[1] - first[1])
            outgoing = RIGHT if delta_col > 0 else LEFT if delta_col < 0 else DOWN if delta_row > 0 else UP
            incoming = LEFT if delta_col > 0 else RIGHT if delta_col < 0 else UP if delta_row > 0 else DOWN
            for step in range(distance + 1):
                cell = (first[0] + step * delta_col, first[1] + step * delta_row)
                if cell in (route.draw_path[0], route.draw_path[-1]):
                    continue
                mask = (incoming if step > 0 else 0) | (outgoing if step < distance else 0)
                owners = directions_by_cell.setdefault(cell, {})
                owners[edge_index] = owners.get(edge_index, 0) | mask
    for (col, row), owners in directions_by_cell.items():
        if len(owners) < 2 or canvas.is_protected(row, col):
            continue
        owner_masks = list(owners.items())
        crossing = False
        for position, (first_index, first_mask) in enumerate(owner_masks):
            first_edge = edges_by_index[first_index]
            for second_index, second_mask in owner_masks[position + 1:]:
                second_edge = edges_by_index[second_index]
                if ((first_mask | second_mask) == UP | DOWN | LEFT | RIGHT
                        and first_edge.source != second_edge.source
                        and first_edge.target != second_edge.target):
                    crossing = True
                    break
            if crossing:
                break
        if crossing:
            canvas.put(row, col, cs.unconnected_crossing, merge=False, style="edge")


def _edge_line_chars(style: EdgeStyle, cs: CharSet) -> tuple[str, str]:
    """Get horizontal and vertical line characters for an edge style."""
    if style == EdgeStyle.DOTTED:
        return cs.line_dotted_h, cs.line_dotted_v
    elif style == EdgeStyle.THICK:
        return cs.line_thick_h, cs.line_thick_v
    elif style == EdgeStyle.INVISIBLE:
        return " ", " "
    return cs.line_horizontal, cs.line_vertical


def _draw_diagonal(
    canvas: Canvas, x1: int, y1: int, x2: int, y2: int, ch: str,
) -> None:
    """Draw a rough diagonal line (fallback)."""
    steps = max(abs(x2 - x1), abs(y2 - y1))
    if steps == 0:
        return
    for step in range(steps + 1):
        x = x1 + (x2 - x1) * step // steps
        y = y1 + (y2 - y1) * step // steps
        canvas.put(y, x, ch)


def _get_corner_char(
    x_prev: int, y_prev: int,
    x_curr: int, y_curr: int,
    x_next: int, y_next: int,
    cs: CharSet,
    rounded: bool = True,
) -> str | None:
    """Determine the corner character at a path turn."""
    # Direction coming in
    dx_in = x_curr - x_prev
    dy_in = y_curr - y_prev

    # Direction going out
    dx_out = x_next - x_curr
    dy_out = y_next - y_curr

    # Normalize to -1/0/1
    dx_in = 0 if dx_in == 0 else (1 if dx_in > 0 else -1)
    dy_in = 0 if dy_in == 0 else (1 if dy_in > 0 else -1)
    dx_out = 0 if dx_out == 0 else (1 if dx_out > 0 else -1)
    dy_out = 0 if dy_out == 0 else (1 if dy_out > 0 else -1)

    if rounded:
        corner_map = {
            (1, 0, 0, 1): cs.round_top_right,       # right then down → ╮
            (1, 0, 0, -1): cs.round_bottom_right,    # right then up → ╯
            (-1, 0, 0, 1): cs.round_top_left,        # left then down → ╭
            (-1, 0, 0, -1): cs.round_bottom_left,    # left then up → ╰
            (0, 1, 1, 0): cs.round_bottom_left,      # down then right → ╰
            (0, 1, -1, 0): cs.round_bottom_right,    # down then left → ╯
            (0, -1, 1, 0): cs.round_top_left,        # up then right → ╭
            (0, -1, -1, 0): cs.round_top_right,      # up then left → ╮
        }
    else:
        corner_map = {
            (1, 0, 0, 1): cs.corner_top_right,      # right then down → ┐
            (1, 0, 0, -1): cs.corner_bottom_right,   # right then up → ┘
            (-1, 0, 0, 1): cs.corner_top_left,       # left then down → ┌
            (-1, 0, 0, -1): cs.corner_bottom_left,   # left then up → └
            (0, 1, 1, 0): cs.corner_bottom_left,     # down then right → └
            (0, 1, -1, 0): cs.corner_bottom_right,   # down then left → ┘
            (0, -1, 1, 0): cs.corner_top_left,       # up then right → ┌
            (0, -1, -1, 0): cs.corner_top_right,     # up then left → ┐
        }

    return corner_map.get((dx_in, dy_in, dx_out, dy_out))


def _draw_arrow_head(
    canvas: Canvas,
    from_point: tuple[int, int],
    to_point: tuple[int, int],
    cs: CharSet,
    style: str = "",
    arrow_type: ArrowType = ArrowType.ARROW,
) -> None:
    """Draw an arrow head one cell before to_point (in the gap, not on the border).

    This prevents the arrow from overwriting shape markers (◆, ◯) on node borders.
    """
    fx, fy = from_point
    tx, ty = to_point

    dx = tx - fx
    dy = ty - fy

    # Normalize direction to -1/0/1
    ndx = 0 if dx == 0 else (1 if dx > 0 else -1)
    ndy = 0 if dy == 0 else (1 if dy > 0 else -1)

    # Place arrow one cell back from the border
    ax = tx - ndx
    ay = ty - ndy

    if arrow_type == ArrowType.CIRCLE:
        canvas.put(ay, ax, cs.circle_endpoint, style=style)
    elif arrow_type == ArrowType.CROSS:
        canvas.put(ay, ax, cs.cross_endpoint, style=style)
    elif ndx > 0:
        canvas.put(ay, ax, cs.arrow_right, style=style)
    elif ndx < 0:
        canvas.put(ay, ax, cs.arrow_left, style=style)
    elif ndy > 0:
        canvas.put(ay, ax, cs.arrow_down, style=style)
    elif ndy < 0:
        canvas.put(ay, ax, cs.arrow_up, style=style)


def _draw_box_start(
    canvas: Canvas,
    edge_point: tuple[int, int],
    next_point: tuple[int, int],
    re: RoutedEdge,
    layout: GridLayout,
    cs: CharSet,
) -> None:
    """Draw a T-junction where an edge leaves a node border."""
    ex, ey = edge_point
    nx, ny = next_point

    dx = nx - ex
    dy = ny - ey

    if dx > 0:
        tee = cs.tee_right if cs.horizontal == "─" else "+"
    elif dx < 0:
        tee = cs.tee_left if cs.horizontal == "─" else "+"
    elif dy > 0:
        tee = cs.tee_down if cs.horizontal == "─" else "+"
    elif dy < 0:
        tee = cs.tee_up if cs.horizontal == "─" else "+"
    else:
        return

    canvas.put(ey, ex, tee)


def _label_overlaps(
    row: int, col_start: int, col_end: int,
    placed: list[tuple[int, int, int]],
) -> bool:
    """Keep labels separated while allowing disjoint branches to align."""
    for placed_row, placed_start, placed_end in placed:
        if placed_row == row and col_start < placed_end + 2 and col_end + 2 > placed_start:
            return True
    return False


def _place_label(
    canvas: Canvas,
    row: int, col: int, label: str,
    placed: list[tuple[int, int, int]],
    *, inline: bool = False,
    max_width: int | None = None,
) -> bool:
    """Place a complete label when every character can be written."""
    col_end = col + display_width(label)
    if col < 0 or row < 0 or (max_width is not None and col_end > max_width):
        return False
    for target_col in range(col, col_end):
        if canvas.is_protected(row, target_col):
            return False
        existing_character = canvas.get(row, target_col)
        if existing_character == " ":
            continue
        if not inline or existing_character not in "─┄━│┆┃-|":
            return False
    # Ensure canvas is large enough for the label
    needed_w = col_end + 1
    needed_h = row + 1
    if needed_w > canvas.width or needed_h > canvas.height:
        canvas.resize(max(canvas.width, needed_w), max(canvas.height, needed_h))
    canvas.put_text(row, col, label, style="edge_label", overwrite_spaces=True)
    placed.append((row, col, col_end))
    return True


def _try_place_label(
    canvas: Canvas,
    row: int, col: int, label: str,
    placed: list[tuple[int, int, int]],
    *, inline: bool = False,
    max_width: int | None = None,
) -> bool:
    """Try to place a non-overlapping label at (row, col)."""
    col_end = col + display_width(label)
    if _label_overlaps(row, col, col_end, placed):
        return False
    return _place_label(canvas, row, col, label, placed, inline=inline, max_width=max_width)


def _find_last_turn(path: list[tuple[int, int]]) -> int:
    """Find the index of the last turn in a path. Returns -1 if no turns."""
    for i in range(len(path) - 2, 0, -1):
        x_prev, y_prev = path[i - 1]
        x_curr, y_curr = path[i]
        x_next, y_next = path[i + 1]
        # Direction changes at this point
        dx_in = x_curr - x_prev
        dy_in = y_curr - y_prev
        dx_out = x_next - x_curr
        dy_out = y_next - y_curr
        if (dx_in, dy_in) != (0, 0) and (dx_out, dy_out) != (0, 0):
            # Normalize
            dx_in = 0 if dx_in == 0 else (1 if dx_in > 0 else -1)
            dy_in = 0 if dy_in == 0 else (1 if dy_in > 0 else -1)
            dx_out = 0 if dx_out == 0 else (1 if dx_out > 0 else -1)
            dy_out = 0 if dy_out == 0 else (1 if dy_out > 0 else -1)
            if (dx_in, dy_in) != (dx_out, dy_out):
                return i
    return -1


def _try_place_on_segment(
    canvas: Canvas, x1: int, y1: int, x2: int, y2: int,
    label: str, placed_labels: list[tuple[int, int, int]],
    prev_point: tuple[int, int] | None = None,
    prefer_left: bool = False,
    bias_target: bool = False,
    inline: bool = False,
    use_ascii: bool = False,
    leader_char: str = "─",
    max_width: int | None = None,
) -> bool:
    """Try to place a label on a specific segment. Returns True if placed.

    prev_point: the path point before (x1, y1), used to determine which side
    of a vertical segment to prefer after a horizontal turn.
    prefer_left: explicitly prefer the left side for vertical segments.
    bias_target: place closer to the target end (2/3) instead of midpoint.
    """
    label_len = display_width(label)

    if x1 == x2 and abs(y2 - y1) >= 2:
        # Vertical segment — place beside the line.
        # If preceded by a horizontal turn, prefer the inner side
        # (left when the branch extends right, right when it extends left).
        lo, hi = min(y1, y2), max(y1, y2)
        if bias_target:
            # Place 2/3 toward the target end (y2)
            if y2 > y1:
                mid_y = y1 + (y2 - y1) * 2 // 3
            else:
                mid_y = y1 + (y2 - y1) * 2 // 3
        else:
            mid_y = (lo + hi) // 2

        place_left = prefer_left
        if not prefer_left and prev_point is not None:
            px, py = prev_point
            if py == y1 and px != x1:
                # Horizontal predecessor — turn came from left (px < x1) or right (px > x1)
                # Place label on the side the turn came from (inner side of the branch)
                place_left = px < x1

        if inline:
            right_label = f"+-{label}" if use_ascii else f"├{leader_char}{label}"
            left_label = f"{label}-+" if use_ascii else f"{label}{leader_char}┤"
            sides = [
                (mid_y, x1, right_label),
                (mid_y, x1 - display_width(left_label) + 1, left_label),
            ]
            if place_left:
                sides.reverse()

            for row, col, anchored_label in sides:
                if _try_place_label(
                    canvas, row, col, anchored_label, placed_labels, inline=True,
                    max_width=max_width,
                ):
                    return True
            for offset in range(1, 4):
                for row, col, anchored_label in sides:
                    if _try_place_label(
                        canvas, row - offset, col, anchored_label, placed_labels, inline=True,
                        max_width=max_width,
                    ):
                        return True
                    if _try_place_label(
                        canvas, row + offset, col, anchored_label, placed_labels, inline=True,
                        max_width=max_width,
                    ):
                        return True
            return False

        if place_left:
            sides = [
                (mid_y, x1 - label_len),       # left
                (mid_y, x1 + 1),                # right
            ]
        else:
            sides = [
                (mid_y, x1 + 1),                # right
                (mid_y, x1 - label_len),        # left
            ]

        for row, col in sides:
            if _try_place_label(canvas, row, col, label, placed_labels, max_width=max_width):
                return True
        for offset in range(1, 4):
            for row, col in sides:
                if _try_place_label(canvas, row - offset, col, label, placed_labels, max_width=max_width):
                    return True
                if _try_place_label(canvas, row + offset, col, label, placed_labels, max_width=max_width):
                    return True
        return False

    if y1 == y2:
        # Horizontal segment — center inline labels on the edge, otherwise
        # place labels above or below it.
        seg_len = abs(x2 - x1)
        if seg_len >= label_len + 2:
            mid = (min(x1, x2) + max(x1, x2)) // 2
            start = mid - label_len // 2
            if inline:
                return _try_place_label(
                    canvas, y1, start, label, placed_labels, inline=True,
                    max_width=max_width,
                )
            if _try_place_label(canvas, y1 - 1, start, label, placed_labels, max_width=max_width):
                return True
            if _try_place_label(canvas, y1 + 1, start, label, placed_labels, max_width=max_width):
                return True
            return False

    return False


def _draw_edge_label(
    canvas: Canvas, re: RoutedEdge,
    placed_labels: list[tuple[int, int, int]],
    *, inline: bool = False, use_ascii: bool = False,
    max_width: int | None = None, preferred_width: int | None = None,
) -> bool:
    """Use an explicit width budget for readable labels before wrapping."""
    if max_width is not None:
        return _draw_single_line_edge_label(
            canvas, re, placed_labels, inline=inline, use_ascii=use_ascii, max_width=max_width,
        ) or _draw_wrapped_edge_label(canvas, re, placed_labels, max_width=max_width)

    # Without a width budget, prefer existing space before unbounded growth.
    diagram_width = canvas.width if preferred_width is None else preferred_width
    if _draw_single_line_edge_label(
        canvas, re, placed_labels, inline=inline, use_ascii=use_ascii, max_width=diagram_width,
    ) or _draw_wrapped_edge_label(canvas, re, placed_labels, max_width=diagram_width):
        return True
    return _draw_single_line_edge_label(
        canvas, re, placed_labels, inline=inline, use_ascii=use_ascii, max_width=max_width,
    ) or _draw_wrapped_edge_label(canvas, re, placed_labels, max_width=max_width)


def _draw_single_line_edge_label(
    canvas: Canvas, re: RoutedEdge,
    placed_labels: list[tuple[int, int, int]],
    *,
    inline: bool = False,
    use_ascii: bool = False,
    max_width: int | None = None,
) -> bool:
    """Draw an edge label on the best segment of the path.

    Prefers segments after the last turn (the unique part of the edge path)
    so labels appear on the branch, not on a shared trunk.
    Uses collision detection to avoid overlapping previously placed labels.
    """
    label = re.label
    if not label:
        return False

    path = re.draw_path
    leader_char = _edge_line_chars(
        re.edge.style, ASCII if use_ascii else UNICODE,
    )[0]

    # Build segment list ordered by preference: post-turn segments first,
    # then remaining segments in reverse order (end segments are more unique)
    n_segs = len(path) - 1
    if n_segs <= 0:
        return False

    last_turn = _find_last_turn(path)
    preferred: list[int] = []
    remaining: list[int] = []

    if last_turn >= 0:
        # Segments after the last turn (unique to this edge)
        for i in range(last_turn, n_segs):
            preferred.append(i)
        # Then remaining segments in reverse
        for i in range(last_turn - 1, -1, -1):
            remaining.append(i)
    else:
        # No turns — straight path, use all segments
        for i in range(n_segs):
            remaining.append(i)

    # For straight paths (no turns), prefer left side and bias toward target
    # so the label doesn't land on the same row as sibling edges' turns
    is_straight = last_turn < 0

    # Try preferred segments first, then remaining
    for i in preferred + remaining:
        x1, y1 = path[i]
        x2, y2 = path[i + 1]
        prev = path[i - 1] if i > 0 else None
        if _try_place_on_segment(
            canvas, x1, y1, x2, y2, label, placed_labels,
            prev_point=prev,
            prefer_left=is_straight,
            bias_target=is_straight,
            inline=inline,
            use_ascii=use_ascii,
            leader_char=leader_char,
            max_width=max_width,
        ):
            return True

    if inline:
        return _draw_single_line_edge_label(
            canvas, re, placed_labels,
            inline=False,
            use_ascii=use_ascii,
            max_width=max_width,
        )

    # Tight routes may cross a subgraph border or have no blank midpoint.
    # Search nearby blank positions along the actual segments; never force
    # text over an arrow, connector, node interior, or another label.
    label_width = display_width(label)
    for first, last in zip(path, path[1:]):
        if first[1] == last[1]:
            minimum_col = min(first[0], last[0]) + 1
            maximum_col = max(first[0], last[0]) - label_width
            middle_col = (minimum_col + maximum_col) // 2
            candidate_cols = sorted(range(minimum_col, maximum_col + 1),
                                    key=lambda col: abs(col - middle_col))
            for offset in (-1, 1, -2, 2, -3, 3):
                for col in candidate_cols:
                    if _try_place_label(canvas, first[1] + offset, col, label, placed_labels, max_width=max_width):
                        return True
        else:
            minimum_row = min(first[1], last[1]) + 1
            maximum_row = max(first[1], last[1]) - 1
            middle_row = (minimum_row + maximum_row) // 2
            candidate_rows = sorted(range(minimum_row, maximum_row + 1),
                                    key=lambda row: abs(row - middle_row))
            for row in candidate_rows:
                for col in (first[0] + 1, first[0] - label_width):
                    if _try_place_label(canvas, row, col, label, placed_labels, max_width=max_width):
                        return True

    return False


def _draw_wrapped_edge_label(
    canvas: Canvas, route: RoutedEdge,
    placed_labels: list[tuple[int, int, int]],
    *, max_width: int | None = None,
) -> bool:
    """Fit complete words into a clear rectangle beside an edge segment.

    Check the whole rectangle before writing: text must never erase a node,
    line, arrowhead, or a previous label. Prefer fewer lines and keep the
    rectangle within the segment's span so its owning edge stays clear.
    """
    width_limit = max_width if max_width is not None else canvas.width
    words = route.label.split()
    if len(words) < 2:
        return False
    minimum_width = max(map(display_width, words))
    maximum_width = min(width_limit, display_width(route.label) - 1)
    if minimum_width > maximum_width:
        return False
    # Bounded work even for very long labels; small corridors are exhaustive.
    width_step = max(1, (maximum_width - minimum_width + 31) // 32)
    wrap_widths = sorted({minimum_width, *range(maximum_width, minimum_width - 1, -width_step)}, reverse=True)
    wrapping_options: list[list[str]] = []
    seen_wrappings: set[tuple[str, ...]] = set()
    for wrap_width in wrap_widths:
        wrapped_lines = wrap_display_text(route.label, wrap_width, hard_break=False)
        wrapping_key = tuple(wrapped_lines)
        if len(wrapped_lines) < 2 or wrapping_key in seen_wrappings:
            continue
        seen_wrappings.add(wrapping_key)
        wrapping_options.append(wrapped_lines)
    # Prefer few lines, then balanced lengths over a short orphan ending.
    wrapping_options.sort(key=lambda lines: (
        len(lines), max(map(display_width, lines)) - min(map(display_width, lines)),
    ))
    # Return labels prefer the outer side across all wrapping choices.
    # This uses reserved margins before crowding the space between nodes.
    sides = ("left", "right") if route.start_dir == route.end_dir == AttachDir.LEFT else (
        ("right", "left") if route.start_dir == route.end_dir == AttachDir.RIGHT else ("either",)
    )
    for side in sides:
        for label_lines in wrapping_options:
            text_width = max(map(display_width, label_lines))
            text_height = len(label_lines)
            for first, last in reversed(list(zip(route.draw_path, route.draw_path[1:]))):
                positions: list[tuple[int, int]] = []
                if first[0] == last[0]:
                    top = min(first[1], last[1]) + 1
                    bottom = max(first[1], last[1]) - text_height
                    rows = sorted(range(top, bottom + 1), key=lambda row: abs(row - (top + bottom) / 2))
                    for row in rows:
                        if side != "right":
                            positions.append((row, first[0] - text_width))
                        if side != "left":
                            positions.append((row, first[0] + 1))
                elif abs(last[0] - first[0]) >= text_width + 2:
                    col = (first[0] + last[0] - text_width) // 2
                    positions.extend(((first[1] - text_height, col), (first[1] + 1, col)))
                for row, col in positions:
                    if row < 0 or col < 0 or col + text_width > width_limit or row + text_height > canvas.height:
                        continue
                    if any(_label_overlaps(row + offset, col, col + text_width, placed_labels)
                           or any(canvas.is_protected(row + offset, cell_col)
                                  or canvas.get(row + offset, cell_col) != " "
                                  for cell_col in range(col, col + text_width))
                           for offset in range(text_height)):
                        continue
                    for offset, label_line in enumerate(label_lines):
                        _place_label(canvas, row + offset, col, label_line, placed_labels, max_width=width_limit)
                    return True
    return False


def _draw_notes(canvas: Canvas, graph: Graph, layout: GridLayout, cs: CharSet) -> None:
    """Draw note boxes next to their target nodes."""
    for note in graph.notes:
        if note.target not in layout.placements:
            continue
        p = layout.placements[note.target]

        lines = note.text.split("\n")
        note_width = max(display_width(line) for line in lines) + 4
        note_height = len(lines) + 2

        if note.position == "rightof":
            note_x = p.draw_x + p.draw_width + 2
        else:  # leftof
            note_x = p.draw_x - note_width - 2
            note_x = max(0, note_x)

        note_y = p.draw_y + (p.draw_height - note_height) // 2

        # Extend canvas if needed
        needed_w = note_x + note_width + 2
        needed_h = note_y + note_height + 2
        if needed_w > canvas.width or needed_h > canvas.height:
            canvas.resize(max(canvas.width, needed_w), max(canvas.height, needed_h))

        draw_rectangle(canvas, note_x, note_y, note_width, note_height, note.text, cs, style="node")
