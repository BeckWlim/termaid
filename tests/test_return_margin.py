"""Reserve return corridors only where routes need them, and fit vertical reflow."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from termaid import parse
from termaid.cli import main
from termaid.layout.engine import plan
from termaid.layout.graph_plan import plan_graph
from termaid.layout.grid import GridCoord, GridLayout, NodePlacement
from termaid.layout.placement import reserve_return_margin
from termaid.routing.router import path_cells
from termaid.utils import display_width


FIXTURE = Path(__file__).parent / 'fixtures' / 'production_ha_components.mmd'


@pytest.mark.parametrize('direction', ['TB', 'LR'])
@pytest.mark.parametrize('intervening_node', [False, True])
def test_reciprocal_pair_needs_an_outer_lane_only_when_its_corridor_is_blocked(direction, intervening_node):
    graph = parse(f'flowchart {direction}\nA --> B\nB -->|return| A\nX')
    horizontal = direction == 'LR'
    layout = GridLayout(placements={
        'A': NodePlacement('A', GridCoord(1, 1)),
        'B': NodePlacement('B', GridCoord(9, 1) if horizontal else GridCoord(1, 9)),
        'X': NodePlacement('X', (GridCoord(5, 1) if horizontal else GridCoord(1, 5))
                           if intervening_node else GridCoord(5, 5)),
    })
    reserve_return_margin(graph, layout, max_label_width=24)
    first_position = layout.placements['A'].grid.row if horizontal else layout.placements['A'].grid.col
    assert (first_position > 1) == intervening_node


def test_long_cycle_keeps_a_return_corridor():
    graph = parse('flowchart TB\nA --> B\nB --> C\nC -->|retry| A')
    geometry = plan_graph(graph, padding_x=0, padding_y=0, gap=1, max_label_width=24, max_width=80)
    return_route = next(route for route in geometry.routes if route.edge.source == 'C')
    first_node_col = min(placement.draw_x for placement in geometry.layout.placements.values())
    assert any(col < first_node_col for col, row in return_route.draw_path)


@pytest.mark.parametrize('width', [80, 101, 130])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_ha_reflow_fits_without_an_unused_return_margin(width, use_ascii, capsys):
    with patch('termaid.layout.engine.plan', wraps=plan) as measured_plan:
        status = main([str(FIXTURE), '--width', str(width), '--strict-width', '--fit-mode', 'reflow',
                       '--gap', '2', '--padding-x', '2', '--padding-y', '0', '--format', 'styled-json',
                       *(['--ascii'] if use_ascii else [])])
    captured = capsys.readouterr()
    assert status == 0 and not captured.err
    assert measured_plan.call_count <= 8
    document = json.loads(captured.out)
    lines = [''.join(chunk['text'] for chunk in row) for row in document['lines']]
    assert max(map(display_width, lines)) <= width
    assert lines[0] == lines[0].lstrip()
    label_words = {word for row in document['lines'] for chunk in row
                   if chunk['style'] == 'edge_label' for word in chunk['text'].split()}
    source_graph = parse(FIXTURE.read_text())
    for edge in source_graph.edges:
        assert set(edge.label.split()) <= label_words


def test_vertical_column_allocation_preserves_nodes_edges_and_input():
    graph = parse(FIXTURE.read_text().replace('flowchart LR', 'flowchart TB'))
    original_graph = deepcopy(graph)
    geometry = plan_graph(graph, max_width=101, max_label_width=64, padding_x=0, padding_y=0, gap=1)
    assert graph == original_graph
    assert len(geometry.routes) == len(graph.edges)
    assert min(placement.draw_x for placement in geometry.layout.placements.values()) == 0
    for node_id, node in geometry.graph.nodes.items():
        assert ''.join(node.label.replace('\\n', '').split()) == ''.join(graph.nodes[node_id].label.split())
    for route in geometry.routes:
        for col, row in path_cells(route.draw_path):
            for node_id, placement in geometry.layout.placements.items():
                assert not (placement.draw_x < col < placement.draw_x + placement.draw_width - 1
                            and placement.draw_y < row < placement.draw_y + placement.draw_height - 1)
                if node_id not in (route.edge.source, route.edge.target):
                    assert not (placement.draw_x <= col < placement.draw_x + placement.draw_width
                                and placement.draw_y <= row < placement.draw_y + placement.draw_height)
