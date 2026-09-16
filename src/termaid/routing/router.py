"""Edge routing orchestrator.

Determines start/end attachment points on nodes, runs A* pathfinding,
and handles direction selection (preferred vs alternative paths).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator
from enum import Enum, auto

from ..graph.model import ArrowType, Direction, Edge, EdgeStyle, Graph
from ..graph.shapes import NodeShape
from ..layout.grid import GridLayout, NodePlacement, SubgraphBounds
from ..utils import display_width
from .pathfinder import find_path, simplify_path


class AttachDir(Enum):
    TOP = auto()
    BOTTOM = auto()
    LEFT = auto()
    RIGHT = auto()


@dataclass
class RoutedEdge:
    """An edge with its computed path in grid coordinates."""
    edge: Edge
    # Path as grid coordinates (simplified to corners)
    grid_path: list[tuple[int, int]] = field(default_factory=list)
    # Path as drawing coordinates
    draw_path: list[tuple[int, int]] = field(default_factory=list)
    start_dir: AttachDir = AttachDir.RIGHT
    end_dir: AttachDir = AttachDir.LEFT
    label: str = ""
    index: int = 0
    # Grid cells occupied by this edge's path
    occupied_cells: set[tuple[int, int]] = field(default_factory=set)
    # Exclusive branch sections available for unambiguous labels.
    label_paths: list[list[tuple[int, int]]] | None = None


class RoutingError(RuntimeError):
    """A connection cannot be represented by a valid orthogonal route."""


def path_cells(path: list[tuple[int, int]]) -> Iterator[tuple[int, int]]:
    """Expand an orthogonal polyline without repeating its corners."""
    if not path:
        return
    yield path[0]
    for first, last in zip(path, path[1:]):
        if first[0] != last[0] and first[1] != last[1]:
            raise RoutingError(f"Non-orthogonal route segment: {first} -> {last}")
        dx = (last[0] > first[0]) - (last[0] < first[0])
        dy = (last[1] > first[1]) - (last[1] < first[1])
        distance = abs(last[0] - first[0]) + abs(last[1] - first[1])
        for step in range(1, distance + 1):
            yield first[0] + step * dx, first[1] + step * dy


def route_edges(graph: Graph, layout: GridLayout) -> list[RoutedEdge]:
    """Route all edges in the graph."""
    direction = graph.direction.normalized()
    routed: list[RoutedEdge] = []
    sibling_routes = _route_sibling_branches(graph, layout)

    # Build subgraph bounds lookup
    sg_bounds: dict[str, SubgraphBounds] = {}
    for sb in layout.subgraph_bounds:
        sg_bounds[sb.subgraph.id] = sb

    # Grid regions of each subgraph box: edges that neither start nor end
    # in a subgraph should avoid routing through its box.
    sg_regions = _compute_sg_regions(layout, sg_bounds)

    def backward_edge(indexed_edge: tuple[int, Edge]) -> bool:
        candidate = indexed_edge[1]
        source = layout.placements.get(candidate.source)
        target = layout.placements.get(candidate.target)
        if source is None or target is None:
            return False
        return (target.grid.col < source.grid.col if direction.is_horizontal
                else target.grid.row < source.grid.row)

    # Route forward branches first, even when a return appears earlier in
    # the source. A return then sees the branches it would otherwise cross.
    for i, edge in sorted(enumerate(graph.edges), key=backward_edge):
        src, tgt = _resolve_endpoints(edge, layout, sg_bounds)

        if src is None or tgt is None:
            continue

        if edge.is_self_reference:
            re = (_route_group_loop(edge, src, graph, layout) if edge.source_is_subgraph
                  else _route_self_edge(edge, src, layout, direction))
            re.index = i
            routed.append(re)
            continue

        forbidden = _foreign_sg_cells(edge, graph, sg_regions)
        re = sibling_routes.get(i)
        if re is None:
            flows: dict[tuple[int, int], set[tuple[int, int, str, str, EdgeStyle]]] = {}
            known_routes = list(routed)
            known_indices = {previous.index for previous in routed}
            known_routes.extend(candidate for index, candidate in sibling_routes.items()
                                if index not in known_indices)
            reserved_approaches: set[tuple[int, int]] = set()
            for previous in known_routes:
                if previous.edge.style == EdgeStyle.INVISIBLE:
                    continue
                previous_cells = list(path_cells(previous.grid_path))
                if (layout.width_budget is not None and direction.is_horizontal
                        and previous.label and previous.edge.source == edge.source
                        and previous.edge.target != edge.target):
                    reserved_approaches.update(previous_cells[-3:-1])
                for first, last in zip(previous_cells, previous_cells[1:]):
                    delta = (last[0] - first[0], last[1] - first[1])
                    for cell in (first, last):
                        flows.setdefault(cell, set()).add((*delta, previous.edge.source, previous.edge.target, previous.edge.style))
                        if previous.edge.has_arrow_start:
                            flows[cell].add((-delta[0], -delta[1], previous.edge.source, previous.edge.target, previous.edge.style))
            re = _route_edge(edge, src, tgt, layout, direction, forbidden, flows, reserved_approaches)
        re.index = i

        # Snap subgraph-endpoint edges onto the subgraph border so they
        # attach to the box, not to the inner node used for routing.
        if edge.source_is_subgraph and edge.source in sg_bounds:
            _clip_endpoint_to_box(re.draw_path, sg_bounds[edge.source], from_start=True)
        if edge.target_is_subgraph and edge.target in sg_bounds:
            _clip_endpoint_to_box(re.draw_path, sg_bounds[edge.target], from_start=False)

        routed.append(re)

    routed.sort(key=lambda route: route.index)

    # Identical declarations remain separate model edges, but can reuse
    # exactly the same geometry and endpoint marker.
    canonical_routes: list[RoutedEdge] = []
    duplicate_routes: list[tuple[RoutedEdge, RoutedEdge]] = []
    for route in routed:
        route_style = graph.link_styles.get(route.index, graph.link_styles.get(-1, {}))
        representative = next((candidate for candidate in canonical_routes
                               if candidate.edge == route.edge
                               and graph.link_styles.get(candidate.index, graph.link_styles.get(-1, {})) == route_style), None)
        if representative is None:
            canonical_routes.append(route)
        else:
            duplicate_routes.append((route, representative))

    # Keep compatible merged arrivals on one port. Spread only arrivals
    # whose direction or appearance requires separate markers.
    for route in canonical_routes:
        route.draw_path = _avoid_group_titles(route.draw_path, layout)
    _spread_shared_endpoints(canonical_routes, layout, sg_bounds, graph)
    _separate_parallel_edges(canonical_routes, graph, layout)
    _straighten_doglegs(canonical_routes, graph, layout)
    _refine_terminal_routes(canonical_routes, graph, layout, set(sibling_routes))
    _separate_label_approaches(canonical_routes, graph, layout)
    for duplicate, representative in duplicate_routes:
        duplicate.draw_path = list(representative.draw_path)
        duplicate.grid_path = list(representative.grid_path)
        duplicate.occupied_cells = set(representative.occupied_cells)
        duplicate.start_dir, duplicate.end_dir = representative.start_dir, representative.end_dir

    return routed


def _separate_label_approaches(routes: list[RoutedEdge], graph: Graph, layout: GridLayout) -> None:
    """Move a nearby turn when it consumes another label's entire approach.

    Two clear cells before an arrow give short branches a usable label anchor.
    This is a preference: keep the original route if separation would touch
    another node or connector, or introduce an extra bend or tiny dogleg.
    """
    if graph.subgraphs:
        return

    def deficit(paths: list[list[tuple[int, int]]]) -> int:
        cells_by_route = [list(path_cells(path)) for path in paths]
        owners: dict[tuple[int, int], int] = {}
        for route, route_cells in zip(routes, cells_by_route):
            if route.edge.style == EdgeStyle.INVISIBLE:
                continue
            for cell in set(route_cells):
                owners[cell] = owners.get(cell, 0) + 1
        missing = 0
        for route, route_cells in zip(routes, cells_by_route):
            if not route.label or route.edge.style == EdgeStyle.INVISIBLE:
                continue
            clear = 0
            for cell in reversed(route_cells[:-1]):
                if owners[cell] != 1:
                    break
                clear += 1
                if clear == 2:
                    break
            missing += 2 - clear
        return missing

    original_deficit = deficit([route.draw_path for route in routes])
    for route_index, route in enumerate(routes):
        if route.edge.style == EdgeStyle.INVISIBLE:
            continue
        paths = [candidate.draw_path for candidate in routes]
        if not original_deficit:
            return
        others = {cell for other in routes if other is not route and other.edge.style != EdgeStyle.INVISIBLE
                  for cell in path_cells(other.draw_path)}
        original_contacts = set(path_cells(route.draw_path)) & others
        original_path = route.draw_path
        for segment_index in range(1, len(original_path) - 2):
            first, last = original_path[segment_index:segment_index + 2]
            horizontal = first[1] == last[1]
            for shift in (-2, 2, -3, 3):
                moved_first = (first[0], first[1] + shift) if horizontal else (first[0] + shift, first[1])
                moved_last = (last[0], last[1] + shift) if horizontal else (last[0] + shift, last[1])
                candidate_path = original_path[:segment_index] + [moved_first, moved_last] + original_path[segment_index + 2:]
                candidate_cells = list(path_cells(candidate_path))
                if (len(candidate_cells) != len(set(candidate_cells))
                        or any(col < 0 or row < 0 for col, row in candidate_cells)
                        or any(abs(a[0] - b[0]) + abs(a[1] - b[1]) < 2
                               for a, b in zip(candidate_path, candidate_path[1:]))):
                    continue
                if (set(candidate_cells) & others) - original_contacts:
                    continue
                if any(p.draw_x <= col < p.draw_x + p.draw_width and p.draw_y <= row < p.draw_y + p.draw_height
                       for col, row in candidate_cells[1:-1] for p in layout.placements.values()):
                    continue
                candidate_paths = paths[:route_index] + [candidate_path] + paths[route_index + 1:]
                candidate_deficit = deficit(candidate_paths)
                if candidate_deficit < original_deficit:
                    route.draw_path = candidate_path
                    original_deficit = candidate_deficit
                    break
            if route.draw_path != original_path:
                break


def _refine_terminal_routes(
    routes: list[RoutedEdge], graph: Graph, layout: GridLayout, bus_indices: set[int],
) -> None:
    """Prefer clear detours, separated bends and readable converging arrivals.

    Keep shared buses intact. Compound frames have their own corridor policy.
    Candidates never enter a node, and perimeter detours add only three cells
    beyond the existing node extent; the normal width fitter measures them.
    """
    if graph.subgraphs:
        return
    horizontal = graph.direction.normalized().is_horizontal

    def quality(route: RoutedEdge, points: list[tuple[int, int]]) -> tuple[int, int, int, int]:
        cells = list(path_cells(points))
        contacts: set[tuple[int, int]] = set()
        for other in routes:
            if other is route or other.edge.style == EdgeStyle.INVISIBLE:
                continue
            other_cells = list(path_cells(other.draw_path))
            shared = set(cells) & set(other_cells)
            if (route.edge.source == other.edge.source and route.edge.style == other.edge.style
                    and route.edge.has_arrow_start == other.edge.has_arrow_start
                    and route.edge.arrow_type_start == other.edge.arrow_type_start):
                for first, second in zip(cells, other_cells):
                    if first != second:
                        break
                    shared.discard(first)
            if (route.edge.target == other.edge.target and route.edge.style == other.edge.style
                    and route.edge.has_arrow_end == other.edge.has_arrow_end
                    and route.edge.arrow_type_end == other.edge.arrow_type_end):
                for first, second in zip(reversed(cells), reversed(other_cells)):
                    if first != second:
                        break
                    shared.discard(first)
            contacts.update(shared)
        cramped = sum(abs(first[0] - last[0]) + abs(first[1] - last[1]) < 2
                      for first, last in zip(points[1:-2], points[2:-1]))
        return len(contacts), cramped, max(0, len(points) - 2), len(cells)

    flow_axis = 0 if horizontal else 1
    # Give links spanning the most ranks first choice of perimeter corridors;
    # a short local detour must not force a control link through every bus.
    for route in sorted(routes, key=lambda candidate: (
        -abs(candidate.draw_path[-1][flow_axis] - candidate.draw_path[0][flow_axis]),
        -len(list(path_cells(candidate.draw_path))),
    )):
        if route.index in bus_indices or route.edge.is_self_reference or route.edge.style == EdgeStyle.INVISIBLE:
            continue
        source = layout.placements[route.edge.source]
        target = layout.placements[route.edge.target]
        if graph.nodes[source.node_id].shape != NodeShape.RECTANGLE or graph.nodes[target.node_id].shape != NodeShape.RECTANGLE:
            continue
        source_layer = source.grid.col if horizontal else source.grid.row
        target_layer = target.grid.col if horizontal else target.grid.row
        if target_layer <= source_layer:
            continue
        start, end = route.draw_path[0], route.draw_path[-1]
        candidates: list[tuple[list[tuple[int, int]], AttachDir, AttachDir, bool]] = []
        departure = AttachDir.RIGHT if horizontal else AttachDir.BOTTOM
        arrival = AttachDir.LEFT if horizontal else AttachDir.TOP
        parallel_arrival = any(
            other is not route and other.edge.target == route.edge.target
            and other.end_dir == arrival for other in routes
        )
        # Parallel faces with a one-cell offset should use a straight port,
        # rather than two touching corners to reach the nominal box center.
        if route.start_dir == departure and route.end_dir == arrival:
            aligned_start = (start[0], end[1]) if horizontal else (end[0], start[1])
            if (source.draw_y < aligned_start[1] < source.draw_y + source.draw_height - 1 if horizontal
                    else source.draw_x < aligned_start[0] < source.draw_x + source.draw_width - 1):
                candidates.append(([aligned_start, end], departure, arrival, False))
            # When another connection already approaches along the flow
            # axis, a late bend can keep the two arrivals visually separate.
            turn = end[0] - 3 if horizontal else end[1] - 3
            if parallel_arrival and turn > (start[0] if horizontal else start[1]):
                late_path = ([start, (turn, start[1]), (turn, end[1]), end] if horizontal
                             else [start, (start[0], turn), (end[0], turn), end])
                candidates.append((late_path, departure, arrival, False))
        primary_start = ((source.draw_x + source.draw_width - 1, source.draw_y + source.draw_height // 2)
                         if horizontal else
                         (source.draw_x + source.draw_width // 2, source.draw_y + source.draw_height - 1))
        # A side arrival can finish with one elbow at the target's row/column.
        if parallel_arrival and horizontal and primary_start[1] < target.draw_y - 1:
            side_end = (target.draw_x + target.draw_width // 2, target.draw_y)
            candidates.append(([primary_start, (side_end[0], primary_start[1]), side_end], departure, AttachDir.TOP, False))
        elif parallel_arrival and horizontal and primary_start[1] > target.draw_y + target.draw_height:
            side_end = (target.draw_x + target.draw_width // 2, target.draw_y + target.draw_height - 1)
            candidates.append(([primary_start, (side_end[0], primary_start[1]), side_end], departure, AttachDir.BOTTOM, False))
        elif parallel_arrival and not horizontal and primary_start[0] < target.draw_x - 1:
            side_end = (target.draw_x, target.draw_y + target.draw_height // 2)
            candidates.append(([primary_start, (primary_start[0], side_end[1]), side_end], departure, AttachDir.LEFT, False))
        elif parallel_arrival and not horizontal and primary_start[0] > target.draw_x + target.draw_width:
            side_end = (target.draw_x + target.draw_width - 1, target.draw_y + target.draw_height // 2)
            candidates.append(([primary_start, (primary_start[0], side_end[1]), side_end], departure, AttachDir.RIGHT, False))
        original_quality = quality(route, route.draw_path)
        if original_quality[0] >= 2:
            # Spend a small perimeter margin to remove multiple intersections.
            side = AttachDir.BOTTOM if horizontal else AttachDir.RIGHT
            outer_lane = max(placement.draw_y + placement.draw_height if horizontal
                             else placement.draw_x + placement.draw_width
                             for placement in layout.placements.values()) + 2
            outer_start = ((source.draw_x + source.draw_width // 2, source.draw_y + source.draw_height - 1)
                           if horizontal else (source.draw_x + source.draw_width - 1, source.draw_y + source.draw_height // 2))
            outer_end = ((target.draw_x + target.draw_width // 2, target.draw_y + target.draw_height - 1)
                         if horizontal else (target.draw_x + target.draw_width - 1, target.draw_y + target.draw_height // 2))
            outer_path = ([outer_start, (outer_start[0], outer_lane), (outer_end[0], outer_lane), outer_end]
                          if horizontal else [outer_start, (outer_lane, outer_start[1]), (outer_lane, outer_end[1]), outer_end])
            candidates.append((outer_path, side, side, True))
        best_quality = original_quality
        for points, start_direction, end_direction, perimeter in candidates:
            candidate_path = simplify_path(list(path_cells(points)))
            candidate_cells = set(path_cells(candidate_path)) - {candidate_path[0], candidate_path[-1]}
            if any(placement.draw_x <= col < placement.draw_x + placement.draw_width
                   and placement.draw_y <= row < placement.draw_y + placement.draw_height
                   for col, row in candidate_cells for placement in layout.placements.values()):
                continue
            candidate_quality = quality(route, candidate_path)
            if perimeter and candidate_quality[0] > original_quality[0] - 2:
                continue
            # Equal-quality elbow paths prefer the late bend offered above.
            if candidate_quality < best_quality or (not perimeter and candidate_quality == best_quality):
                route.draw_path = candidate_path
                route.start_dir, route.end_dir = start_direction, end_direction
                best_quality = candidate_quality


def _straighten_doglegs(routed: list[RoutedEdge], graph: Graph, layout: GridLayout) -> None:
    """Remove redundant excursions after port spreading frees the corridor.

    Never trade a saved bend for new overlap or a new crossing. Work on final
    drawing coordinates so provisional grid ports cannot cause stale detours.
    """
    for route in routed:
        others = set().union(*(set(path_cells(other.draw_path)) for other in routed if other is not route))
        original_cells = set(path_cells(route.draw_path))
        original_contacts = original_cells & others
        points = route.draw_path
        for index in range(len(points) - 4):
            first, second, third, fourth, fifth = points[index:index + 5]
            if first[1] == second[1] and third[1] == fourth[1] and fourth[0] == fifth[0]:
                corner = (fourth[0], first[1])
            elif first[0] == second[0] and third[0] == fourth[0] and fourth[1] == fifth[1]:
                corner = (first[0], fourth[1])
            else:
                continue
            candidate = simplify_path(list(path_cells(points[:index + 1] + [corner] + points[index + 4:])))
            candidate_cells = set(path_cells(candidate))
            if (candidate_cells & others) - original_contacts:
                continue
            if any(p.draw_x <= col < p.draw_x + p.draw_width and p.draw_y <= row < p.draw_y + p.draw_height
                   for col, row in candidate_cells - {points[0], points[-1]}
                   for p in layout.placements.values()):
                continue
            if not _clear_group_corridor(route.edge, candidate, graph, layout):
                continue
            if len(candidate) < len(points):
                route.draw_path = candidate
                break


def _route_sibling_branches(graph: Graph, layout: GridLayout) -> dict[int, RoutedEdge]:
    """Give plain forward siblings one clear bus before routing other edges.

    Use only open routing lanes between a source and a common target layer.
    Labels stay on each destination branch. Group borders may be crossed
    perpendicularly, but titles and unrelated groups are never bus lanes.
    """
    horizontal = graph.direction.normalized().is_horizontal
    endpoint_counts: dict[tuple[str, str], int] = {}
    for edge in graph.edges:
        pair = (edge.source, edge.target)
        endpoint_counts[pair] = endpoint_counts.get(pair, 0) + 1
    groups: dict[tuple[str, int, bool, bool, ArrowType, ArrowType], list[int]] = {}
    for edge_index, edge in enumerate(graph.edges):
        if (edge.source_is_subgraph
                or edge.target_is_subgraph or edge.style != EdgeStyle.SOLID
                or edge.arrow_type_start != ArrowType.ARROW or edge.arrow_type_end != ArrowType.ARROW
                or endpoint_counts[(edge.source, edge.target)] > 1
                or edge_index in graph.link_styles or -1 in graph.link_styles):
            continue
        source = layout.placements.get(edge.source)
        target = layout.placements.get(edge.target)
        if source is None or target is None:
            continue
        source_layer = source.grid.col if horizontal else source.grid.row
        target_layer = target.grid.col if horizontal else target.grid.row
        if target_layer > source_layer:
            signature = (edge.source, target_layer, edge.has_arrow_start, edge.has_arrow_end,
                         edge.arrow_type_start, edge.arrow_type_end)
            groups.setdefault(signature, []).append(edge_index)

    routes: dict[int, RoutedEdge] = {}
    reserved_segments: dict[tuple[tuple[int, int], tuple[int, int]], list[Edge]] = {}
    for (source_id, target_layer, *_endpoint_signature), edge_indices in groups.items():
        if len({graph.edges[index].target for index in edge_indices}) < 2:
            continue
        source = layout.placements[source_id]
        source_layer = source.grid.col if horizontal else source.grid.row
        start_direction = AttachDir.RIGHT if horizontal else AttachDir.BOTTOM
        end_direction = AttachDir.LEFT if horizontal else AttachDir.TOP
        for lane in range(source_layer + 2, target_layer - 1):
            candidates: dict[int, RoutedEdge] = {}
            for edge_index in edge_indices:
                edge = graph.edges[edge_index]
                target = layout.placements[edge.target]
                start = _get_attach_point(source, start_direction)
                end = _get_attach_point(target, end_direction)
                corners = ([start, (lane, start[1]), (lane, end[1]), end]
                           if horizontal else
                           [start, (start[0], lane), (end[0], lane), end])
                cells = list(path_cells(corners))
                if any(not layout.is_free(col, row) for col, row in cells[1:-1]):
                    break
                if any(
                    reserved_segments.get((last, first)) or any(
                        previous.source != edge.source and previous.target != edge.target
                        for previous in reserved_segments.get((first, last), [])
                    )
                    for first, last in zip(cells, cells[1:])
                ):
                    break
                grid_path = simplify_path(cells)
                draw_path = [layout.grid_to_draw_center(col, row) for col, row in grid_path]
                title_safe_path = _avoid_group_titles(draw_path, layout)
                if not _clear_group_corridor(edge, title_safe_path, graph, layout):
                    break
                # Leave an arrow cell between the bus corner and the target.
                if len(draw_path) > 2 and sum(abs(a - b) for a, b in zip(draw_path[-2], draw_path[-1])) < 2:
                    break
                candidates[edge_index] = RoutedEdge(
                    edge=edge, grid_path=grid_path, draw_path=title_safe_path,
                    start_dir=start_direction, end_dir=end_direction,
                    index=edge_index, occupied_cells=set(cells), label=edge.label,
                )
            if len(candidates) == len(edge_indices):
                routes.update(candidates)
                for candidate in candidates.values():
                    candidate_cells = list(path_cells(candidate.grid_path))
                    for first, last in zip(candidate_cells, candidate_cells[1:]):
                        reserved_segments.setdefault((first, last), []).append(candidate.edge)
                break
    return routes


def _avoid_group_titles(path: list[tuple[int, int]], layout: GridLayout) -> list[tuple[int, int]]:
    """Refine routes that would be erased when group headings are painted."""
    if len(path) < 2:
        return path
    title_cells = {
        (col, bounds.y + 1 + offset)
        for bounds in layout.subgraph_bounds
        for offset, line in enumerate(bounds.subgraph.label.split("\n"))
        for col in range(bounds.x + 2, bounds.x + 2 + display_width(line))
    }
    if not title_cells.intersection(path_cells(path)):
        return path
    node_cells = {
        (col, row)
        for placement in layout.placements.values()
        for col in range(placement.draw_x, placement.draw_x + placement.draw_width)
        for row in range(placement.draw_y, placement.draw_y + placement.draw_height)
    }
    start, end = path[0], path[-1]
    start_dx = (path[1][0] > start[0]) - (path[1][0] < start[0])
    start_dy = (path[1][1] > start[1]) - (path[1][1] < start[1])
    end_dx = (path[-2][0] > end[0]) - (path[-2][0] < end[0])
    end_dy = (path[-2][1] > end[1]) - (path[-2][1] < end[1])
    departure = (start[0] + 3 * start_dx, start[1] + 3 * start_dy)
    arrival = (end[0] + 3 * end_dx, end[1] + 3 * end_dy)
    stubs = {(start[0] + step * start_dx, start[1] + step * start_dy) for step in range(3)}
    stubs.update((end[0] + step * end_dx, end[1] + step * end_dy) for step in range(3))
    blocked = node_cells | title_cells | stubs
    if departure in blocked or arrival in blocked:
        return path
    original_cells = set(path_cells(path))
    left = max(0, min(col for col, row in original_cells) - 3)
    right = max(col for col, row in original_cells) + 3
    top = max(0, min(row for col, row in original_cells) - 3)
    bottom = max(row for col, row in original_cells) + 3
    deviation_cells = {(col, row) for col in range(left, right + 1) for row in range(top, bottom + 1)
                       if (col, row) not in original_cells}
    refined = find_path(
        *departure, *arrival,
        lambda col, row: col >= 0 and row >= 0 and (col, row) not in blocked,
        deviation_cells,
        max_iterations=30000,
    )
    if refined is None:
        return path
    return simplify_path(list(path_cells([start, *refined, end])))


def _clear_group_corridor(
    edge: Edge, draw_path: list[tuple[int, int]], graph: Graph, layout: GridLayout,
) -> bool:
    """Validate a candidate bus against actual group borders and headings."""
    allowed: set[str] = set()
    for endpoint, is_group in ((edge.source, edge.source_is_subgraph),
                               (edge.target, edge.target_is_subgraph)):
        group = (graph.find_subgraph_by_id(endpoint) if is_group
                 else graph.find_subgraph_for_node(endpoint))
        while group is not None:
            allowed.add(group.id)
            group = group.parent
    cells = set(path_cells(draw_path))
    for bounds in layout.subgraph_bounds:
        left, top = bounds.x, bounds.y
        right, bottom = left + bounds.width - 1, top + bounds.height - 1
        if bounds.subgraph.id not in allowed:
            if any(left <= col <= right and top <= row <= bottom for col, row in cells):
                return False
        for offset, title_line in enumerate(bounds.subgraph.label.split("\n")):
            if any((col, top + 1 + offset) in cells
                   for col in range(left + 2, left + 2 + display_width(title_line))):
                return False
        # Following a border hides the distinction between frame and bus.
        for first, last in zip(draw_path, draw_path[1:]):
            if (first[0] == last[0] and first[0] in (left, right)
                    and max(min(first[1], last[1]), top) < min(max(first[1], last[1]), bottom)):
                return False
            if (first[1] == last[1] and first[1] in (top, bottom)
                    and max(min(first[0], last[0]), left) < min(max(first[0], last[0]), right)):
                return False
    return True


def _separate_parallel_edges(routed: list[RoutedEdge], graph: Graph, layout: GridLayout) -> None:
    """Allocate ordered ports and independent character-cell lanes to duplicates.

    The coarse routing grid has only one port per face. Refine duplicate
    forward edges in drawing coordinates, committing a group only when
    every lane clears nodes, headings, and its sibling lanes.
    """
    groups: dict[tuple[str, str], list[RoutedEdge]] = {}
    for route in routed:
        if (not route.edge.is_self_reference and not route.edge.source_is_subgraph
                and not route.edge.target_is_subgraph and route.edge.style != EdgeStyle.INVISIBLE):
            groups.setdefault(tuple(sorted((route.edge.source, route.edge.target))), []).append(route)
    horizontal = graph.direction.normalized().is_horizontal
    node_cells = {
        (col, row)
        for placement in layout.placements.values()
        for col in range(placement.draw_x, placement.draw_x + placement.draw_width)
        for row in range(placement.draw_y, placement.draw_y + placement.draw_height)
    } if any(len(group) > 1 for group in groups.values()) else set()
    for endpoint_ids, group in groups.items():
        if len(group) < 2:
            continue
        source_id, target_id = sorted(endpoint_ids, key=lambda node_id: (
            layout.placements[node_id].grid.col if horizontal else layout.placements[node_id].grid.row
        ))
        source, target = layout.placements[source_id], layout.placements[target_id]
        if (target.grid.col <= source.grid.col if horizontal else target.grid.row <= source.grid.row):
            continue
        ordered = sorted(group, key=lambda route: (route.label, route.edge.style.value, route.index))
        occupied: set[tuple[int, int]] = set()
        candidates: list[list[tuple[int, int]]] = []
        other_cells = set().union(*(set(path_cells(route.draw_path)) for route in routed
                                   if tuple(sorted((route.edge.source, route.edge.target))) != endpoint_ids))
        reserved: set[tuple[int, int]] = set()
        ports: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for lane_index in range(len(ordered)):
            port_span = min(source.draw_height, target.draw_height) - 3 if horizontal else min(source.draw_width, target.draw_width) - 3
            lane_step = min(2 if horizontal else 16, port_span // (len(ordered) - 1))
            source_span = source.draw_height - 3 if horizontal else source.draw_width - 3
            target_span = target.draw_height - 3 if horizontal else target.draw_width - 3
            source_offset = 1 + (source_span - (len(ordered) - 1) * lane_step) // 2 + lane_index * lane_step
            target_offset = 1 + (target_span - (len(ordered) - 1) * lane_step) // 2 + lane_index * lane_step
            start = ((source.draw_x + source.draw_width - 1, source.draw_y + source_offset)
                     if horizontal else
                     (source.draw_x + source_offset, source.draw_y + source.draw_height - 1))
            end = ((target.draw_x, target.draw_y + target_offset)
                   if horizontal else (target.draw_x + target_offset, target.draw_y))
            ports.append((start, end))
            for distance in (1, 2):
                reserved.add((start[0] + distance, start[1]) if horizontal else (start[0], start[1] + distance))
                reserved.add((end[0] - distance, end[1]) if horizontal else (end[0], end[1] - distance))
        for route, (start, end) in zip(ordered, ports):
            departure = (start[0] + 2, start[1]) if horizontal else (start[0], start[1] + 2)
            arrival = (end[0] - 2, end[1]) if horizontal else (end[0], end[1] - 2)
            own_stubs = set(path_cells([start, departure])) | set(path_cells([arrival, end]))

            def is_clear(col: int, row: int) -> bool:
                if col < 0 or row < 0 or (col, row) in node_cells or (col, row) in occupied:
                    return False
                if (col, row) in reserved and (col, row) not in own_stubs:
                    return False
                return _clear_group_corridor(route.edge, [(col, row)], graph, layout)

            cells = find_path(*departure, *arrival, is_clear, other_cells, max_iterations=20000)
            if cells is None:
                break
            candidate = simplify_path(list(path_cells([start, *cells, end])))
            if not _clear_group_corridor(route.edge, candidate, graph, layout):
                break
            candidates.append(candidate)
            occupied.update(path_cells(candidate))
        if len(candidates) == len(ordered):
            for route, candidate in zip(ordered, candidates):
                forward = route.edge.source == source_id
                route.draw_path = candidate if forward else candidate[::-1]
                route.start_dir = (AttachDir.RIGHT if horizontal else AttachDir.BOTTOM) if forward else (AttachDir.LEFT if horizontal else AttachDir.TOP)
                route.end_dir = (AttachDir.LEFT if horizontal else AttachDir.TOP) if forward else (AttachDir.RIGHT if horizontal else AttachDir.BOTTOM)


def _spread_shared_endpoints(
    routed: list[RoutedEdge],
    layout: GridLayout,
    sg_bounds: dict[str, SubgraphBounds],
    graph: Graph,
) -> None:
    """Share compatible arrivals and separate visually distinct endpoints."""
    from collections import defaultdict

    end_groups: dict[tuple[int, int], list[RoutedEdge]] = defaultdict(list)
    for re in routed:
        if len(re.draw_path) >= 2:
            end_groups[re.draw_path[-1]].append(re)

    for point, edges in end_groups.items():
        if len(edges) <= 1:
            continue
        signatures = {
            (route.edge.target, route.end_dir, route.edge.style,
             route.edge.has_arrow_end, route.edge.arrow_type_end,
             tuple(sorted(graph.link_styles.get(route.index, graph.link_styles.get(-1, {})).items())))
            for route in edges
        }
        if len(signatures) == 1:
            continue
        tgt_id = edges[0].edge.target
        tgt = layout.placements.get(tgt_id)
        if not tgt and tgt_id in sg_bounds:
            sb = sg_bounds[tgt_id]
            from ..layout.grid import GridCoord
            tgt = NodePlacement(
                node_id=tgt_id, grid=GridCoord(0, 0),
                draw_x=sb.x, draw_y=sb.y, draw_width=sb.width, draw_height=sb.height,
            )
        if not tgt:
            continue
        vertical_arrival = edges[0].end_dir in (AttachDir.TOP, AttachDir.BOTTOM)
        ordered_edges = sorted(edges, key=lambda route: (
            route.draw_path[0][0 if vertical_arrival else 1],
            route.edge.source, route.label, route.index,
        ))
        _apply_spread(ordered_edges, point, tgt, is_start=False, layout=layout)


def _apply_spread(
    edges: list[RoutedEdge],
    point: tuple[int, int],
    placement: NodePlacement,
    is_start: bool,
    layout: GridLayout,
) -> None:
    """Offset each edge's endpoint along the node border.

    For TOP/BOTTOM attachment (horizontal spread): shifts the adjacent
    corner point to match the new x, avoiding backward horizontal jog
    segments that create stray line artifacts.

    For LEFT/RIGHT attachment (vertical spread): moves the adjacent
    corner vertically, keeping the final approach horizontal.
    """
    if is_start:
        return  # start spreading disabled; causes border artifacts

    n = len(edges)
    px, py = point
    attach = edges[0].end_dir

    if attach in (AttachDir.TOP, AttachDir.BOTTOM):
        # Vertical arrival: spread horizontally along the border.
        min_x = placement.draw_x + 1
        max_x = placement.draw_x + placement.draw_width - 2
        spread_range = max_x - min_x
        if spread_range < n - 1:
            return
        step = min(2, spread_range // max(n - 1, 1))
        for i, re in enumerate(edges):
            offset = int((i - (n - 1) / 2) * step)
            if offset == 0:
                continue
            new_x = max(min_x, min(max_x, px + offset))
            adj_x, adj_y = re.draw_path[-2]
            re.draw_path[-1] = (new_x, py)
            re.draw_path[-2] = (new_x, adj_y)
    else:
        # Horizontal arrival: spread vertically along the border.
        # Only spread when the approach segment is long enough to fit
        # a clean corner + line + border arrow (>= 2 cells from the last turn
        # to the endpoint).  Tight gaps produce cramped ╭▶ patterns.
        min_y = placement.draw_y + 1
        max_y = placement.draw_y + placement.draw_height - 2
        spread_range = max_y - min_y
        if spread_range < n - 1:
            return
        # Check that all edges have enough approach distance
        min_gap = min(abs(px - re.draw_path[-2][0]) for re in edges)
        if min_gap < 2:
            return  # not enough room for clean corner + arrow
        step = min(2, spread_range // max(n - 1, 1))
        for i, re in enumerate(edges):
            offset = int((i - (n - 1) / 2) * step)
            if offset == 0:
                continue
            new_y = max(min_y, min(max_y, py + offset))
            adj_x, adj_y = re.draw_path[-2]
            re.draw_path[-1] = (px, new_y)
            source = layout.placements.get(re.edge.source)
            if len(re.draw_path) > 2:
                re.draw_path[-2] = (adj_x, new_y)
            elif source is not None and source.draw_y < new_y < source.draw_y + source.draw_height - 1:
                re.draw_path[0] = (adj_x, new_y)
            else:
                approach_x = px - 2 if px > adj_x else px + 2
                re.draw_path[-1:-1] = [(approach_x, adj_y), (approach_x, new_y)]


def _sg_member_placements(
    sb: SubgraphBounds, layout: GridLayout,
) -> list[NodePlacement]:
    """Placements of all nodes inside a subgraph (recursively)."""
    member_ids: set[str] = set()

    def _gather(sg) -> None:
        member_ids.update(sg.node_ids)
        for child in sg.children:
            _gather(child)

    _gather(sb.subgraph)
    return [layout.placements[m] for m in member_ids if m in layout.placements]


def _resolve_endpoints(
    edge: Edge,
    layout: GridLayout,
    sg_bounds: dict[str, SubgraphBounds],
) -> tuple[NodePlacement | None, NodePlacement | None]:
    """Resolve edge endpoints to placements.

    For a subgraph endpoint, synthesize a virtual placement: the draw box
    is the subgraph's bounding box, and the grid cell is borrowed from a
    member node. When a subgraph is involved, the source and target cells
    are chosen jointly (closest member pair) so the edge crosses the box
    border on the facing side without jogs. The routed path is later
    clipped to the box border by ``_clip_endpoint_to_box``.
    """
    if not edge.source_is_subgraph and not edge.target_is_subgraph:
        return layout.placements.get(edge.source), layout.placements.get(edge.target)

    def _candidates(node_id: str, is_sg: bool) -> list[NodePlacement]:
        if not is_sg:
            p = layout.placements.get(node_id)
            return [p] if p else []
        sb = sg_bounds.get(node_id)
        if sb is None:
            return []
        return _sg_member_placements(sb, layout)

    src_cands = _candidates(edge.source, edge.source_is_subgraph)
    tgt_cands = _candidates(edge.target, edge.target_is_subgraph)
    if not src_cands or not tgt_cands:
        return None, None

    def _center(p: NodePlacement) -> tuple[int, int]:
        return (p.draw_x + p.draw_width // 2, p.draw_y + p.draw_height // 2)

    best_s, best_t = min(
        ((s, t) for s in src_cands for t in tgt_cands),
        key=lambda pair: (
            abs(_center(pair[0])[0] - _center(pair[1])[0])
            + abs(_center(pair[0])[1] - _center(pair[1])[1]),
            pair[0].node_id,
            pair[1].node_id,
        ),
    )

    from ..layout.grid import GridCoord

    def _virtualize(node_id: str, is_sg: bool, member: NodePlacement) -> NodePlacement:
        if not is_sg:
            return member
        sb = sg_bounds[node_id]
        return NodePlacement(
            node_id=node_id,
            grid=GridCoord(col=member.grid.col, row=member.grid.row),
            draw_x=sb.x,
            draw_y=sb.y,
            draw_width=sb.width,
            draw_height=sb.height,
        )

    return (
        _virtualize(edge.source, edge.source_is_subgraph, best_s),
        _virtualize(edge.target, edge.target_is_subgraph, best_t),
    )


def _clip_endpoint_to_box(
    draw_path: list[tuple[int, int]],
    sb: SubgraphBounds,
    from_start: bool,
) -> None:
    """Snap one end of a draw path onto a subgraph's border rectangle.

    The path was routed from a member node inside the box; drop the part
    inside the box and move the terminal point to where the path crosses
    the border, so the edge visually attaches to the subgraph itself.
    """
    if len(draw_path) < 2:
        return

    pts = draw_path if from_start else draw_path[::-1]
    x0, y0 = sb.x, sb.y
    x1, y1 = sb.x + sb.width - 1, sb.y + sb.height - 1

    def strictly_inside(p: tuple[int, int]) -> bool:
        return x0 < p[0] < x1 and y0 < p[1] < y1

    k = 0
    while k < len(pts) and strictly_inside(pts[k]):
        k += 1
    if k >= len(pts):
        return  # path never leaves the box; keep as-is

    if k == 0:
        # Terminal point is already on/outside the border: pull it back
        # onto the box edge along the first segment's axis.
        ax, ay = pts[0]
        bx, by = pts[1]
        if ax == bx:
            new = [(ax, min(max(ay, y0), y1))] + pts[1:]
        else:
            new = [(min(max(ax, x0), x1), ay)] + pts[1:]
    else:
        # Crossing point on the segment pts[k-1] (inside) -> pts[k] (outside).
        px, py = pts[k - 1]
        qx, qy = pts[k]
        if px == qx:
            cross = (px, y1 if qy > py else y0)
        else:
            cross = (x1 if qx > px else x0, py)
        new = [cross] + pts[k:]

    if len(new) >= 2 and new[0] == new[1]:
        new = new[1:]
    if len(new) < 2:
        return  # degenerate; keep the original path

    # If the last turn sits right next to the border, the terminal segment
    # has no room for the arrowhead/tee plus a line cell. Shift the turn
    # segment away from the border to open up the approach.
    if len(new) >= 4:
        (cx, cy), (nx, ny), (mx, my) = new[0], new[1], new[2]
        px, py = new[3]
        if cx == nx and ny == my and abs(cy - ny) < 3:
            # Perpendicular jog before a vertical approach
            sign = 1 if cy > ny else -1
            new_y = cy - 3 * sign
            if (sign > 0 and py < new_y) or (sign < 0 and py > new_y):
                new[1] = (nx, new_y)
                new[2] = (mx, new_y)
        elif cy == ny and nx == mx and abs(cx - nx) < 3:
            # Perpendicular jog before a horizontal approach
            sign = 1 if cx > nx else -1
            new_x = cx - 3 * sign
            if (sign > 0 and px < new_x) or (sign < 0 and px > new_x):
                new[1] = (new_x, ny)
                new[2] = (new_x, my)

    if not from_start:
        new = new[::-1]
    draw_path[:] = new


def _compute_sg_regions(
    layout: GridLayout,
    sg_bounds: dict[str, SubgraphBounds],
) -> dict[str, set[tuple[int, int]]]:
    """Grid cells covered by each subgraph box (member blocks + border channels)."""
    regions: dict[str, set[tuple[int, int]]] = {}
    for sg_id, sb in sg_bounds.items():
        members = _sg_member_placements(sb, layout)
        if not members:
            continue
        min_col = min(p.grid.col for p in members) - 1
        max_col = max(p.grid.col for p in members) + 1
        min_row = min(p.grid.row for p in members) - 1
        max_row = max(p.grid.row for p in members) + 1
        regions[sg_id] = {
            (c, r)
            for c in range(min_col, max_col + 1)
            for r in range(min_row, max_row + 1)
        }
    return regions


def _foreign_sg_cells(
    edge: Edge,
    graph: Graph,
    sg_regions: dict[str, set[tuple[int, int]]],
) -> set[tuple[int, int]]:
    """Cells of subgraph boxes this edge should avoid routing through.

    A subgraph is off-limits unless one of the edge's endpoints lives in it
    (or in a subgraph nested inside/around it).
    """
    if not sg_regions:
        return set()

    allowed: set[str] = set()
    for endpoint, is_sg in (
        (edge.source, edge.source_is_subgraph),
        (edge.target, edge.target_is_subgraph),
    ):
        if is_sg:
            sg = graph.find_subgraph_by_id(endpoint)
            # The subgraph itself, its ancestors, and its descendants: the
            # borrowed attachment cell may sit inside a nested child box.
            stack = [sg] if sg else []
            while stack:
                cur = stack.pop()
                allowed.add(cur.id)
                stack.extend(cur.children)
            while sg:
                allowed.add(sg.id)
                sg = sg.parent
        else:
            sg = graph.find_subgraph_for_node(endpoint)
            while sg:
                allowed.add(sg.id)
                sg = sg.parent

    cells: set[tuple[int, int]] = set()
    for sg_id, region in sg_regions.items():
        if sg_id not in allowed:
            cells |= region
    return cells


def _get_attach_point(
    placement: NodePlacement,
    attach_dir: AttachDir,
) -> tuple[int, int]:
    """Get the grid coordinate of an attachment point on a node."""
    gc = placement.grid
    if attach_dir == AttachDir.TOP:
        return (gc.col, gc.row - 1)
    elif attach_dir == AttachDir.BOTTOM:
        return (gc.col, gc.row + 1)
    elif attach_dir == AttachDir.LEFT:
        return (gc.col - 1, gc.row)
    else:  # RIGHT
        return (gc.col + 1, gc.row)


def _determine_directions(
    src: NodePlacement,
    tgt: NodePlacement,
    direction: Direction,
) -> tuple[tuple[AttachDir, AttachDir], tuple[AttachDir, AttachDir]]:
    """Determine preferred and alternative start/end attachment directions."""
    sc, sr = src.grid.col, src.grid.row
    tc, tr = tgt.grid.col, tgt.grid.row

    if direction.is_horizontal:
        # Primary flow is left-to-right
        if tc > sc:
            preferred = (AttachDir.RIGHT, AttachDir.LEFT)
        elif tc < sc:
            # A return can use the lower corridor or the reserved upper lane.
            preferred = (AttachDir.BOTTOM, AttachDir.BOTTOM)
            return preferred, (AttachDir.TOP, AttachDir.TOP)
        else:
            preferred = (AttachDir.BOTTOM, AttachDir.TOP) if tr > sr else (AttachDir.TOP, AttachDir.BOTTOM)

        # Alternative uses vertical
        if tr > sr:
            alt = (AttachDir.BOTTOM, AttachDir.TOP)
        elif tr < sr:
            alt = (AttachDir.TOP, AttachDir.BOTTOM)
        else:
            alt = preferred
    else:
        # Primary flow is top-to-bottom
        if tr > sr:
            preferred = (AttachDir.BOTTOM, AttachDir.TOP)
        elif tr < sr:
            # A return can use either side, including a reserved left lane.
            preferred = (AttachDir.RIGHT, AttachDir.RIGHT)
            return preferred, (AttachDir.LEFT, AttachDir.LEFT)
        else:
            preferred = (AttachDir.RIGHT, AttachDir.LEFT) if tc > sc else (AttachDir.LEFT, AttachDir.RIGHT)

        # Alternative uses horizontal
        if tc > sc:
            alt = (AttachDir.RIGHT, AttachDir.LEFT)
        elif tc < sc:
            alt = (AttachDir.LEFT, AttachDir.RIGHT)
        else:
            alt = preferred

    return preferred, alt


def _route_edge(
    edge: Edge,
    src: NodePlacement,
    tgt: NodePlacement,
    layout: GridLayout,
    direction: Direction,
    soft_obstacles: set[tuple[int, int]],
    flows: dict[tuple[int, int], set[tuple[int, int, str, str, EdgeStyle]]] | None = None,
    reserved_approaches: set[tuple[int, int]] | None = None,
) -> RoutedEdge:
    """Route a single edge between two nodes."""
    preferred, alt = _determine_directions(src, tgt, direction)
    if (layout.width_budget is not None and direction.is_horizontal
            and src.grid.row == tgt.grid.row and tgt.grid.col > src.grid.col):
        # Long edges can approach the bottom face instead of crossing the
        # short, labeled connection immediately to the target's left.
        alt = (AttachDir.BOTTOM, AttachDir.BOTTOM)
    occupied_flows = flows or {}
    label_cells = reserved_approaches or set()

    def flow_penalty(col: int, row: int, dx: int, dy: int) -> float:
        existing = occupied_flows.get((col, row), set())
        penalty = 0.0
        for direction_x, direction_y, source_id, target_id, style in existing:
            compatible = ((source_id == edge.source or target_id == edge.target)
                          and style == edge.style and not edge.has_arrow_start)
            if (direction_x, direction_y) == (-dx, -dy):
                penalty = max(penalty, 20.0)
            elif direction_x * dx + direction_y * dy == 0:
                if not (layout.width_budget is not None and direction.is_horizontal and compatible):
                    penalty = max(penalty, 4.0)
            elif not compatible:
                penalty = max(penalty, 12.0)
        return penalty

    # Try preferred path
    # Don't exclude source/target from obstacles — edges must not route
    # through node borders. The pathfinder allows start/end points natively.
    start_pref = _get_attach_point(src, preferred[0])
    end_pref = _get_attach_point(tgt, preferred[1])

    path_pref = find_path(
        start_pref[0], start_pref[1],
        end_pref[0], end_pref[1],
        lambda c, r: layout.is_free(c, r) and (c, r) not in label_cells,
        soft_obstacles,
        step_penalty=flow_penalty,
    )

    # Try alternative path
    start_alt = _get_attach_point(src, alt[0])
    end_alt = _get_attach_point(tgt, alt[1])

    path_alt = find_path(
        start_alt[0], start_alt[1],
        end_alt[0], end_alt[1],
        lambda c, r: layout.is_free(c, r) and (c, r) not in label_cells,
        soft_obstacles,
        step_penalty=flow_penalty,
    )

    if path_pref is None and path_alt is None and label_cells:
        # Label reservations are a preference, never a reason to lose an
        # edge. Relax them once; ordinary obstacles and flow costs remain.
        return _route_edge(edge, src, tgt, layout, direction, soft_obstacles, occupied_flows)

    # Pick path: prefer the flow-aligned direction unless the alternative
    # is significantly shorter.  A small bias keeps edges exiting in the
    # natural flow direction (BOTTOM for TD, RIGHT for LR) which avoids
    # tight corners next to node borders.
    _PREFER_BIAS = 3  # allow preferred path to be up to 3 cells longer
    def route_cost(candidate: list[tuple[int, int]]) -> float:
        return len(candidate) + sum(
            flow_penalty(last[0], last[1], last[0] - first[0], last[1] - first[1])
            for first, last in zip(candidate, candidate[1:])
        )
    if path_pref and path_alt:
        backward = (tgt.grid.col < src.grid.col if direction.is_horizontal
                    else tgt.grid.row < src.grid.row)
        preferred_crossings = len(set(path_pref[1:-1]) & soft_obstacles) if backward else 0
        alternative_crossings = len(set(path_alt[1:-1]) & soft_obstacles) if backward else 0
        perpendicular_axis = 1 if direction.is_horizontal else 0
        canvas_extent = layout.canvas_height if direction.is_horizontal else layout.canvas_width
        preferred_overflow = max(0, max(layout.grid_to_draw_center(*point)[perpendicular_axis]
                                        for point in path_pref) - canvas_extent + 1) if backward else 0
        alternative_overflow = max(0, max(layout.grid_to_draw_center(*point)[perpendicular_axis]
                                          for point in path_alt) - canvas_extent + 1) if backward else 0
        # Pathfinding already accounts for occupied lanes. Use the same
        # cost when choosing a node face in every orientation, otherwise a
        # shorter congested route wins back the crossings A* avoided.
        preferred_cost = route_cost(path_pref)
        alternative_cost = route_cost(path_alt)
        if (preferred_crossings, preferred_overflow, preferred_cost) <= (
                alternative_crossings, alternative_overflow, alternative_cost + _PREFER_BIAS):
            path, start_dir, end_dir = path_pref, preferred[0], preferred[1]
        else:
            path, start_dir, end_dir = path_alt, alt[0], alt[1]
    elif path_pref:
        path, start_dir, end_dir = path_pref, preferred[0], preferred[1]
    elif path_alt:
        path, start_dir, end_dir = path_alt, alt[0], alt[1]
    else:
        raise RoutingError(f"No orthogonal route for {edge.source} -> {edge.target}")

    simplified = simplify_path(path)

    # Convert to drawing coordinates (center of each cell)
    draw_path = [layout.grid_to_draw_center(c, r) for c, r in simplified]

    # Track occupied cells
    occupied = set(path)

    return RoutedEdge(
        edge=edge,
        grid_path=simplified,
        draw_path=draw_path,
        start_dir=start_dir,
        end_dir=end_dir,
        label=edge.label,
        occupied_cells=occupied,
    )


def _route_group_loop(
    edge: Edge, source: NodePlacement, graph: Graph, layout: GridLayout,
) -> RoutedEdge:
    """Attach a self-loop to the group frame, outside its member nodes."""
    left, top = source.draw_x, source.draw_y
    right, bottom = left + source.draw_width - 1, top + source.draw_height - 1
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    candidates = [
        (AttachDir.RIGHT, [(right, center_y - 1), (right + 3, center_y - 1),
                          (right + 3, center_y + 1), (right, center_y + 1)]),
        (AttachDir.BOTTOM, [(center_x - 1, bottom), (center_x - 1, bottom + 3),
                           (center_x + 1, bottom + 3), (center_x + 1, bottom)]),
        (AttachDir.LEFT, [(left, center_y - 1), (left - 3, center_y - 1),
                         (left - 3, center_y + 1), (left, center_y + 1)]),
    ]
    for attachment, candidate in candidates:
        cells = list(path_cells(candidate))
        if any(col < 0 or row < 0 for col, row in cells):
            continue
        if any(placement.draw_x <= col < placement.draw_x + placement.draw_width
               and placement.draw_y <= row < placement.draw_y + placement.draw_height
               for col, row in cells for placement in layout.placements.values()):
            continue
        if _clear_group_corridor(edge, candidate, graph, layout):
            return RoutedEdge(edge, draw_path=candidate, start_dir=attachment,
                              end_dir=attachment, label=edge.label)
    raise RoutingError(f"No orthogonal self-loop for subgraph {edge.source}")


def _route_self_edge(
    edge: Edge,
    src: NodePlacement,
    layout: GridLayout,
    direction: Direction,
) -> RoutedEdge:
    """Route a self-referencing edge (A --> A).

    Self-edge loops out from the top, goes right, comes back down to the right side.
    """
    gc = src.grid

    # Loop: top → above-right → right → back to top-right area
    # Grid path: exit top, go up, go right, go down, enter right side
    path = [
        (gc.col, gc.row - 1),      # top border of node
        (gc.col, gc.row - 2),      # one cell above
        (gc.col + 2, gc.row - 2),  # above and to the right
        (gc.col + 2, gc.row),      # right and level with center
        (gc.col + 1, gc.row),      # right border of node
    ]
    start_dir = AttachDir.TOP
    end_dir = AttachDir.RIGHT

    draw_path = [layout.grid_to_draw_center(c, r) for c, r in path]
    occupied = set(path)

    return RoutedEdge(
        edge=edge,
        grid_path=path,
        draw_path=draw_path,
        start_dir=start_dir,
        end_dir=end_dir,
        label=edge.label,
        occupied_cells=occupied,
    )
