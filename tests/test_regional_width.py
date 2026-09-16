"""Readable regional allocation and route ownership in the integrated diagram."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from termaid import parse, render
from termaid.cli import main
from termaid.layout.graph_plan import plan_graph
from termaid.layout.labels import LabelPlan
from termaid.renderer.charset import UNICODE
from termaid.renderer.draw import _draw_edge_label, _draw_overhanging_branch_label, render_graph_canvas
from termaid.layout.scene import LayoutScene
from termaid.graph.model import Edge
from termaid.routing.router import RoutedEdge, path_cells
from termaid.utils import display_width


FIXTURES = Path(__file__).parent / 'fixtures'
SOURCE = (FIXTURES / 'mooncake_integrated.mmd').read_text()
IDENTIFIERS = ('MasterService', 'FileStorage', 'NOF_SSD', 'LOCAL_DISK', 'RealClient')


def arguments(width, *, use_ascii=False, output_format='text', strict=True):
    return [str(FIXTURES / 'mooncake_integrated.mmd'), '--width', str(width),
            '--fit-mode', 'wrap', '--gap', '3', '--padding-x', '1', '--padding-y', '0',
            '--format', output_format, *(['--ascii'] if use_ascii else []),
            *(['--strict-width'] if strict else [])]


@pytest.mark.parametrize('width', [140, 180, 220])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_integrated_readable_rendering(width, use_ascii, capsys):
    assert main(arguments(width, use_ascii=use_ascii)) == 0
    captured = capsys.readouterr()
    assert not captured.err
    output = captured.out
    assert max(map(display_width, output.splitlines())) <= width
    assert '[1]' not in output
    assert all(output.count(identifier) == 1 for identifier in IDENTIFIERS)
    assert output.count('Pod A:') == 1
    assert all(label in output for label in ('Control plane', 'Data plane', 'Pod B:', 'Offload', 'SPDK:', 'NVMe-oF'))
    if not use_ascii:
        assert 'xx' not in output and 'x▶' not in output
        assert output == (FIXTURES / f'mooncake_integrated_{width}.snap').read_text()
        if width == 220:
            assert 'SPDK: NVMe-oF' in output and 'Local I/O' in output


@pytest.mark.parametrize('width', [140, 180, 220])
def test_styled_width_fitting_matches_plain(width, capsys):
    assert main(arguments(width)) == 0
    plain = capsys.readouterr().out
    assert main(arguments(width, output_format='styled-json')) == 0
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    assert '\n'.join(''.join(chunk['text'] for chunk in row) for row in document['lines']) + '\n' == plain
    labels = ' '.join(chunk['text'] for row in document['lines'] for chunk in row if chunk['style'] == 'edge_label')
    assert 'Offload' in labels and 'SPDK:' in labels and 'NVMe-oF' in labels


@pytest.mark.parametrize('width', [60, 90, 120])
def test_infeasible_width_reports_overflow_without_fragmenting_nodes(width, capsys):
    assert main(arguments(width, strict=False)) == 0
    captured = capsys.readouterr()
    assert 'Warning: diagram' in captured.err
    assert max(map(display_width, captured.out.splitlines())) > width
    assert all(identifier in captured.out for identifier in IDENTIFIERS)
    # A constrained label still has its full source text in a reference.
    if width <= 90:
        assert '[1]' in captured.out and 'Offload' in captured.out
    assert main(arguments(width)) == 2
    strict_capture = capsys.readouterr()
    assert 'Error: diagram' in strict_capture.err and not strict_capture.out


@pytest.mark.parametrize('width,budget', [(140, 8), (180, 20), (220, 20)])
def test_geometry_preserves_topology_and_clearance(width, budget):
    graph = parse(SOURCE)
    original_graph = deepcopy(graph)
    options = dict(padding_x=0, padding_y=0, gap=1, max_label_width=budget, max_width=width)
    geometry = plan_graph(graph, **options)
    scene = render_graph_canvas(graph, **options)
    assert graph.nodes == original_graph.nodes and graph.edges == original_graph.edges
    assert graph.direction == original_graph.direction and graph.node_order == original_graph.node_order
    for group_id in ('Control', 'Data', 'PodB'):
        group = graph.find_subgraph_by_id(group_id)
        original_group = original_graph.find_subgraph_by_id(group_id)
        assert (group.label, group.node_ids, [child.id for child in group.children]) == (
            original_group.label, original_group.node_ids, [child.id for child in original_group.children],
        )
    assert set(geometry.layout.placements) == set(graph.nodes)
    assert len(geometry.routes) == len(graph.edges) == 10
    assert len(geometry.layout.placements) == 9
    assert [route.edge for route in geometry.routes] == graph.edges
    assert {bounds.subgraph.id for bounds in geometry.layout.subgraph_bounds} == {'Control', 'Data', 'PodB'}
    data_bounds = next(bounds for bounds in geometry.layout.subgraph_bounds if bounds.subgraph.id == 'Data')
    assert data_bounds.width / geometry.layout.canvas_width > 0.7

    # The early 29-column label gap no longer squeezes the complex region.
    app = geometry.layout.placements['App']
    client = geometry.layout.placements['Client']
    assert client.draw_x - app.draw_x - app.draw_width <= 20
    assert geometry.layout.placements['Master'].draw_width >= display_width('MasterService') + 2
    for identifier in IDENTIFIERS:
        assert any(identifier in node.label for node in geometry.graph.nodes.values())

    segment_sets = []
    for route in geometry.routes:
        cells = list(path_cells(route.draw_path))
        assert cells[0] == route.draw_path[0] and cells[-1] == route.draw_path[-1]
        assert all(first[0] == last[0] or first[1] == last[1]
                   for first, last in zip(route.draw_path, route.draw_path[1:]))
        segment_sets.append(set(zip(cells, cells[1:])))
        # The destination head has a visible connector before it.
        col, row = cells[-2]
        assert scene.get(row, col) in '─│┄┆'
        for placement in geometry.layout.placements.values():
            assert not any(placement.draw_x < col < placement.draw_x + placement.draw_width - 1
                           and placement.draw_y < row < placement.draw_y + placement.draw_height - 1
                           for col, row in cells)
        for bounds in geometry.layout.subgraph_bounds:
            for first, last in zip(route.draw_path, route.draw_path[1:]):
                if first[0] == last[0] and first[0] in (bounds.x, bounds.x + bounds.width - 1):
                    assert max(min(first[1], last[1]), bounds.y) >= min(max(first[1], last[1]), bounds.y + bounds.height - 1)

    for index, first_route in enumerate(geometry.routes):
        for later, second_route in enumerate(geometry.routes[index + 1:], start=index + 1):
            assert not segment_sets[index].intersection((last, first) for first, last in segment_sets[later])
            if segment_sets[index] & segment_sets[later]:
                assert first_route.edge.source == second_route.edge.source or first_route.edge.target == second_route.edge.target
                assert first_route.edge.style == second_route.edge.style

    styled_rows = list(scene.iter_styled_rows())
    crossings = {(col, row) for row, cells in enumerate(styled_rows)
                 for col, (character, style) in enumerate(cells) if character == 'x' and style == 'edge'}
    endpoints = {route.draw_path[-1] for route in geometry.routes}
    assert crossings
    for col, row in crossings:
        assert min(abs(col - end_col) + abs(row - end_row) for end_col, end_row in endpoints) >= 3
        assert (col + 1, row) not in crossings and (col, row + 1) not in crossings


def test_short_label_can_overhang_its_exclusive_branch_without_overwriting_geometry():
    scene = LayoutScene(20, 5)
    scene.draw_horizontal(3, 2, 17, UNICODE.horizontal)
    route = RoutedEdge(Edge('A', 'B', label='Offload'), draw_path=[(2, 3), (17, 3)],
                       label='Offload', label_paths=[[(10, 3), (13, 3)]])
    label_plan = LabelPlan(scene, 20)
    assert _draw_overhanging_branch_label(label_plan, route, [], max_width=20)
    label_plan.paint(scene)
    assert 'Offload' in scene.to_string()
    assert all(scene.get(3, col) == '─' for col in range(2, 18))
    for row in (0, 1, 2, 4):
        for col in range(20):
            scene.protect(row, col)
    assert not _draw_overhanging_branch_label(LabelPlan(scene, 20), route, [], max_width=20)


def test_explicit_label_limit_without_width_budget_keeps_existing_wrapping():
    source = 'flowchart LR\nA[MasterService] --> B[FileStorage]'
    assert 'MasterService' not in render(source, max_label_width=6)
    assert 'MasterService' in render(source, max_label_width=6, max_width=60)


@pytest.mark.parametrize('vertical', [False, True])
def test_overhanging_label_requires_an_exclusive_clear_anchor(vertical):
    scene = LayoutScene(24, 8)
    if vertical:
        scene.draw_vertical(8, 0, 7, '│')
        route_path = [(8, 0), (8, 7)]
        exclusive_branch = [(8, 3)]
    else:
        scene.draw_horizontal(3, 0, 23, '─')
        route_path = [(0, 3), (23, 3)]
        exclusive_branch = [(8, 3)]
    route = RoutedEdge(Edge('A', 'B'), draw_path=route_path,
                       label='short branch label', label_paths=[exclusive_branch])
    label_plan = LabelPlan(scene, 24)
    assert _draw_overhanging_branch_label(label_plan, route, [], max_width=24)
    label_plan.paint(scene)
    assert all(scene.get(row, col) == ('│' if vertical else '─') for col, row in path_cells(route_path))
    before = scene.to_string()
    route.label_paths = []
    assert not _draw_overhanging_branch_label(LabelPlan(scene, 24), route, [], max_width=24)
    assert scene.to_string() == before


def test_short_horizontal_label_can_use_the_full_gap_between_protected_boxes():
    scene = LayoutScene(16, 6)
    for row in range(6):
        for col in range(16):
            if col < 8 or col > 10:
                scene.protect(row, col)
    scene.draw_horizontal(3, 7, 11, '─')
    route = RoutedEdge(Edge('A', 'B'), draw_path=[(7, 3), (11, 3)],
                       label='yes', label_paths=[[(10, 3)]])
    label_plan = LabelPlan(scene, 16)
    assert _draw_overhanging_branch_label(label_plan, route, [], max_width=16)
    label_plan.paint(scene)
    assert 'yes' in scene.to_string()
    assert all(scene.get(3, col) == '─' for col in range(7, 12))


def test_exclusive_closed_loop_preserves_its_full_label_path():
    scene = LayoutScene(20, 10)
    loop_path = [(5, 1), (12, 1), (12, 7), (5, 7), (5, 1)]
    for first, last in zip(loop_path, loop_path[1:]):
        if first[0] == last[0]:
            scene.draw_vertical(first[0], min(first[1], last[1]), max(first[1], last[1]), '│')
        else:
            scene.draw_horizontal(first[1], min(first[0], last[0]), max(first[0], last[0]), '─')
    route = RoutedEdge(Edge('A', 'A'), draw_path=loop_path, label='loop', label_paths=[loop_path])
    label_plan = LabelPlan(scene, 20)
    assert _draw_edge_label(label_plan, route, [], max_width=20)
    label_plan.paint(scene)
    assert 'loop' in scene.to_string()


def test_label_reservations_cannot_disconnect_an_edge():
    from termaid.layout.grid import compute_layout
    from termaid.routing.router import _route_edge
    graph = parse('flowchart LR\nA --> B')
    layout = compute_layout(graph, max_width=40)
    route = _route_edge(graph.edges[0], layout.placements['A'], layout.placements['B'],
                        layout, graph.direction, set(), reserved_approaches={(3, 1), (1, 3)})
    assert len(route.draw_path) >= 2
    assert all(first[0] == last[0] or first[1] == last[1]
               for first, last in zip(route.draw_path, route.draw_path[1:]))
    assert route.draw_path[0][0] == layout.placements['A'].draw_x + layout.placements['A'].draw_width - 1
    assert route.draw_path[-1][0] == layout.placements['B'].draw_x
