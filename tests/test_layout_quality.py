"""Terminal layout policies, tested by graph meaning and readable geometry."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from termaid import parse
from termaid.cli import main
from termaid.layout.graph_plan import plan_graph
from termaid.layout.grid import GridCoord, GridLayout, NodePlacement
from termaid.layout.layers import assign_layers
from termaid.renderer.draw import render_graph_canvas
from termaid.routing.router import AttachDir, RoutedEdge, _refine_terminal_routes, _separate_label_approaches, path_cells
from termaid.utils import display_width


FIXTURES = Path(__file__).parents[1] / "benchmarks" / "fixtures" / "layout"
SAMPLES = sorted(FIXTURES.glob("*.mmd"))


@pytest.mark.parametrize("direction", ["TB", "BT", "LR", "RL"])
@pytest.mark.parametrize("reverse_declarations", [False, True])
def test_shortcuts_preserve_all_acyclic_dependencies(direction, reverse_declarations):
    declarations = ["A --> D", "A --> B", "B --> C", "C ----> D", "B --> D"]
    source_lines = list(reversed(declarations)) if reverse_declarations else declarations
    graph = parse(f"flowchart {direction}\n" + "\n".join(source_lines))
    original_graph = deepcopy(graph)
    layers = assign_layers(graph)
    for edge in graph.edges:
        assert layers[edge.target] >= layers[edge.source] + edge.min_length
    assert graph == original_graph


def test_control_shortcut_does_not_pull_storage_above_memory():
    graph = parse((FIXTURES / "storage_architecture.mmd").read_text())
    layers = assign_layers(graph)
    assert layers["Client"] < layers["Memory"] < layers["Offload"] < layers["SSD"]
    assert len({layers[node_id] for node_id in ("Memory", "NoF", "DFS", "Disk")}) == 1


def test_control_detour_clears_the_storage_fanout_and_converging_arrivals():
    graph = parse((FIXTURES / "storage_architecture.mmd").read_text())
    geometry = plan_graph(graph, padding_x=1, padding_y=0, gap=2, max_label_width=20)
    routes = {(route.edge.source, route.edge.target): route for route in geometry.routes}
    control = routes[("Master", "Offload")]
    control_cells = set(path_cells(control.draw_path))
    for route in geometry.routes:
        if route is not control:
            assert control_cells.isdisjoint(path_cells(route.draw_path))
    storage_right = max(geometry.layout.placements[node_id].draw_x + geometry.layout.placements[node_id].draw_width
                        for node_id in ("Memory", "NoF", "DFS", "Disk"))
    assert max(col for col, row in control.draw_path) >= storage_right
    application = routes[("App", "Client")]
    client = geometry.layout.placements["Client"]
    assert application.draw_path[1][1] >= client.draw_y
    assert application.draw_path[0][0] == application.draw_path[1][0]
    descriptors = routes[("Master", "Client")]
    assert all(abs(first[0] - last[0]) + abs(first[1] - last[1]) >= 2
               for first, last in zip(descriptors.draw_path[1:-2], descriptors.draw_path[2:-1]))


def test_single_arrival_does_not_force_a_late_bend():
    graph = parse("flowchart TB\nA --> B")
    layout = GridLayout(placements={
        "A": NodePlacement("A", GridCoord(1, 1), draw_x=0, draw_y=0, draw_width=9, draw_height=3),
        "B": NodePlacement("B", GridCoord(5, 5), draw_x=20, draw_y=15, draw_width=9, draw_height=3),
    })
    original_path = [(4, 2), (4, 5), (24, 5), (24, 15)]
    route = RoutedEdge(graph.edges[0], draw_path=list(original_path),
                       start_dir=AttachDir.BOTTOM, end_dir=AttachDir.TOP)
    _refine_terminal_routes([route], graph, layout, set())
    assert route.draw_path == original_path


def test_tiny_dogleg_can_shift_to_a_clear_parallel_lane():
    graph = parse("flowchart TB\nA --> B\nX --> Y")
    layout = GridLayout(placements={
        "A": NodePlacement("A", GridCoord(1, 1), draw_x=0, draw_y=0, draw_width=9, draw_height=3),
        "B": NodePlacement("B", GridCoord(1, 5), draw_x=0, draw_y=12, draw_width=9, draw_height=3),
        "X": NodePlacement("X", GridCoord(5, 1), draw_x=10, draw_y=0, draw_width=9, draw_height=3),
        "Y": NodePlacement("Y", GridCoord(5, 5), draw_x=10, draw_y=12, draw_width=9, draw_height=3),
    })
    cramped = RoutedEdge(graph.edges[0], draw_path=[(4, 2), (4, 8), (5, 8), (5, 12)],
                         start_dir=AttachDir.BOTTOM, end_dir=AttachDir.TOP)
    neighbor = RoutedEdge(graph.edges[1], draw_path=[(14, 2), (14, 12)], index=1,
                          start_dir=AttachDir.BOTTOM, end_dir=AttachDir.TOP)
    _refine_terminal_routes([cramped, neighbor], graph, layout, set())
    assert cramped.draw_path == [(5, 2), (5, 12)]
    assert neighbor.draw_path == [(14, 2), (14, 12)]
    assert set(path_cells(cramped.draw_path)).isdisjoint(path_cells(neighbor.draw_path))


@pytest.mark.parametrize('blocked', [False, True])
def test_turn_can_move_to_leave_a_label_approach_unless_geometry_blocks_it(blocked):
    graph = parse('flowchart TB\nA -->|short| B\nA --> C')
    layout = GridLayout(placements={
        'A': NodePlacement('A', GridCoord(1, 1), draw_x=0, draw_y=0, draw_width=9, draw_height=3),
        'B': NodePlacement('B', GridCoord(1, 5), draw_x=0, draw_y=12, draw_width=9, draw_height=3),
        'C': NodePlacement('C', GridCoord(5, 5), draw_x=16, draw_y=12, draw_width=9, draw_height=3),
    })
    if blocked:
        layout.placements['obstacle'] = NodePlacement('obstacle', GridCoord(3, 3),
                                                     draw_x=10, draw_y=7, draw_width=3, draw_height=4)
    branch = RoutedEdge(graph.edges[0], draw_path=[(4, 2), (4, 12)], label='short')
    detour = RoutedEdge(graph.edges[1], draw_path=[(4, 2), (4, 11), (20, 11), (20, 12)])
    original_path = list(detour.draw_path)
    _separate_label_approaches([branch, detour], graph, layout)
    if blocked:
        assert detour.draw_path == original_path
    else:
        exclusive_cells = set(path_cells(branch.draw_path)) - set(path_cells(detour.draw_path))
        assert {(4, 10), (4, 11)} <= exclusive_cells
        assert len(detour.draw_path) == len(original_path)


@pytest.mark.parametrize('width', [80, 120, 160])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_storage_labels_use_available_space_before_references(width, use_ascii, capsys):
    assert main([str(FIXTURES / 'storage_architecture.mmd'), '--width', str(width), '--strict-width',
                 '--fit-mode', 'reflow', '--padding-x', '2', '--padding-y', '0', '--gap', '2',
                 *(['--ascii'] if use_ascii else [])]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert max(map(display_width, captured.out.splitlines())) <= width
    assert '[1]' not in captured.out


@pytest.mark.parametrize("direction", ["TB", "BT", "LR", "RL"])
def test_collector_and_continuation_align_inside_their_sources(direction):
    source = (FIXTURES / "fan_in.mmd").read_text().replace("flowchart TB", f"flowchart {direction}")
    geometry = plan_graph(parse(source))
    placements = geometry.layout.placements
    horizontal = direction in ("LR", "RL")
    positions = {node_id: placement.grid.row if horizontal else placement.grid.col
                 for node_id, placement in placements.items()}
    assert positions["Collector"] == positions["Database"]
    assert min(positions[name] for name in ("SensorA", "SensorB", "SensorC")) < positions["Collector"]
    assert positions["Collector"] < max(positions[name] for name in ("SensorA", "SensorB", "SensorC"))


@pytest.mark.parametrize("direction", ["TB", "BT", "LR", "RL"])
@pytest.mark.parametrize("use_ascii", [False, True])
def test_bidirectional_fanout_stays_compact_and_preserves_each_arrival(direction, use_ascii):
    source = f"flowchart {direction}\n" + "\n".join(f"Hub <--> N{number}" for number in range(6))
    graph = parse(source)
    geometry = plan_graph(graph, padding_x=1, padding_y=0, gap=2)
    canvas = render_graph_canvas(graph, padding_x=1, padding_y=0, gap=2,
                                 use_ascii=use_ascii, arrow_position="border")
    assert canvas is not None
    heads = ({AttachDir.TOP: "v", AttachDir.BOTTOM: "^", AttachDir.LEFT: ">", AttachDir.RIGHT: "<"}
             if use_ascii else
             {AttachDir.TOP: "▼", AttachDir.BOTTOM: "▲", AttachDir.LEFT: "▶", AttachDir.RIGHT: "◀"})
    for route in geometry.routes:
        start_col, start_row = route.draw_path[0]
        end_col, end_row = route.draw_path[-1]
        assert canvas.get(start_row, start_col) == heads[route.start_dir]
        assert canvas.get(end_row, end_col) == heads[route.end_dir]
    horizontal = direction in ("LR", "RL")
    hub = geometry.layout.placements["Hub"]
    peers = [placement for node_id, placement in geometry.layout.placements.items() if node_id != "Hub"]
    hub_position = hub.grid.row if horizontal else hub.grid.col
    peer_positions = [placement.grid.row if horizontal else placement.grid.col for placement in peers]
    assert min(peer_positions) < hub_position < max(peer_positions)
    assert (geometry.width if horizontal else geometry.height) < 22


@pytest.mark.parametrize("fixture_path", SAMPLES, ids=lambda path: path.stem)
@pytest.mark.parametrize("direction", ["TB", "BT", "LR", "RL"])
def test_classic_routes_clear_unrelated_nodes(fixture_path, direction):
    source = fixture_path.read_text().replace("flowchart TB", f"flowchart {direction}", 1)
    graph = parse(source)
    original_graph = deepcopy(graph)
    geometry = plan_graph(graph, padding_x=1, padding_y=0, gap=2, max_label_width=20)
    assert len(geometry.routes) == len(graph.edges)
    assert graph == original_graph
    for route in geometry.routes:
        cells = set(path_cells(route.draw_path))
        for node_id, placement in geometry.layout.placements.items():
            assert not any(placement.draw_x < col < placement.draw_x + placement.draw_width - 1
                           and placement.draw_y < row < placement.draw_y + placement.draw_height - 1
                           for col, row in cells)
            if node_id in (route.edge.source, route.edge.target):
                continue
            assert not any(placement.draw_x <= col < placement.draw_x + placement.draw_width
                           and placement.draw_y <= row < placement.draw_y + placement.draw_height
                           for col, row in cells)


@pytest.mark.parametrize("fixture_path", SAMPLES, ids=lambda path: path.stem)
@pytest.mark.parametrize("width", [80, 120, 160])
@pytest.mark.parametrize("use_ascii", [False, True])
def test_classic_samples_fit_terminal_without_losing_text(fixture_path, width, use_ascii, capsys):
    graph = parse(fixture_path.read_text())
    assert main([str(fixture_path), "--width", str(width), "--strict-width", "--fit-mode", "reflow",
                 "--padding-x", "1", "--padding-y", "0", "--gap", "2", "--format", "styled-json",
                 *(["--ascii"] if use_ascii else [])]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    lines = ["".join(chunk["text"] for chunk in row) for row in document["lines"]]
    assert max(map(display_width, lines)) <= width
    label_text = " ".join(chunk["text"] for row in document["lines"] for chunk in row
                          if chunk["style"] in ("label", "edge_label"))
    label_words = set(label_text.split())
    for node in graph.nodes.values():
        assert set(node.label.split()) <= label_words
    for edge in graph.edges:
        assert set(edge.label.split()) <= label_words
