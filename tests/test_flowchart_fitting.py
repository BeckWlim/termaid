"""Width budgets must preserve readable nodes, branches, and edge labels."""
from pathlib import Path
import json

import pytest

from termaid.cli import main
from termaid.layout.grid import compute_layout
from termaid.parser.flowchart import parse_flowchart
from termaid.renderer.canvas import Canvas
from termaid.renderer.draw import _try_place_label
from termaid.routing.router import route_edges
from termaid.utils import display_width


FIXTURE = Path(__file__).parent / "fixtures" / "production_architecture.mmd"


@pytest.mark.parametrize("width", [60, 80, 85, 100, 120, 160])
@pytest.mark.parametrize("output_format", ["text", "styled-json"])
def test_architecture_fits_without_losing_arrows_or_labels(width, output_format, capsys):
    result = main([
        str(FIXTURE), "--width", str(width), "--strict-width",
        "--fit-mode", "reflow", "--gap", "2", "--padding-x", "2",
        "--padding-y", "0", "--uniform-nodes", "--format", output_format,
    ])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    if output_format == "styled-json":
        document = json.loads(captured.out)
        rendered_lines = ["".join(chunk["text"] for chunk in line) for line in document["lines"]]
        output_text = "\n".join(rendered_lines)
    else:
        output_text = captured.out
    assert max(map(display_width, output_text.splitlines())) <= width
    assert output_text.count("▼") == 11
    assert output_text.count("▶") == 1
    # Each branch retains its label; narrow corridors may wrap it.
    assert output_text.count("Object") == 3 and output_text.count("bytes") == 3
    assert output_text.count("Replica descriptors") == 1
    assert "┼" not in output_text
    if width >= 80:
        assert "Application" in output_text
        assert display_width(output_text.splitlines()[0].lstrip()) >= 13
    if width >= 85:
        assert "MasterClient" in output_text
        assert "MasterService" in output_text


@pytest.mark.parametrize("direction", ["TD", "LR"])
@pytest.mark.parametrize("labelled", [False, True])
def test_siblings_share_one_forward_branch(direction, labelled):
    source = (f"graph {direction}\nA --> B\nA -->|memory| C\nA -->|disk| D\nA -->|network| E"
              if labelled else f"graph {direction}\nA --> B\nA --> C\nA --> D\nA --> E")
    graph = parse_flowchart(source)
    layout = compute_layout(graph, padding_x=0, padding_y=0, gap=2)
    routed = route_edges(graph, layout)
    assert len(routed) == 4
    assert len({tuple(edge.draw_path[0]) for edge in routed}) == 1
    branch_axes = set()
    for edge in routed:
        for start, end in zip(edge.draw_path, edge.draw_path[1:]):
            if direction == "TD" and start[0] != end[0]:
                assert start[1] == end[1]
                branch_axes.add(start[1])
            elif direction == "LR" and start[1] != end[1]:
                assert start[0] == end[0]
                branch_axes.add(start[0])
    assert len(branch_axes) == 1


@pytest.mark.parametrize("character", ["│", "─", "┼", "▼", "◀", "X"])
def test_labels_cannot_erase_connectors_or_existing_text(character):
    canvas = Canvas(20, 3)
    canvas.put(1, 5, character, style="edge")
    assert not _try_place_label(canvas, 1, 3, "message", [])
    assert canvas.get(1, 5) == character


@pytest.mark.parametrize("direction", ["TD", "LR"])
def test_uniform_boxes_are_sized_before_routing(direction):
    graph = parse_flowchart(
        f"graph {direction}\nA[Application] --> B[Long client label]\n"
        "B --> C[Short]\nB --> D[Several words in this node]"
    )
    layout = compute_layout(graph, padding_x=0, padding_y=0, gap=2,
                            max_label_width=12, uniform_nodes=True)
    dimensions = {(node.draw_width, node.draw_height) for node in layout.placements.values()}
    assert len(dimensions) == 1
    for edge in route_edges(graph, layout):
        target = layout.placements[edge.edge.target]
        endpoint_col, endpoint_row = edge.draw_path[-1]
        assert target.draw_x <= endpoint_col < target.draw_x + target.draw_width
        assert target.draw_y <= endpoint_row < target.draw_y + target.draw_height


def test_labels_do_not_occupy_empty_node_cells():
    canvas = Canvas(20, 3)
    canvas.protect(1, 5)
    assert not _try_place_label(canvas, 1, 3, "message", [])
    assert canvas.get(1, 5) == " "


def test_uniform_rich_output_matches_plain_geometry():
    from termaid import render, render_rich

    source = FIXTURE.read_text()
    plain_output = render(source, max_label_width=17, uniform_nodes=True, gap=1, padding_x=0, padding_y=0)
    rich_output = render_rich(source, max_label_width=17, uniform_nodes=True, gap=1, padding_x=0, padding_y=0)
    assert rich_output.plain == plain_output


@pytest.mark.parametrize("direction", ["TD", "LR"])
def test_return_uses_outer_lane_without_crossing_forward_branches(direction):
    source_text = FIXTURE.read_text().replace("flowchart TD", "flowchart " + direction)
    graph = parse_flowchart(source_text)
    layout = compute_layout(graph, padding_x=0, padding_y=0, gap=1,
                            max_label_width=15, uniform_nodes=True)
    routes = route_edges(graph, layout)
    return_route = next(route for route in routes if route.edge.label == "Replica descriptors")
    assert all(col >= 0 and row >= 0 for col, row in return_route.draw_path)
    for route in routes:
        if route is not return_route:
            assert not (return_route.occupied_cells & route.occupied_cells)
    # Either outer side is valid; the return must remain outside the blocks.
    horizontal = direction == "LR"
    lower_bound = min(node.draw_y if horizontal else node.draw_x for node in layout.placements.values())
    upper_bound = max(node.draw_y + node.draw_height if horizontal else node.draw_x + node.draw_width
                      for node in layout.placements.values())
    assert any((row if horizontal else col) < lower_bound or (row if horizontal else col) >= upper_bound
               for col, row in return_route.draw_path)
    assert [route.index for route in routes] == list(range(len(graph.edges)))


def test_no_return_needs_no_left_margin():
    graph = parse_flowchart("graph TD\nA --> B\nA --> C")
    layout = compute_layout(graph)
    assert min(node.draw_x for node in layout.placements.values()) == 0


@pytest.mark.parametrize("ascii_output,marker", [(False, "x"), (True, "x")])
def test_unrelated_crossing_differs_from_shared_junction(ascii_output, marker):
    from termaid.graph.model import Edge
    from termaid.renderer.charset import ASCII, UNICODE
    from termaid.renderer.draw import _draw_edges
    from termaid.routing.router import RoutedEdge

    graph = parse_flowchart("graph TD\nA --> B\nC --> D")
    crossing_routes = [
        RoutedEdge(edge=graph.edges[0], draw_path=[(0, 3), (6, 3)]),
        RoutedEdge(edge=graph.edges[1], draw_path=[(3, 0), (3, 6)]),
    ]
    canvas = Canvas(7, 7)
    charset = ASCII if ascii_output else UNICODE
    _draw_edges(canvas, graph, compute_layout(graph), crossing_routes, charset)
    assert canvas.get(3, 3) == marker
    assert canvas.get(3, 5) == charset.arrow_right
    assert canvas.get(5, 3) == charset.arrow_down

    shared_routes = [
        crossing_routes[0],
        RoutedEdge(edge=Edge("A", "D"), draw_path=[(0, 3), (3, 3), (3, 6)]),
    ]
    shared_canvas = Canvas(7, 7)
    _draw_edges(shared_canvas, graph, compute_layout(graph), shared_routes, charset)
    assert shared_canvas.get(3, 3) == charset.tee_down
    assert marker not in shared_canvas.to_string()


def test_crossing_marker_survives_semantic_output():
    from termaid.output.styled import render_styled

    source = (FIXTURE.parent / "flowcharts" / "large_graph.mmd").read_text()
    document = render_styled(source)
    crossing_chunks = [chunk for line in document["lines"] for chunk in line if "x" in chunk["text"]]
    assert crossing_chunks
    assert all(chunk["style"] == "edge" for chunk in crossing_chunks)
