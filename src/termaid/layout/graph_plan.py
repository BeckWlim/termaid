"""Resolve graph boxes, ports, routes and orientation before scene placement."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from ..graph.model import Direction, Graph
from ..routing.router import AttachDir, RoutedEdge, _avoid_group_titles, route_edges
from .grid import GridLayout, compute_layout


@dataclass
class GraphPlan:
    graph: Graph
    layout: GridLayout
    routes: list[RoutedEdge]
    width: int
    height: int


def plan_graph(
    graph: Graph, *, padding_x: int = 4, padding_y: int = 2, gap: int = 4,
    max_label_width: int | None = None, uniform_nodes: bool = False,
    max_width: int | None = None,
) -> GraphPlan:
    layout_graph = deepcopy(graph)
    direction = layout_graph.direction
    layout_graph.direction = direction.normalized()
    layout = compute_layout(layout_graph, padding_x, padding_y, gap,
                            max_label_width=max_label_width, uniform_nodes=uniform_nodes,
                            max_width=max_width)
    routes = route_edges(layout_graph, layout)
    width = max([layout.canvas_width + 4, *(x + 2 for route in routes for x, y in route.draw_path)])
    height = max([layout.canvas_height + 4, *(y + 2 for route in routes for x, y in route.draw_path)])
    if direction in (Direction.BT, Direction.RL):
        vertical = direction == Direction.BT
        for placement in layout.placements.values():
            if vertical:
                placement.draw_y = height - placement.draw_y - placement.draw_height
            else:
                placement.draw_x = width - placement.draw_x - placement.draw_width
        for bounds in layout.subgraph_bounds:
            if vertical:
                bounds.y = height - bounds.y - bounds.height
            else:
                bounds.x = width - bounds.x - bounds.width
        flipped_directions = ({AttachDir.TOP: AttachDir.BOTTOM, AttachDir.BOTTOM: AttachDir.TOP}
                              if vertical else {AttachDir.LEFT: AttachDir.RIGHT, AttachDir.RIGHT: AttachDir.LEFT})
        for route in routes:
            route.draw_path = [(x, height - 1 - y) if vertical else (width - 1 - x, y)
                               for x, y in route.draw_path]
            route.start_dir = flipped_directions.get(route.start_dir, route.start_dir)
            route.end_dir = flipped_directions.get(route.end_dir, route.end_dir)
            route.draw_path = _avoid_group_titles(route.draw_path, layout)
    layout_graph.direction = direction
    return GraphPlan(layout_graph, layout, routes, width, height)
