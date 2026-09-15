"""Layout invariants shared across editor widths and output adapters."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from termaid import parse
from termaid.cli import main
from termaid.layout.labels import LabelPlan, TextPlacement
from termaid.parser.sequence import parse_sequence_diagram
from termaid.renderer.canvas import Canvas
from termaid.renderer.draw import render_graph_canvas
from termaid.renderer.sequence import render_sequence


FIXTURE = Path(__file__).parent / 'fixtures/production_lease_race.mmd'


def test_replacing_measured_text_does_not_reuse_stale_widths():
    original = TextPlacement('edge:0', 1, 2, ('long text',))
    assert original.width == 9
    changed = replace(original, lines=('界', '🗄x'))
    assert changed.width == 3
    assert set(changed.cells()) == {(1, 2), (1, 3), (2, 2), (2, 3), (2, 4)}
    assert original.width == 9


@pytest.mark.parametrize('character', ['│', '─', '►', 'x', 'existing'])
def test_rejected_label_plan_never_paints_fragments(character: str):
    canvas = Canvas(24, 8)
    canvas.put_text(3, 6, character, style='edge')
    before = canvas.to_string()
    plan = LabelPlan(canvas, 24)
    assert not plan.add(TextPlacement('message:1', 2, 4, ('first', 'second')))
    assert not plan.placements
    assert canvas.to_string() == before


def test_batch_validates_late_geometry_before_painting_any_label():
    canvas = Canvas(24, 8)
    plan = LabelPlan(canvas, 24)
    assert plan.add(TextPlacement('edge:0', 1, 1, ('first',)))
    assert plan.add(TextPlacement('edge:1', 3, 1, ('second',)))
    assert 'first' not in canvas.to_string()
    canvas.put(3, 3, '►', style='arrow')
    before = canvas.to_string()
    with pytest.raises(ValueError, match='edge:1'):
        plan.paint(canvas)
    assert canvas.to_string() == before


@pytest.mark.parametrize('wide_text', ['界', '🗄'])
def test_plans_reserve_spaces_and_wide_character_cells(wide_text: str):
    canvas = Canvas(20, 5)
    canvas.protect(1, 8)
    plan = LabelPlan(canvas, 10)
    assert not plan.add(TextPlacement('protected', 1, 7, (wide_text,)))
    assert not plan.add(TextPlacement('overflow', 2, 9, (wide_text,)))
    assert plan.add(TextPlacement('first', 2, 1, (wide_text + ' gap',)))
    assert not plan.add(TextPlacement('overlap', 2, 3, ('X',)))
    plan.paint(canvas)
    assert wide_text + ' gap' in canvas.to_string()
    assert canvas.get(2, 4) == 'g'


@pytest.mark.parametrize('width', [68, 85, 100, 120, 160])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_lease_race_labels_preserve_all_lifelines_and_message_content(
    width: int, use_ascii: bool, capsys: pytest.CaptureFixture[str],
):
    arguments = [str(FIXTURE), '--width', str(width), '--strict-width', '--fit-mode', 'reflow',
                 '--gap', str(max(1, min(4, width // 40))), '--padding-x', '2',
                 '--padding-y', '0', '--format', 'styled-json']
    if use_ascii:
        arguments.append('--ascii')
    assert main(arguments) == 0
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    rows = document['lines']
    output_lines = [''.join(chunk['text'] for chunk in row) for row in rows]
    lifeline = ':' if use_ascii else '┆'
    centers = [index for index, character in enumerate(output_lines[-1]) if character == lifeline]
    assert len(centers) == 4
    assert max(map(len, output_lines)) <= width
    label_text = []
    arrowheads = 0
    for line, chunks in zip(output_lines, rows):
        arrowheads += sum(len(chunk['text']) for chunk in chunks if chunk['style'] == 'arrow')
        if any(chunk['style'] == 'edge_label' for chunk in chunks):
            assert all(line[column] == lifeline for column in centers)
            assert all(chunk['style'] != 'arrow' for chunk in chunks)
            label_text.extend(chunk['text'] for chunk in chunks if chunk['style'] == 'edge_label')
    diagram = parse_sequence_diagram(FIXTURE.read_text())
    from termaid.model.sequence import Message
    messages = [event for event in diagram.events if isinstance(event, Message)]
    assert arrowheads == len(messages)
    assert ''.join(''.join(label_text).split()) == ''.join(
        ''.join(message.label.split()) for message in messages
    )


def test_sequence_rendering_keeps_original_text_across_widths():
    source = '''sequenceDiagram
participant A
participant B
participant C
alt a long scope heading whose text must survive repeated layouts
A->>C: CreateWithLease(master_view, A, lease A)
else another condition with a visible ending
C->>A: restore the complete original message
end'''
    diagram = parse_sequence_diagram(source)
    original = deepcopy(diagram)
    for label_width in (8, 24, 8, 40):
        actual = render_sequence(diagram, max_label_width=label_width).to_string()
        expected = render_sequence(parse_sequence_diagram(source), max_label_width=label_width).to_string()
        assert actual == expected
        assert diagram == original


@pytest.mark.parametrize('direction', ['TD', 'LR', 'BT', 'RL'])
def test_graph_rendering_keeps_original_labels_and_direction(direction: str):
    source = f'graph {direction}\nA[long original node label] -->|return value| B[other node]'
    graph = parse(source)
    original_description = repr(graph)
    for label_width in (5, 20, 5):
        canvas = render_graph_canvas(graph, max_label_width=label_width)
        fresh_canvas = render_graph_canvas(parse(source), max_label_width=label_width)
        assert canvas is not None and fresh_canvas is not None
        assert canvas.to_string() == fresh_canvas.to_string()
        assert repr(graph) == original_description
