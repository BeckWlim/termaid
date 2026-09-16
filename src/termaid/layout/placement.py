"""Node placement and sizing for the layout engine.

Handles placing nodes on the grid, computing column widths and row
heights based on label content, and normalizing sizes within layers.
"""
from __future__ import annotations

from ..graph.model import Direction, Graph
from ..graph.shapes import NodeShape
from ..utils import display_width, wrap_display_text
from .grid import (
    STRIDE,
    MAX_LABEL_WIDTH,
    MAX_NORMALIZED_WIDTH,
    MAX_NORMALIZED_HEIGHT,
    GridCoord,
    GridLayout,
    NodePlacement,
)


def _aligned_singleton_positions(graph: Graph, layer_order: list[list[str]]) -> dict[str, int]:
    """Align solitary hubs with nearby peers without widening the node grid.

    Use an existing median column (row for LR), so centering does not add
    a new text-width column between two peers. Compound and explicit grids
    retain their own membership/coordinate rules.
    """
    positions = {node_id: position for nodes in layer_order
                 for position, node_id in enumerate(nodes)}
    if graph.subgraphs or graph.grid_positions:
        return positions
    node_layers = {node_id: layer_index for layer_index, nodes in enumerate(layer_order)
                   for node_id in nodes}
    if any(node_layers.get(edge.target, 0) <= node_layers.get(edge.source, 0)
           for edge in graph.edges):
        # Feedback corridors depend on the first column remaining available.
        return positions
    for layer_index in range(len(layer_order) - 1, -1, -1):
        nodes = layer_order[layer_index]
        if len(nodes) != 1:
            continue
        node_id = nodes[0]
        child_positions = sorted({positions[edge.target] for edge in graph.edges
                                  if edge.source == node_id
                                  and node_layers.get(edge.target) == layer_index + 1})
        parent_positions = sorted({positions[edge.source] for edge in graph.edges
                                   if edge.target == node_id
                                   and node_layers.get(edge.source) == layer_index - 1})
        neighbors = (parent_positions if len(parent_positions) > 1 and len(child_positions) < 2
                     else child_positions or parent_positions)
        if neighbors:
            positions[node_id] = neighbors[(len(neighbors) - 1) // 2]
    # Carry a hub's alignment through its single-node continuation. A leaf
    # must not anchor its collecting parent back at the leftmost column.
    for layer_index, nodes in enumerate(layer_order):
        if len(nodes) != 1 or layer_index == 0 or len(layer_order[layer_index - 1]) != 1:
            continue
        node_id = nodes[0]
        parent_id = layer_order[layer_index - 1][0]
        if (any(edge.source == parent_id and edge.target == node_id for edge in graph.edges)
                and len({edge.target for edge in graph.edges if edge.source == node_id}) <= 1):
            positions[node_id] = positions[parent_id]
    return positions


def place_nodes(
    graph: Graph,
    layout: GridLayout,
    layer_order: list[list[str]],
    direction: Direction,
    gap_expansions: dict[int, int] | None = None,
) -> None:
    """Place nodes on the grid based on layer assignments.

    gap_expansions maps gap index to the number of extra grid cells to
    insert between that gap's adjacent layers, giving the pathfinder more
    room to route crossing edges without overlap.
    """
    expansions = gap_expansions or {}
    perpendicular_positions = _aligned_singleton_positions(graph, layer_order)
    cumulative_extra = 0
    for layer_idx, nodes in enumerate(layer_order):
        if layer_idx > 0:
            cumulative_extra += expansions.get(layer_idx - 1, 0)
        for nid in nodes:
            pos_idx = perpendicular_positions[nid]
            if direction.is_horizontal:
                col = layer_idx * STRIDE + 1 + cumulative_extra
                row = pos_idx * STRIDE + 1
            else:
                col = pos_idx * STRIDE + 1
                row = layer_idx * STRIDE + 1 + cumulative_extra

            gc = GridCoord(col=col, row=row)

            # Collision check: shift perpendicular if occupied
            while not _can_place(layout, gc):
                if direction.is_horizontal:
                    gc = GridCoord(col=gc.col, row=gc.row + STRIDE)
                else:
                    gc = GridCoord(col=gc.col + STRIDE, row=gc.row)

            placement = NodePlacement(node_id=nid, grid=gc)
            layout.placements[nid] = placement

            # Reserve 3x3 block
            for dc in range(-1, 2):
                for dr in range(-1, 2):
                    layout.grid_occupied[(gc.col + dc, gc.row + dr)] = nid


def reserve_return_margin(graph: Graph, layout: GridLayout, max_label_width: int | None = None) -> None:
    """Leave an outer lane for backward edges along the first node column.

    The label gets its own cell before the lane, so even a compact grid can
    route on the left without clipping text or squeezing it into node boxes.
    Horizontal diagrams use the equivalent lane above their first row.
    """
    if graph.subgraphs or not layout.placements:
        return
    horizontal = graph.direction.normalized().is_horizontal
    first_position = min(placement.grid.row if horizontal else placement.grid.col
                         for placement in layout.placements.values())
    return_labels: list[str] = []
    for edge in graph.edges:
        source = layout.placements.get(edge.source)
        target = layout.placements.get(edge.target)
        if source is None or target is None:
            continue
        source_position = source.grid.row if horizontal else source.grid.col
        target_position = target.grid.row if horizontal else target.grid.col
        source_layer = source.grid.col if horizontal else source.grid.row
        target_layer = target.grid.col if horizontal else target.grid.row
        if source_position == target_position == first_position and target_layer < source_layer:
            return_labels.append(edge.label)
    if not return_labels:
        return
    delta_col, delta_row = (0, 2) if horizontal else (2, 0)
    for placement in layout.placements.values():
        placement.grid = GridCoord(placement.grid.col + delta_col, placement.grid.row + delta_row)
    layout.grid_occupied = {(col + delta_col, row + delta_row): owner
                           for (col, row), owner in layout.grid_occupied.items()}
    if horizontal:
        layout.row_heights[0] = 1
        layout.row_heights[1] = 3
    else:
        natural_width = max(1, max(display_width(label) for label in return_labels))
        # In fitted diagrams reserve a modest structural return corridor.
        # Edge sentences wrap later and must not set the node-column offset.
        corridor_width = min(24, 6 * (len(return_labels) + 2))
        layout.col_widths[0] = corridor_width if max_label_width is not None else natural_width
        layout.col_widths[1] = 3


def _can_place(layout: GridLayout, gc: GridCoord) -> bool:
    """Check if a 3x3 block centered at gc is free."""
    for dc in range(-1, 2):
        for dr in range(-1, 2):
            if not layout.is_free(gc.col + dc, gc.row + dr):
                return False
    return True


def normalize_sizes(
    graph: Graph, layout: GridLayout, *, uniform_nodes: bool = False,
) -> None:
    """Normalize node dimensions within the same layer, capped at a maximum.

    Nodes at the same flow level (same layer) are normalized to the same
    perpendicular dimension so side-by-side nodes look consistent.
    """
    direction = graph.direction.normalized()

    if uniform_nodes:
        box_placements = [
            placement for node_id, placement in layout.placements.items()
            if graph.nodes[node_id].shape != NodeShape.JUNCTION
        ]
        if not box_placements:
            return
        common_width = max(layout.col_widths[placement.grid.col] for placement in box_placements)
        common_height = max(layout.row_heights[placement.grid.row] for placement in box_placements)
        for placement in box_placements:
            layout.col_widths[placement.grid.col] = common_width
            layout.row_heights[placement.grid.row] = common_height
        return

    # Group placements by layer
    layer_groups: dict[int, list[NodePlacement]] = {}
    for nid, p in layout.placements.items():
        # Skip junctions from normalization
        node = graph.nodes.get(nid)
        if node and node.shape == NodeShape.JUNCTION:
            continue
        if direction.is_vertical:
            layer_key = p.grid.row  # same row = same layer in TD
        else:
            layer_key = p.grid.col  # same col = same layer in LR
        layer_groups.setdefault(layer_key, []).append(p)

    for placements in layer_groups.values():
        if len(placements) < 2:
            continue  # single node in layer, nothing to normalize

        if direction.is_vertical:
            # TD: normalize column widths within same layer
            cols = {p.grid.col for p in placements}
            max_w = max(layout.col_widths.get(c, 1) for c in cols)
            target = min(max_w, MAX_NORMALIZED_WIDTH)
            for c in cols:
                layout.col_widths[c] = max(layout.col_widths.get(c, 1), target)
        else:
            # LR: normalize row heights within same layer
            rows = {p.grid.row for p in placements}
            max_h = max(layout.row_heights.get(r, 1) for r in rows)
            target = min(max_h, MAX_NORMALIZED_HEIGHT)
            for r in rows:
                layout.row_heights[r] = max(layout.row_heights.get(r, 1), target)


def compute_sizes(
    graph: Graph,
    layout: GridLayout,
    padding_x: int,
    padding_y: int,
    gap: int = 4,
    max_label_width: int | None = None,
) -> None:
    """Compute column widths and row heights based on node content."""
    fitted_horizontal = layout.width_budget is not None and graph.direction.normalized().is_horizontal
    parallel_counts: dict[tuple[str, str], int] = {}
    for edge in graph.edges:
        if not edge.is_self_reference:
            endpoints = (min(edge.source, edge.target), max(edge.source, edge.target))
            parallel_counts[endpoints] = parallel_counts.get(endpoints, 0) + 1
    parallel_capacity: dict[str, int] = {}
    for endpoints, count in parallel_counts.items():
        for node_id in endpoints:
            parallel_capacity[node_id] = max(parallel_capacity.get(node_id, 1), count)

    for nid, placement in layout.placements.items():
        node = graph.nodes[nid]

        # Minimal-size nodes (junctions) -- just 1x1
        if node.shape == NodeShape.JUNCTION:
            col = placement.grid.col
            row = placement.grid.row
            layout.col_widths[col] = max(layout.col_widths.get(col, 1), 1)
            layout.row_heights[row] = max(layout.row_heights.get(row, 1), 1)
            continue

        label = node.label
        lines = label.replace("\\n", "\n").split("\n")

        # Preserve the historical whitespace-only wrapping unless a caller
        # explicitly supplies a width-fitting constraint.
        label_width = max_label_width or MAX_LABEL_WIDTH
        wrapped_lines: list[str] = []
        for line in lines:
            if display_width(line) <= label_width:
                wrapped_lines.append(line)
            else:
                wrapped_lines.extend(wrap_display_text(
                    line,
                    label_width,
                    hard_break=max_label_width is not None and not fitted_horizontal,
                ))

        # Update the node's label with wrapped text
        if len(wrapped_lines) > 1 and wrapped_lines != lines:
            node.label = "\\n".join(wrapped_lines)
            # Styled label segments describe one source line. Retaining them
            # would redraw the unwrapped label over the fitted node.
            node.label_segments = None

        text_width = max(display_width(l) for l in wrapped_lines) if wrapped_lines else 0
        text_height = len(wrapped_lines)

        content_width = text_width + padding_x  # padding on each side
        content_height = text_height + padding_y  # padding top/bottom

        # Ensure minimum sizes
        content_width = max(content_width, 3)
        content_height = max(content_height, 1)

        if fitted_horizontal:
            incoming_sources = {edge.source for edge in graph.edges
                                if edge.target == nid and not edge.is_self_reference}
            if len(incoming_sources) > 1:
                content_height = max(content_height, len(incoming_sources) * 2 - 1)

        # Distinct edges between the same endpoints need distinct ports.
        # Reserve enough border cells even with zero text padding.
        parallel_count = parallel_capacity.get(nid, 1)
        if parallel_count > 1:
            if graph.direction.normalized().is_horizontal:
                content_height = max(content_height, parallel_count * 2 - 1)
            else:
                label_spacing = max((
                    max(map(display_width, edge.label.split("\n"))) + 2
                    for edge in graph.edges if nid in (edge.source, edge.target)
                ), default=4)
                lane_spacing = 4 if max_label_width is not None else max(4, min(16, label_spacing))
                content_width = max(content_width, (parallel_count - 1) * lane_spacing + 1)

        col = placement.grid.col
        row = placement.grid.row

        # Center column gets the content width
        cur = layout.col_widths.get(col, 1)
        layout.col_widths[col] = max(cur, content_width)

        # Center row gets the content height
        cur = layout.row_heights.get(row, 1)
        layout.row_heights[row] = max(cur, content_height)

    # Border cells (around nodes) get width 1
    all_cols: set[int] = set()
    all_rows: set[int] = set()
    for placement in layout.placements.values():
        c, r = placement.grid.col, placement.grid.row
        for dc in range(-1, 2):
            all_cols.add(c + dc)
        for dr in range(-1, 2):
            all_rows.add(r + dr)

    for c in all_cols:
        if c not in layout.col_widths:
            layout.col_widths[c] = 1
    for r in all_rows:
        if r not in layout.row_heights:
            layout.row_heights[r] = 1

    # Gap cells between nodes
    max_col = max(all_cols) if all_cols else 0
    max_row = max(all_rows) if all_rows else 0
    for c in range(max_col + 2):
        if c not in layout.col_widths:
            layout.col_widths[c] = gap  # gap columns
    for r in range(max_row + 2):
        if r not in layout.row_heights:
            layout.row_heights[r] = max(gap - 1, 1)  # gap rows

    # Expand gaps to fit edge labels
    _expand_gaps_for_edge_labels(graph, layout, compact=max_label_width is not None or fitted_horizontal)
    if fitted_horizontal:
        # Coarse routing lanes become distinct character columns. Reserve
        # clearance only across transitions used by multiple connections.
        node_columns = sorted({placement.grid.col for placement in layout.placements.values()})
        for left_col, right_col in zip(node_columns, node_columns[1:]):
            crossing_edges = [edge for edge in graph.edges
                              if edge.source in layout.placements and edge.target in layout.placements
                              and min(layout.placements[edge.source].grid.col, layout.placements[edge.target].grid.col) <= left_col
                              and max(layout.placements[edge.source].grid.col, layout.placements[edge.target].grid.col) >= right_col]
            if len(crossing_edges) > 1:
                for gap_col in range(left_col + 2, right_col - 1):
                    layout.col_widths[gap_col] = max(layout.col_widths.get(gap_col, 1), 3)
    for (source_id, target_id), count in parallel_counts.items():
        if count < 2 or source_id not in layout.placements:
            continue
        pair_placements = [layout.placements[node_id] for node_id in (source_id, target_id)
                           if node_id in layout.placements]
        source = min(pair_placements, key=lambda placement: (
            placement.grid.col if graph.direction.normalized().is_horizontal else placement.grid.row
        ))
        if graph.direction.normalized().is_horizontal:
            gap_col = source.grid.col + 2
            layout.col_widths[gap_col] = max(layout.col_widths.get(gap_col, 1), 5)
        else:
            gap_row = source.grid.row + 2
            layout.row_heights[gap_row] = max(layout.row_heights.get(gap_row, 1), 5)


def _expand_gaps_for_edge_labels(
    graph: Graph, layout: GridLayout, *, compact: bool = False,
) -> None:
    """Expand gap cells between nodes to fit edge labels.

    For horizontal flow (LR): expand gap columns so labels fit on
    horizontal segments.  For vertical flow (TB): expand gap rows so
    labels fit beside vertical segments.
    """
    direction = graph.direction.normalized()
    is_horizontal = direction.is_horizontal

    for edge in graph.edges:
        if not edge.label:
            continue
        label_lines = edge.label.split("\n")
        label_len = max(map(display_width, label_lines))

        src_p = layout.placements.get(edge.source)
        tgt_p = layout.placements.get(edge.target)
        if not src_p or not tgt_p:
            continue

        if is_horizontal:
            # Edges run horizontally -- label needs gap column width
            c1 = min(src_p.grid.col, tgt_p.grid.col)
            c2 = max(src_p.grid.col, tgt_p.grid.col)
            # Gap cells are between the two node 3x3 blocks
            gap_start = c1 + 2
            gap_end = c2 - 2
            if gap_start > gap_end:
                continue
            # Need: gap_width + 1 >= label_len + 2  ->  gap_width >= label_len + 1
            needed = label_len + 1
            if compact and layout.width_budget is not None:
                # A sentence can wrap beside its route. Its longest word
                # sets the readable floor, not the width of the full label.
                word_width = max(map(display_width, edge.label.split()), default=0)
                needed = min(needed, max(8, word_width))
                if len(edge.label.split()) == 1:
                    needed = max(needed, label_len + 3)
            # Distribute across first gap cell (simplest approach)
            cur = layout.col_widths.get(gap_start, 4)
            layout.col_widths[gap_start] = max(cur, needed)
        else:
            # Edges run vertically -- label placed beside the line (x+1)
            # Expand gap row for vertical space, but also ensure the gap
            # column is wide enough for the label text beside the line
            r1 = min(src_p.grid.row, tgt_p.grid.row)
            r2 = max(src_p.grid.row, tgt_p.grid.row)
            gap_start = r1 + 2
            gap_end = r2 - 2
            if gap_start > gap_end:
                continue
            # Need enough vertical space: at least 2 rows for the label
            cur = layout.row_heights.get(gap_start, 3)
            layout.row_heights[gap_start] = max(cur, len(label_lines) + 2, 3)

            # Fitted vertical diagrams place labels in the routing rows.
            # Reserving the entire label in every crossed column gap
            # consumes the width budget before node text can use it.
            if compact:
                continue

            # Also ensure the gap column beside the edge is wide enough
            # for the label text. The edge typically runs in a border col;
            # the label is placed at x+1, which falls in the gap col after.
            # Determine gap column from both source AND target positions.
            src_col = src_p.grid.col
            tgt_col = tgt_p.grid.col
            # The edge runs vertically in a gap column between src and tgt.
            # Expand all gap columns that might hold the label.
            gap_cols: set[int] = set()
            if tgt_col >= src_col:
                gap_cols.add(src_col + 2)  # gap to the right of source
            if tgt_col <= src_col:
                gap_cols.add(src_col - 2)  # gap to the left of source
            # For edges crossing multiple columns, also expand intermediate gaps
            c_min = min(src_col, tgt_col)
            c_max = max(src_col, tgt_col)
            for c in range(c_min + 2, c_max, STRIDE):
                gap_cols.add(c)
            for gap_col in gap_cols:
                if gap_col >= 0 and gap_col in layout.col_widths:
                    cur = layout.col_widths[gap_col]
                    layout.col_widths[gap_col] = max(cur, label_len + 1)

    # For vertical flow: when multiple labeled edges leave the same source,
    # ensure the gap row is tall enough for all labels with spacing.
    if not is_horizontal:
        from collections import Counter
        labeled_per_src: Counter[str] = Counter()
        for edge in graph.edges:
            if edge.label:
                labeled_per_src[edge.source] += 1
        for src_id, count in labeled_per_src.items():
            if count < 2:
                continue
            src_p = layout.placements.get(src_id)
            if not src_p:
                continue
            gap_row = src_p.grid.row + 2
            needed = count * 2 + 1  # 2 rows per label + spacing
            cur = layout.row_heights.get(gap_row, 3)
            layout.row_heights[gap_row] = max(cur, needed)


def allocate_label_slack(graph: Graph, layout: GridLayout) -> bool:
    """Spend remaining width on label corridors after measuring nodes and frames.

    Horizontal approaches favor complete short labels; opposing vertical
    ports favor room for wrapped labels. Both allocations stay within the
    remaining budget instead of stretching every gap.
    """
    if layout.width_budget is None:
        return False
    if not graph.direction.normalized().is_horizontal:
        return _allocate_reciprocal_label_slack(graph, layout)
    available = max(0, layout.width_budget - layout.canvas_width)
    node_columns = sorted({placement.grid.col for placement in layout.placements.values()})
    previous_columns = dict(zip(node_columns[1:], node_columns))
    changed = False
    for edge in sorted(graph.edges, key=lambda item: display_width(item.label)):
        label_width = display_width(edge.label)
        if not 1 <= label_width <= 16 or '\n' in edge.label:
            continue
        source = layout.placements.get(edge.source)
        target = layout.placements.get(edge.target)
        if source is None or target is None or previous_columns.get(target.grid.col) != source.grid.col:
            continue
        outgoing = sum(candidate.source == edge.source for candidate in graph.edges)
        start_col = source.grid.col + (2 if outgoing > 1 else 1)
        approach_start, _ = layout.grid_to_draw_center(start_col, source.grid.row)
        approach_end, _ = layout.grid_to_draw_center(target.grid.col - 1, target.grid.row)
        needed = max(0, label_width + 3 - (approach_end - approach_start))
        if 0 < needed <= available:
            gap_col = target.grid.col - 2
            layout.col_widths[gap_col] = layout.col_widths.get(gap_col, 1) + needed
            available -= needed
            changed = True
    return changed


def _allocate_reciprocal_label_slack(graph: Graph, layout: GridLayout) -> bool:
    """Separate opposing vertical ports when the terminal has spare columns.

    Labels between reciprocal routes need space on both sides of the middle
    port. Keep a margin for outer return labels and spend only the remaining
    budget; an unfitted diagram keeps its ordinary node sizing.
    """
    if layout.width_budget is None or graph.subgraphs or graph.grid_positions:
        return False
    edge_pairs = {(edge.source, edge.target) for edge in graph.edges}
    desired_widths: dict[int, int] = {}
    for edge in graph.edges:
        if not edge.label or (edge.target, edge.source) not in edge_pairs:
            continue
        source = layout.placements.get(edge.source)
        target = layout.placements.get(edge.target)
        if source is None or target is None or source.grid.col != target.grid.col:
            continue
        corridor_width = min(16, display_width(edge.label))
        desired_widths[source.grid.col] = max(desired_widths.get(source.grid.col, 0), 2 * corridor_width + 3)
    outer_label_margin = max((display_width(word) for edge in graph.edges for word in edge.label.split()), default=0) + 2
    available = max(0, layout.width_budget - layout.canvas_width - outer_label_margin)
    changed = False
    for column, desired_width in sorted(desired_widths.items()):
        growth = min(available, max(0, desired_width - layout.col_widths[column]))
        if growth:
            layout.col_widths[column] += growth
            available -= growth
            changed = True
    return changed
