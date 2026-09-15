"""Keep state boxes readable before fitting transition labels around routes."""
from collections import Counter
import json
from pathlib import Path

import pytest

from termaid import parse
from termaid.cli import main
from termaid.graph.model import Edge
from termaid.layout.grid import compute_layout
from termaid.renderer.canvas import Canvas
from termaid.renderer.draw import _draw_wrapped_edge_label
from termaid.routing.router import RoutedEdge
from termaid.utils import display_width

FIXTURE = Path(__file__).parent / 'fixtures/production_supervisor_state.mmd'


@pytest.mark.parametrize('width', [68, 85, 100, 120])
def test_supervisor_keeps_node_names_and_nine_transition_labels(width, capsys):
    assert main([str(FIXTURE), '--width', str(width), '--strict-width', '--fit-mode', 'reflow',
                 '--gap', '2', '--padding-x', '2', '--padding-y', '0', '--format', 'styled-json']) == 0
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    output_lines = [''.join(chunk['text'] for chunk in row) for row in document['lines']]
    output = '\n'.join(output_lines)
    assert max(map(display_width, output_lines)) <= width
    assert '[x]' not in output
    assert output.count('[1]') == 2
    assert output.rstrip().endswith('[1] another leader exists')
    # Return text uses the empty left margin. The far-right sentence uses
    # the requested budget, staying on one line when enough space exists.
    return_row = next(line for line in output_lines if 'Standby' in line and '►' in line)
    return_col = return_row.index('╭')
    assert any(line[:return_col].strip() == 'leadership' and line[return_col:return_col + 1] == '│'
               for line in output_lines)
    if width >= 100:
        assert '│leadership monitor reports loss' in output
    elif width == 85:
        assert '│leadership monitor' in output
        assert '│reports loss' in output
    else:
        assert 'leadership monitor reports loss' not in output
    for node_name in ('Starting', 'Standby', 'Candidate', 'LeaderWarmup', 'Recovering', 'Serving'):
        assert node_name in output
    source_graph = parse(FIXTURE.read_text())
    expected_words = Counter(word for edge in source_graph.edges
                             for word in edge.label.split())
    actual_words = Counter(word for row in document['lines'] for chunk in row
                           if chunk['style'] == 'edge_label' for word in chunk['text'].split())
    assert actual_words == expected_words + Counter({'[1]': 2})


def test_fitted_node_layout_does_not_depend_on_transition_sentence_length():
    source_graph = parse(FIXTURE.read_text())
    short_label_graph = parse(FIXTURE.read_text())
    for edge in short_label_graph.edges:
        if edge.label:
            edge.label = 'go'
    source_layout = compute_layout(source_graph, padding_x=0, padding_y=0, gap=1, max_label_width=32)
    short_label_layout = compute_layout(short_label_graph, padding_x=0, padding_y=0, gap=1, max_label_width=32)
    assert source_layout.placements == short_label_layout.placements
    assert source_layout.col_widths == short_label_layout.col_widths
    assert source_layout.row_heights == short_label_layout.row_heights


def test_wrapping_keeps_every_word_and_does_not_erase_lines():
    canvas = Canvas(16, 12)
    for col in (0, 7, 15):
        canvas.draw_vertical(col, 0, 11, '│', style='edge')
    route = RoutedEdge(Edge('A', 'B'), draw_path=[(7, 0), (7, 11)], label='long words stay whole')
    assert _draw_wrapped_edge_label(canvas, route, [], max_width=16)
    for row in range(12):
        assert all(canvas.get(row, col) == '│' for col in (0, 7, 15))
    words = ''.join(canvas.get(row, col) if canvas.get_style(row, col) == 'edge_label' else ' '
                    for row in range(12) for col in range(16)).split()
    assert words == ['long', 'words', 'stay', 'whole']


def test_unbreakable_label_fails_without_partial_writes():
    canvas = Canvas(8, 8)
    canvas.draw_vertical(4, 0, 7, '│', style='edge')
    before = canvas.to_string()
    route = RoutedEdge(Edge('A', 'B'), draw_path=[(4, 0), (4, 7)], label='unbreakable_identifier')
    assert not _draw_wrapped_edge_label(canvas, route, [], max_width=8)
    assert canvas.to_string() == before
