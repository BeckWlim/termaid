"""Geometry and public rendering coverage for layered architecture diagrams."""
from pathlib import Path

import pytest

from termaid import render
from termaid.cli import main
from termaid.graph.model import ArrowType, Edge, EdgeStyle
from termaid.layout.grid import GridLayout, compute_layout
from termaid.parser.flowchart import parse_flowchart
from termaid.renderer.canvas import Canvas
from termaid.renderer.charset import ASCII, UNICODE
from termaid.renderer.draw import _draw_crossings, _draw_edges
from termaid.routing.router import RoutedEdge, _route_sibling_branches, path_cells, route_edges
from termaid.utils import display_width

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('declaration', ['Storage[Storage resources]', 'Storage [Storage resources]',
                                         'Storage["Storage resources"]'])
@pytest.mark.parametrize('reference_first', [False, True])
def test_compact_subgraph_resolves_references(declaration, reference_first):
    group = f'subgraph Outer[Outer group]\nsubgraph {declaration}\ndirection LR\nMemory[MEMORY]\nend\nend\n'
    edge = 'Master --> Storage\n'
    graph = parse_flowchart('flowchart TB\n' + (edge + group if reference_first else group + edge))
    storage = graph.find_subgraph_by_id('Storage')
    assert storage is not None and storage.label == 'Storage resources'
    assert storage.parent.id == 'Outer' and storage.direction.value == 'LR'
    assert 'Storage' not in graph.nodes
    assert graph.edges[0].target_is_subgraph
    layout = compute_layout(graph)
    route = route_edges(graph, layout)[0]
    bounds = next(bounds for bounds in layout.subgraph_bounds if bounds.subgraph.id == 'Storage')
    x, y = route.draw_path[-1]
    assert x in (bounds.x, bounds.x + bounds.width - 1) or y in (bounds.y, bounds.y + bounds.height - 1)


@pytest.mark.parametrize('tag', ['<br>', '<br/>', '<br />', '<BR/>'])
def test_label_breaks_are_measured_before_rendering(tag):
    source = f'flowchart TB\nA["内存{tag}MEMORY"] -->|read{tag}write| B["`**Disk**{tag}*SSD*`"]'
    graph = parse_flowchart(source)
    assert graph.nodes['A'].label == '内存\nMEMORY'
    assert graph.nodes['B'].label == 'Disk\nSSD'
    assert ''.join(segment.text for segment in graph.nodes['B'].label_segments) == 'Disk\nSSD'
    assert graph.edges[0].label == 'read\nwrite'
    layout = compute_layout(graph, padding_y=0)
    assert layout.placements['A'].draw_height >= 4
    output = render(source, padding_y=0, gap=8)
    assert '<br' not in output.lower()
    for label in ('内存', 'MEMORY', 'Disk', 'SSD', 'read', 'write'):
        assert label in output
    assert not any('read' in line and 'write' in line for line in output.splitlines())


def test_multiline_group_title_and_literal_markup():
    source = 'flowchart TB\nsubgraph G["Storage<br/>resources"]\nA["literal <b>text</b>"]\nend'
    graph = parse_flowchart(source)
    assert graph.subgraphs[0].label == 'Storage\nresources'
    output = render(source)
    assert 'literal <b>text</b>' in output
    assert output.index('Storage') < output.index('resources') < output.index('literal')


@pytest.mark.parametrize('charset', [UNICODE, ASCII])
@pytest.mark.parametrize('endpoints,first_path,second_path', [
    (('A', 'B', 'C', 'D'), [(0, 3), (6, 3)], [(3, 0), (3, 6)]),
    (('S', 'A', 'S', 'B'), [(0, 0), (0, 3), (6, 3)], [(0, 0), (3, 0), (3, 6)]),
    (('A', 'T', 'B', 'T'), [(0, 3), (6, 3), (6, 6)], [(3, 0), (3, 6), (6, 6)]),
])
def test_crossings_use_local_topology(charset, endpoints, first_path, second_path):
    canvas = Canvas(7, 7)
    canvas.put(3, 3, '+')
    routes = [RoutedEdge(Edge(*endpoints[:2]), draw_path=first_path),
              RoutedEdge(Edge(*endpoints[2:]), draw_path=second_path)]
    _draw_crossings(canvas, routes, charset)
    assert canvas.get(3, 3) == charset.unconnected_crossing


def test_shared_trunk_and_third_owner():
    routes = [
        RoutedEdge(Edge('S', 'A'), draw_path=[(3, 0), (3, 3), (0, 3)]),
        RoutedEdge(Edge('S', 'B'), draw_path=[(3, 0), (3, 3), (6, 3)]),
        RoutedEdge(Edge('S', 'C'), draw_path=[(3, 0), (3, 6)]),
    ]
    canvas = Canvas(7, 7)
    canvas.put(3, 3, '┼')
    _draw_crossings(canvas, routes, UNICODE)
    assert canvas.get(3, 3) == '┼'
    routes.append(RoutedEdge(Edge('X', 'Y'), draw_path=[(0, 3), (6, 3)]))
    _draw_crossings(canvas, routes, UNICODE)
    assert canvas.get(3, 3) == 'x'


@pytest.mark.parametrize('charset', [UNICODE, ASCII])
def test_shared_origin_codirectional_overlap_needs_no_crossing(charset):
    routes = [RoutedEdge(Edge('A', 'B'), draw_path=[(0, 3), (8, 3)]),
              RoutedEdge(Edge('A', 'D'), draw_path=[(0, 3), (6, 3), (6, 6)])]
    canvas = Canvas(9, 7)
    for col in range(2, 7):
        canvas.put(3, col, charset.horizontal)
    _draw_crossings(canvas, routes, charset)
    assert 'x' not in canvas.to_string()


@pytest.mark.parametrize('marker', [ArrowType.ARROW, ArrowType.CROSS, ArrowType.CIRCLE])
def test_crossing_survives_endpoint_marker_and_label(marker):
    graph = parse_flowchart('flowchart TB\nA --> B\nC --> D')
    graph.edges[0].arrow_type_end = marker
    routes = [RoutedEdge(graph.edges[0], draw_path=[(0, 3), (4, 3)], label='label'),
              RoutedEdge(graph.edges[1], draw_path=[(3, 0), (3, 6)], index=1)]
    canvas = Canvas(15, 8)
    _draw_edges(canvas, graph, GridLayout(), routes, UNICODE, inline_edge_labels=True)
    assert canvas.get(3, 3) == 'x'
    expected = {ArrowType.ARROW: '▶', ArrowType.CROSS: '×', ArrowType.CIRCLE: '○'}[marker]
    assert expected in canvas.to_string()
    assert '▼' in canvas.to_string()


@pytest.mark.parametrize('direction', ['TB', 'BT', 'LR', 'RL'])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('reciprocal', [False, True])
def test_parallel_and_opposite_routes_have_separate_lanes(direction, compact, reciprocal):
    final_edge = 'B -->|reply| A' if reciprocal else 'A <-->|third| B'
    source = f'flowchart {direction}\nA -->|first| B\nA -.->|second| B\n{final_edge}'
    graph = parse_flowchart(source)
    layout = compute_layout(graph, padding_y=0 if compact else 2, gap=1 if compact else 8)
    routes = route_edges(graph, layout)
    owned_cells = [set(path_cells(route.draw_path)) for route in routes]
    assert all(not first.intersection(second) for index, first in enumerate(owned_cells)
               for second in owned_cells[index + 1:])
    for route in routes:
        assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(route.draw_path, route.draw_path[1:]))
    output = render(source, padding_y=0 if compact else 2, gap=1 if compact else 8)
    assert output == render(source, padding_y=0 if compact else 2, gap=1 if compact else 8)
    assert sum(output.count(head) for head in '▶◀▲▼') == (3 if reciprocal else 4)
    for label in ('first', 'second', 'reply' if reciprocal else 'third'):
        assert label in output


def test_subgraph_storage_fanout_uses_shared_bus_and_clears_titles():
    graph = parse_flowchart((FIXTURES / 'mooncake_store.mmd').read_text())
    layout = compute_layout(graph)
    branches = _route_sibling_branches(graph, layout)
    assert set(branches) == {3, 4, 5, 6, 7}
    common_cells = set.intersection(*(set(path_cells(route.draw_path)) for route in branches.values()))
    assert len(common_cells) >= 2
    for bounds in layout.subgraph_bounds:
        title_cells = {(col, bounds.y + 1 + offset)
                       for offset, line in enumerate(bounds.subgraph.label.split('\n'))
                       for col in range(bounds.x + 2, bounds.x + 2 + display_width(line))}
        assert all(not title_cells.intersection(path_cells(route.draw_path)) for route in route_edges(graph, layout))


@pytest.mark.parametrize('direction', ['TB', 'BT', 'LR', 'RL'])
@pytest.mark.parametrize('use_ascii', [False, True])
@pytest.mark.parametrize('gap', [1, 8])
def test_architecture_public_render_matrix(direction, use_ascii, gap):
    source = (FIXTURES / 'mooncake_store.mmd').read_text().replace('flowchart TB', f'flowchart {direction}')
    output = render(source, use_ascii=use_ascii, gap=gap, padding_y=0, max_width=85, max_label_width=16)
    assert '<br' not in output
    assert all(word in output for word in ('Application', 'MasterService', 'MEMORY', 'NOF_SSD', 'LOCAL_DISK', 'DFS'))
    if not use_ascii:
        assert sum(output.count(head) for head in '▶◀▲▼') == 10


@pytest.mark.parametrize('use_ascii', [False, True])
def test_narrow_cli_preserves_parallel_labels(tmp_path, capsys, use_ascii):
    source_path = tmp_path / 'parallel.mmd'
    source_path.write_text('flowchart TB\nA -->|request| B\nB -->|response| A')
    assert main([str(source_path), '--width', '35', '--strict-width', '--fit-mode', 'reflow',
                 *(['--ascii'] if use_ascii else [])]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert max(map(display_width, captured.out.splitlines())) <= 35
    assert 'request' in captured.out and 'response' in captured.out


@pytest.mark.parametrize('use_ascii', [False, True])
def test_architecture_reviewed_snapshot(use_ascii):
    source = (FIXTURES / 'mooncake_store.mmd').read_text()
    output = render(source, use_ascii=use_ascii, padding_x=2, padding_y=0, gap=4, max_label_width=16, max_width=120)
    snapshot_path = FIXTURES / ('mooncake_store_ascii.snap' if use_ascii else 'mooncake_store.snap')
    assert output + '\n' == snapshot_path.read_text()


@pytest.mark.parametrize('direction', ['TB', 'BT', 'LR', 'RL'])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_border_heads_occupy_the_actual_target_border(direction, use_ascii):
    from termaid.layout.graph_plan import plan_graph
    from termaid.renderer.draw import render_graph_canvas
    graph = parse_flowchart(f'flowchart {direction}\nA[Source] --> B[Target]')
    geometry = plan_graph(graph, gap=4)
    scene = render_graph_canvas(graph, gap=4, use_ascii=use_ascii, arrow_position='border')
    route = geometry.routes[0]
    col, row = route.draw_path[-1]
    charset = ASCII if use_ascii else UNICODE
    expected = {'TB': charset.arrow_down, 'BT': charset.arrow_up,
                'LR': charset.arrow_right, 'RL': charset.arrow_left}[direction]
    assert scene.get(row, col) == expected
    before_col, before_row = list(path_cells(route.draw_path))[-2]
    assert scene.get(before_row, before_col) in '-|─│'
    assert 'Target' in scene.to_string()


def test_border_heads_preserve_distinct_shape_markers():
    output = render('flowchart TB\nA --> B{Choice}', arrow_position='border')
    assert '◇' in output and '▼' in output
    scene = Canvas(5, 3)
    scene.put(1, 2, '◆')
    scene.protect(1, 2)
    assert not scene.put_border_marker(1, 2, '▼')
    assert scene.get(1, 2) == '◆'


def test_border_heads_cli_and_adapter_parity(tmp_path, capsys):
    from termaid import plan
    source = 'flowchart LR\nA <--> B'
    diagram_plan = plan(source, arrow_position='border')
    assert diagram_plan.to_string() == diagram_plan.to_rich().plain
    assert diagram_plan.to_string().count('▶') == 1
    assert diagram_plan.to_string().count('◀') == 1
    source_path = tmp_path / 'border.mmd'
    source_path.write_text(source)
    assert main([str(source_path), '--arrow-position', 'border']) == 0
    assert capsys.readouterr().out.rstrip('\n') == diagram_plan.to_string()


def test_markdown_breaks_keep_styles_and_unmatched_asterisks():
    from termaid import plan
    diagram_plan = plan('flowchart TB\nA["`**Memory**<br/>*Disk*<br/>literal*`"]')
    styled_rows = diagram_plan.to_styled()['lines']
    assert any(chunk['text'] == 'Memory' and chunk['style'] == 'bold_label' for row in styled_rows for chunk in row)
    assert any(chunk['text'] == 'Disk' and chunk['style'] == 'italic_label' for row in styled_rows for chunk in row)
    assert 'literal*' in diagram_plan.to_string()


@pytest.mark.parametrize('direction', ['TB', 'BT', 'LR', 'RL'])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_default_heads_touch_both_block_borders(direction, use_ascii):
    from termaid.layout.graph_plan import plan_graph
    from termaid.renderer.draw import render_graph_canvas
    graph = parse_flowchart(f'flowchart {direction}\nA[Source] <--> B[Target]')
    geometry = plan_graph(graph, gap=4)
    scene = render_graph_canvas(graph, gap=4, use_ascii=use_ascii)
    cells = list(path_cells(geometry.routes[0].draw_path))
    charset = ASCII if use_ascii else UNICODE
    start_head, end_head, connector = {
        'TB': (charset.arrow_up, charset.arrow_down, charset.vertical),
        'BT': (charset.arrow_down, charset.arrow_up, charset.vertical),
        'LR': (charset.arrow_left, charset.arrow_right, charset.horizontal),
        'RL': (charset.arrow_right, charset.arrow_left, charset.horizontal),
    }[direction]
    for cell, expected in ((cells[0], start_head), (cells[-1], end_head)):
        assert scene.get(cell[1], cell[0]) == expected
    for col, row in (cells[1], cells[-2]):
        assert scene.get(row, col) == connector
    assert scene.to_string() == render(f'flowchart {direction}\nA[Source] <--> B[Target]', gap=4, use_ascii=use_ascii, arrow_position='border')


def test_unicode_arrowheads_are_one_triangle_family():
    import unicodedata
    for head in (UNICODE.arrow_up, UNICODE.arrow_right, UNICODE.arrow_down, UNICODE.arrow_left):
        assert unicodedata.name(head).endswith('POINTING TRIANGLE')
        assert display_width(head) == 1


def test_endpoint_fallback_preserves_adjacent_corner():
    from termaid.renderer.draw import _draw_endpoint_marker
    route = RoutedEdge(Edge('A', 'B'), draw_path=[(0, 2), (4, 2), (4, 3)])
    scene = Canvas(7, 5)
    scene.draw_horizontal(2, 0, 3, '─')
    scene.put(2, 4, '╮')
    scene.put(3, 4, '◇')
    scene.protect(3, 4)
    _draw_endpoint_marker(scene, route, UNICODE, reverse=False, style='arrow',
                          arrow_type=ArrowType.ARROW, on_border=True)
    assert scene.get(2, 4) == '╮'
    assert scene.get(3, 4) == '◇'
    assert scene.get(2, 3) == '▶'


@pytest.mark.parametrize('direction', ['TB', 'BT', 'LR', 'RL'])
@pytest.mark.parametrize('label', ['', '|copy|'])
def test_identical_edges_reuse_head_without_removing_model_edges(direction, label):
    from termaid.layout.graph_plan import plan_graph
    source = f'flowchart {direction}\nA -->{label} B\nA -->{label} B'
    graph = parse_flowchart(source)
    geometry = plan_graph(graph)
    assert len(graph.edges) == len(geometry.routes) == 2
    assert set(geometry.layout.placements) == {'A', 'B'}
    assert geometry.routes[0].draw_path == geometry.routes[1].draw_path
    output = render(source)
    assert sum(output.count(head) for head in '▶◀▲▼') == 1
    if label:
        assert output.count('copy') == 1


@pytest.mark.parametrize('direction', ['TB', 'BT', 'LR', 'RL'])
def test_shared_destination_keeps_visible_arrivals(direction):
    from termaid.layout.graph_plan import plan_graph
    from termaid.renderer.draw import render_graph_canvas
    from termaid.routing.router import AttachDir
    source = f'flowchart {direction}\nA --> C\nB --> C'
    graph = parse_flowchart(source)
    geometry = plan_graph(graph)
    assert len(geometry.routes) == 2
    canvas = render_graph_canvas(graph, arrow_position='border')
    assert canvas is not None
    target = geometry.layout.placements['C']
    arrival_heads = {AttachDir.TOP: '▼', AttachDir.BOTTOM: '▲',
                     AttachDir.LEFT: '▶', AttachDir.RIGHT: '◀'}
    for route in geometry.routes:
        assert route.edge.target == 'C'
        col, row = route.draw_path[-1]
        assert target.draw_x <= col < target.draw_x + target.draw_width
        assert target.draw_y <= row < target.draw_y + target.draw_height
        assert col in (target.draw_x, target.draw_x + target.draw_width - 1) or row in (
            target.draw_y, target.draw_y + target.draw_height - 1)
        assert canvas.get(row, col) == arrival_heads[route.end_dir]


@pytest.mark.parametrize('use_ascii', [False, True])
def test_copy_pipeline_keeps_branch_labels_and_early_bends(use_ascii, capsys):
    from termaid.layout.graph_plan import plan_graph
    source = (FIXTURES / 'copy_pipeline.mmd').read_text()
    graph = parse_flowchart(source)
    geometry = plan_graph(graph, padding_x=1, padding_y=0, gap=2, max_label_width=8)
    assert len(geometry.routes) == len(graph.edges) == 26
    assert set(geometry.layout.placements) == set(graph.nodes)
    branches = [route for route in geometry.routes if route.edge.source == 'Ready']
    for route in branches:
        assert abs(route.draw_path[-1][1] - route.draw_path[-2][1]) >= 3
    sibling_routes = _route_sibling_branches(graph, geometry.layout)
    rail_cells = set().union(*(set(path_cells(route.draw_path)) for route in sibling_routes.values()
                               if route.edge.source == 'Transport'))
    policy_cells = set().union(*(set(path_cells(route.draw_path)) for route in sibling_routes.values()
                                 if route.edge.source == 'Policy'))
    # Independent buses may cross at a cell, but cannot share a segment.
    shared_cells = rail_cells & policy_cells
    assert not any((col + 1, row) in shared_cells or (col, row + 1) in shared_cells
                   for col, row in shared_cells)
    assert main([str(FIXTURES / 'copy_pipeline.mmd'), '--width', '85', '--strict-width',
                 '--fit-mode', 'reflow', '--padding-y', '0', '--gap', '2',
                 *(['--ascii'] if use_ascii else [])]) == 0
    output = capsys.readouterr().out
    assert '[1]' not in output
    assert all(output.count(label) == 1 for label in ('hit', 'miss', 'yes', 'no'))
    assert max(map(display_width, output.splitlines())) <= 85
