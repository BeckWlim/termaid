"""Regression cases for missing labels and converging directional heads."""
import json
from pathlib import Path

import pytest

from termaid import render, render_rich
from termaid.cli import main
from termaid.output.styled import render_styled
from termaid.utils import display_width

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('output_format', ['text', 'styled-json'])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_compact_labels_have_visible_failure_markers(output_format, use_ascii, capsys):
    arguments = [str(FIXTURES / 'compact_parallel_labels.mmd'), '--width', '85',
                 '--strict-width', '--fit-mode', 'reflow', '--gap', '2',
                 '--padding-x', '2', '--padding-y', '0', '--format', output_format]
    assert main(arguments + (['--ascii'] if use_ascii else [])) == 0
    captured = capsys.readouterr()
    assert not captured.err
    if output_format == 'styled-json':
        document = json.loads(captured.out)
        output = '\n'.join(''.join(chunk['text'] for chunk in row) for row in document['lines'])
        assert all(chunk['style'] == 'edge_label' for row in document['lines']
                   for chunk in row if '[1]' in chunk['text'])
    else:
        output = captured.out
    assert all(output.count(f'[{number}]') == 2 for number in range(1, 6))
    assert all(f'[{number + 1}] operation{number}' in output for number in range(5))
    assert output.count('operation5') == 1
    assert output.count('v' if use_ascii else '▼') == 6
    assert max(map(display_width, output.splitlines())) <= 85
    # Every failed label has a marker in its own clear corridor, on one row.
    assert any(all(f'[{number}]' in line for number in range(1, 6))
               and 'operation5' in line for line in output.splitlines())


@pytest.mark.parametrize('output_format', ['text', 'styled-json'])
@pytest.mark.parametrize('initial_gap', ['1', '8'])
def test_middle_choice_survives_strict_width_fitting(output_format, initial_gap, capsys):
    assert main([str(FIXTURES / 'converging_arrowheads.mmd'), '--width', '25',
                 '--strict-width', '--fit-mode', 'reflow', '--gap', initial_gap,
                 '--padding-x', '4', '--padding-y', '0', '--arrow-position', 'middle',
                 '--format', output_format]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    if output_format == 'styled-json':
        document = json.loads(captured.out)
        output = '\n'.join(''.join(chunk['text'] for chunk in row) for row in document['lines'])
    else:
        output = captured.out
    assert sum(output.count(head) for head in '▶◀▲▼') == 6
    assert 'x' in output and '╳' not in output  # Crossing remains distinguishable from a junction.
    # A better rank/route may recover all labels, or move the reference to
    # another edge. Require complete labels and at most one paired reference.
    assert output.count('[1]') in (0, 2) and '[2]' not in output
    assert all(output.count(f'edge{number:02}') == 1 for number in (1, 2, 3, 5, 6, 7))
    assert max(map(display_width, output.splitlines())) <= 25
    for node_number in range(6):
        assert f'N{node_number}' in output


@pytest.mark.parametrize('direction,head', [('TD', '▼'), ('BT', '▲'), ('LR', '▶'), ('RL', '◀')])
def test_middle_heads_preserve_direction_and_adapter_parity(direction, head):
    source = f'graph {direction}\nA --> B'
    default_output = render(source, gap=8)
    endpoint_output = render(source, gap=8, arrow_position='end')
    middle_output = render(source, gap=8, arrow_position='middle')
    assert default_output == endpoint_output
    assert middle_output != endpoint_output
    assert middle_output.count(head) == 1
    assert render_rich(source, gap=8, arrow_position='middle').plain == middle_output
    styled_document = render_styled(source, gap=8, arrow_position='middle')
    styled_output = '\n'.join(''.join(chunk['text'] for chunk in row) for row in styled_document['lines'])
    assert styled_output == middle_output


@pytest.mark.parametrize('use_ascii', [False, True])
def test_bidirectional_heads_have_distinct_cells(use_ascii):
    output = render('graph LR\nA <--> B', gap=8, arrow_position='middle', use_ascii=use_ascii)
    assert output.count('<' if use_ascii else '◀') == 1
    assert output.count('>' if use_ascii else '▶') == 1


@pytest.mark.parametrize('connection', ['o--o', 'x--x', '---', '~~~'])
def test_non_directional_endpoints_remain_unchanged(connection):
    source = f'graph LR\nA {connection} B'
    assert render(source, arrow_position='middle') == render(source)


def test_successful_label_and_link_style_remain_intact():
    source = 'graph TD\nA -->|complete word| B\nlinkStyle 0 stroke:#ff0000'
    output = render_rich(source, gap=8, arrow_position='middle')
    assert 'complete word' in output.plain and 'x' not in output.plain
    head_offset = output.plain.index('▼')
    assert any(span.start <= head_offset < span.end and '#ff0000' in str(span.style)
               for span in output.spans)


def test_invalid_arrow_position_is_rejected():
    with pytest.raises(ValueError, match='arrow_position'):
        render('graph LR\nA --> B', arrow_position='unknown')


@pytest.mark.parametrize('direction', ['TD', 'BT'])
def test_references_are_numbered_in_source_order_and_listed_below(direction, tmp_path, capsys):
    labels = [f'operation_number{number:02}_requiring_a_reference' for number in range(12)]
    source = f'graph {direction}\n' + '\n'.join(
        f'A{number} -->|{label}| B{number}' for number, label in enumerate(labels)
    )
    source_path = tmp_path / 'references.mmd'
    source_path.write_text(source)
    assert main([str(source_path), '--width', '85', '--strict-width', '--fit-mode', 'reflow',
                 '--gap', '1', '--padding-x', '0', '--padding-y', '0']) == 0
    output = capsys.readouterr().out
    assert max(map(display_width, output.splitlines())) <= 85
    for number, label in enumerate(labels, start=1):
        assert output.count(f'[{number}]') == 2
        assert f'[{number}] {label}' in output
    assert output.rstrip().endswith(f'[12] {labels[-1]}')


def test_reference_list_wraps_without_losing_unicode_text(tmp_path, capsys):
    label = 'abcdefghijklmnopqrstuvwxyz漢字'
    source_path = tmp_path / 'narrow.mmd'
    source_path.write_text(f'graph TD\nA -->|{label}| B')
    assert main([str(source_path), '--width', '12', '--strict-width', '--fit-mode', 'reflow',
                 '--gap', '1', '--padding-x', '0', '--padding-y', '0']) == 0
    output = capsys.readouterr().out
    assert output.count('[1]') == 2
    diagram, footer = output.rstrip().rsplit('\n\n', 1)
    assert '[1]' in diagram
    assert ''.join(line[4:] for line in footer.splitlines()) == label
    assert max(map(display_width, output.splitlines())) <= 12
