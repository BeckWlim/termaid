"""Subgraph layout handling for the layout engine.

Manages gap expansion for subgraph borders and labels,
and computes subgraph bounding boxes after node placement.
"""
from __future__ import annotations

from ..graph.model import Direction, Graph, Subgraph
from ..utils import display_width
from .grid import (
    SG_BORDER_PAD,
    SG_GAP_PER_LEVEL,
    SG_LABEL_HEIGHT,
    GridLayout,
    SubgraphBounds,
)


def expand_gaps_for_subgraphs(
    graph: Graph, layout: GridLayout, direction: Direction,
) -> None:
    """Expand gap cells to accommodate subgraph borders, labels, and nesting."""
    if not graph.subgraphs:
        return

    # Ancestor subgraph chain for each node
    def _get_chain(nid: str) -> frozenset[str]:
        chain: set[str] = set()
        sg = graph.find_subgraph_for_node(nid)
        while sg:
            chain.add(sg.id)
            sg = sg.parent
        return frozenset(chain)

    node_chains = {nid: _get_chain(nid) for nid in graph.node_order}
    extra_title_rows = {
        bounds_id: max(0, len(subgraph.label.split("\n")) - 1)
        for bounds_id in set().union(*node_chains.values())
        if (subgraph := graph.find_subgraph_by_id(bounds_id)) is not None
    }

    is_vertical = direction in (Direction.TB, Direction.TD)

    # Group nodes by flow-axis (layer) and cross-axis grid positions
    flow_groups: dict[int, list[str]] = {}
    cross_groups: dict[int, list[str]] = {}
    for nid, p in layout.placements.items():
        flow_pos = p.grid.row if is_vertical else p.grid.col
        cross_pos = p.grid.col if is_vertical else p.grid.row
        flow_groups.setdefault(flow_pos, []).append(nid)
        cross_groups.setdefault(cross_pos, []).append(nid)

    sorted_flow = sorted(flow_groups.keys())
    sorted_cross = sorted(cross_groups.keys())

    # --- Expand flow-direction gaps (between layers) ---
    for i in range(len(sorted_flow) - 1):
        pos1 = sorted_flow[i]
        pos2 = sorted_flow[i + 1]

        # Count subgraph borders that live in this gap: a subgraph
        # containing nodes on one side but not the other has a border
        # (bottom or top) between the two layers. The symmetric difference
        # of the ancestor sets counts exactly those borders, covering
        # nesting transitions and sibling subgraphs alike.
        sgs1: set[str] = set()
        for nid in flow_groups[pos1]:
            sgs1 |= node_chains[nid]
        sgs2: set[str] = set()
        for nid in flow_groups[pos2]:
            sgs2 |= node_chains[nid]
        depth_change = len(sgs1 ^ sgs2)

        if depth_change > 0:
            extra = depth_change * SG_GAP_PER_LEVEL + sum(
                extra_title_rows[sg_id] for sg_id in sgs1 ^ sgs2
            )
            # Gap cells between the two node rows/columns
            gap_start = pos1 + 2
            gap_end = pos2 - 2
            gap_sizes = layout.row_heights if is_vertical else layout.col_widths
            default_size = 1 if is_vertical else 2
            available = sum(gap_sizes.get(gap, default_size) for gap in range(gap_start, gap_end + 1))
            # Borders need space once per layer transition, not once for
            # every routing lane inserted by crossing minimization.
            if gap_start <= gap_end and available < extra:
                gap_sizes[gap_end] = gap_sizes.get(gap_end, default_size) + extra - available
            if not is_vertical and layout.width_budget is not None and gap_start <= gap_end:
                # A three-cell lane's center coincides with the next frame
                # at node_left - 2. Keep the route two cells off that frame.
                gap_sizes[gap_end] = max(gap_sizes.get(gap_end, 1), 7)

    # --- Expand cross-direction gaps (sibling subgraphs) ---
    for i in range(len(sorted_cross) - 1):
        pos1 = sorted_cross[i]
        pos2 = sorted_cross[i + 1]

        inner1: set[str] = set()
        for nid in cross_groups[pos1]:
            sg = graph.find_subgraph_for_node(nid)
            if sg:
                inner1.add(sg.id)

        inner2: set[str] = set()
        for nid in cross_groups[pos2]:
            sg = graph.find_subgraph_for_node(nid)
            if sg:
                inner2.add(sg.id)

        if (inner1 or inner2) and inner1 != inner2:
            extra = 8  # Space for two subgraph borders + gap
            gap_start = pos1 + 2
            gap_end = pos2 - 2
            for gap in range(gap_start, gap_end + 1):
                if is_vertical:
                    cur = layout.col_widths.get(gap, 2)
                    layout.col_widths[gap] = max(cur, extra)
                else:
                    cur = layout.row_heights.get(gap, 1)
                    layout.row_heights[gap] = max(cur, extra)


def compute_subgraph_bounds(
    graph: Graph,
    layout: GridLayout,
) -> None:
    """Compute bounding boxes for subgraphs."""
    def _compute(sg: Subgraph) -> SubgraphBounds | None:
        # Recursively compute children first
        child_bounds: list[SubgraphBounds] = []
        for child in sg.children:
            cb = _compute(child)
            if cb:
                child_bounds.append(cb)
                layout.subgraph_bounds.append(cb)

        # Gather all node placements in this subgraph
        all_node_ids = set(sg.node_ids)
        for child in sg.children:
            all_node_ids.update(child.node_ids)
            _gather_all_nodes(child, all_node_ids)

        if not all_node_ids and not child_bounds:
            return None

        content_boxes = [
            (p.draw_x, p.draw_y, p.draw_x + p.draw_width, p.draw_y + p.draw_height)
            for nid in all_node_ids if (p := layout.placements.get(nid)) is not None
        ]
        content_boxes.extend((cb.x, cb.y, cb.x + cb.width, cb.y + cb.height) for cb in child_bounds)
        if not content_boxes:
            return None
        min_x = min(box[0] for box in content_boxes)
        min_y = min(box[1] for box in content_boxes)
        max_x = max(box[2] for box in content_boxes)
        max_y = max(box[3] for box in content_boxes)
        content_width = max_x - min_x + SG_BORDER_PAD * 2
        title_lines = sg.label.split("\n")
        title_height = SG_LABEL_HEIGHT + len(title_lines) - 1
        label_width = max(map(display_width, title_lines)) + 4
        final_width = max(content_width, label_width)

        bounds = SubgraphBounds(
            subgraph=sg,
            x=min_x - SG_BORDER_PAD,
            y=min_y - SG_BORDER_PAD - title_height,
            width=final_width,
            height=max_y - min_y + SG_BORDER_PAD * 2 + title_height,
        )
        return bounds

    for sg in graph.subgraphs:
        bounds = _compute(sg)
        if bounds:
            layout.subgraph_bounds.append(bounds)


def _gather_all_nodes(sg: Subgraph, result: set[str]) -> None:
    """Recursively gather all node IDs from a subgraph and its children."""
    result.update(sg.node_ids)
    for child in sg.children:
        _gather_all_nodes(child, result)
