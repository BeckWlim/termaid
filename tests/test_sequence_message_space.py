"""Sequence annotations use available space without erasing unrelated lifelines."""
import pytest

from termaid.model.sequence import Block, Message
from termaid.parser.sequence import parse_sequence_diagram
from termaid.renderer.sequence import render_sequence
from termaid.utils import display_width


@pytest.mark.parametrize('use_ascii', [False, True])
def test_scope_hint_preserves_lifelines_beyond_its_text(use_ascii):
    diagram = parse_sequence_diagram('''sequenceDiagram
participant A
participant B
participant C
participant D
par hint
A->>D: go
end''')
    canvas = render_sequence(diagram, use_ascii=use_ascii)
    lines = canvas.to_string().splitlines()
    heading_row = next(index for index, line in enumerate(lines) if '[par] hint' in line)
    centers = [lines[1].index(name) for name in 'ABCD']
    for center in centers[1:]:
        assert canvas.get(heading_row, center) == (':' if use_ascii else '┆')
    assert '[par] hint' in lines[heading_row]


@pytest.mark.parametrize('section', [False, True])
def test_multiline_hints_only_clear_their_own_text(section):
    diagram = parse_sequence_diagram('''sequenceDiagram
participant A
participant B
participant C
participant D
par hint
A->>D: go
and branch
D->>A: back
end''')
    scope = diagram.events[0]
    assert isinstance(scope, Block)
    if section:
        scope.sections[0].label = 'branch\nnext'
    else:
        scope.label = 'hint\nnext'
    canvas = render_sequence(diagram)
    lines = canvas.to_string().splitlines()
    continuation_row = next(index for index, line in enumerate(lines) if 'next' in line)
    centers = [lines[1].index(name) for name in 'ABCD']
    for center in centers[1:]:
        assert canvas.get(continuation_row, center) == '┆'
    text_start = lines[continuation_row].index('next')
    assert all(canvas.get(continuation_row, column) != '┆'
               for column in range(text_start, text_start + display_width('next')))


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('autonumber', [False, True])
def test_message_uses_arrow_span_without_crossing_endpoints(reverse, autonumber):
    message = '返回整批 descriptor 或逐 key 错误，T_replica_rpc 结束'
    source_id, target_id = ('B', 'A') if reverse else ('A', 'B')
    source = '\n'.join([
        'sequenceDiagram', 'autonumber' if autonumber else '',
        'participant A', 'participant B', 'participant C',
        f'{source_id}-->>{target_id}: {message}',
    ])
    canvas = render_sequence(parse_sequence_diagram(source), max_label_width=20, gap=36)
    lines = canvas.to_string().splitlines()
    left = lines[1].index('A')
    right = lines[1].index('B')
    assert right - left == 36
    label_rows = []
    for row in canvas.to_styled_pairs():
        columns = [column for column, (_, style) in enumerate(row) if style == 'edge_label']
        if columns:
            assert left + 2 <= min(columns) <= max(columns) <= right - 2
            label_rows.append(''.join(character for character, style in row if style == 'edge_label'))
    assert len(label_rows) == 2
    assert 'T_replica_rpc 结束' in label_rows[-1]
    assert ' '.join(label_rows).removeprefix('1: ') == message
    assert lines[1].index('C') == right + 36


def test_self_message_uses_clear_label_space_and_keeps_timing_phrase():
    diagram = parse_sequence_diagram('''sequenceDiagram
participant A
participant B
A->>A: BatchQuery 返回，T_metadata 结束''')
    canvas = render_sequence(diagram, max_label_width=20, gap=36)
    lines = canvas.to_string().splitlines()
    left = lines[1].index('A')
    loop_row = next(row for row in lines[3:] if '┐' in row)
    loop_right = loop_row.index('┐')
    next_lifeline = lines[1].index('B')
    assert loop_right < next_lifeline
    label_rows = []
    for row in canvas.to_styled_pairs():
        columns = [column for column, (_, style) in enumerate(row) if style == 'edge_label']
        if columns:
            assert left < min(columns) <= max(columns) < next_lifeline
            label_rows.append(''.join(character for character, style in row if style == 'edge_label'))
    assert label_rows == ['BatchQuery 返回，', 'T_metadata 结束']


@pytest.mark.parametrize('use_ascii', [False, True])
@pytest.mark.parametrize('gap', [52, 80])
def test_self_loop_cap_is_proportional_and_independent_of_long_label_length(use_ascii, gap):
    reaches = []
    for label in ('prepare standby controller', 'start admin server and enter standby'):
        diagram = parse_sequence_diagram('\n'.join([
            'sequenceDiagram', 'participant A', 'participant B', 'participant C',
            f'A->>A: {label}',
        ]))
        canvas = render_sequence(diagram, use_ascii=use_ascii, gap=gap)
        lines = canvas.to_string().splitlines()
        left = lines[1].index('A')
        next_lifeline = lines[1].index('B')
        loop_row = next(line for line in lines[3:] if ('+' if use_ascii else '┐') in line)
        loop_right = loop_row.index('+' if use_ascii else '┐')
        reach = loop_right - left + 1
        assert reach == max(10, int(canvas.width * 0.15))
        assert loop_right < next_lifeline - 1
        label_row = next(line for line in lines if label in line)
        assert label_row.index(label) + display_width(label) > loop_right
        assert label_row[next_lifeline] == (':' if use_ascii else '┆')
        reaches.append(reach)
    assert reaches[0] == reaches[1]


@pytest.mark.parametrize('use_ascii', [False, True])
@pytest.mark.parametrize('label', ['', 'x', 'local work'])
def test_short_self_loop_keeps_eight_visible_cells_and_neighbor_clear(use_ascii, label):
    diagram = parse_sequence_diagram('\n'.join([
        'sequenceDiagram', 'participant A', 'participant B', f'A->>A: {label}',
    ]))
    canvas = render_sequence(diagram, use_ascii=use_ascii, gap=1, max_label_width=3)
    lines = canvas.to_string().splitlines()
    left = lines[1].index('A')
    next_lifeline = lines[1].index('B')
    loop_row_index = next(index for index, line in enumerate(lines[3:], start=3)
                          if ('+' if use_ascii else '┐') in line)
    loop_right = lines[loop_row_index].index('+' if use_ascii else '┐')
    assert loop_right - (left + 2) + 1 >= 8
    assert loop_right <= next_lifeline - 2
    assert canvas.get(loop_row_index + 1, left + 2) == ('<' if use_ascii else '◄')


@pytest.mark.parametrize('label', ['one\ntwo', 'one\n\ntwo'])
def test_message_refitting_preserves_explicit_line_breaks(label):
    diagram = parse_sequence_diagram('sequenceDiagram\nA->>B: placeholder')
    message = diagram.events[0]
    assert isinstance(message, Message)
    message.label = label
    canvas = render_sequence(diagram, max_label_width=5, gap=36)
    assert message.label == label
    assert 'one' in canvas.to_string() and 'two' in canvas.to_string()


@pytest.mark.parametrize('use_ascii', [False, True])
@pytest.mark.parametrize('node_width', [5, 10, 20])
def test_arrow_never_breaks_a_label_that_fits_between_endpoints(use_ascii, node_width):
    label = 'BatchQuery 返回，T_metadata 结束'
    diagram = parse_sequence_diagram(f'sequenceDiagram\nA->>B: {label}')
    canvas = render_sequence(diagram, use_ascii=use_ascii, max_label_width=node_width, gap=36)
    label_rows = [
        ''.join(character for character, style in row if style == 'edge_label')
        for row in canvas.to_styled_pairs()
        if any(style == 'edge_label' for _, style in row)
    ]
    assert label_rows == [label]


@pytest.mark.parametrize('arrow', ['->>', '-->>', '<<->>', '-)', '-x'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('use_ascii', [False, True])
def test_arrow_ends_leave_a_blank_cell_beside_lifelines(arrow, reverse, use_ascii):
    source_id, target_id = ('B', 'A') if reverse else ('A', 'B')
    diagram = parse_sequence_diagram('\n'.join([
        'sequenceDiagram', 'participant A', 'participant B',
        'par hint', f'{source_id}{arrow}{target_id}: payload', 'end',
    ]))
    canvas = render_sequence(diagram, use_ascii=use_ascii)
    lines = canvas.to_string().splitlines()
    left = lines[1].index('A')
    right = lines[1].index('B')
    arrow_row = next(index for index, row in enumerate(canvas.to_styled_pairs())
                     if any(style == 'arrow' for _, style in row))
    lifeline = ':' if use_ascii else '┆'
    assert canvas.get(arrow_row, left) == canvas.get(arrow_row, right) == lifeline
    assert canvas.get(arrow_row, left + 1) == canvas.get(arrow_row, right - 1) == ' '
    assert canvas.get(arrow_row, left + 2) != ' '
    assert canvas.get(arrow_row, right - 2) != ' '


@pytest.mark.parametrize('use_ascii', [False, True])
def test_self_loop_keeps_lifeline_and_neighbor_clear(use_ascii):
    source = '''sequenceDiagram
participant A
participant B
A->>A: long local work
A->>B: done'''
    canvas = render_sequence(parse_sequence_diagram(source), use_ascii=use_ascii)
    lines = canvas.to_string().splitlines()
    left = lines[1].index('A')
    right = lines[1].index('B')
    return_row = next(index for index, row in enumerate(canvas.to_styled_pairs())
                      if any(character == ('<' if use_ascii else '◄') and style == 'arrow'
                             for character, style in row))
    lifeline = ':' if use_ascii else '┆'
    for row in (return_row - 1, return_row):
        assert canvas.get(row, left) == canvas.get(row, right) == lifeline
        assert canvas.get(row, left + 1) == canvas.get(row, right - 1) == ' '


def test_unavoidable_crossing_is_marked_without_touching_endpoint_lifelines():
    canvas = render_sequence(parse_sequence_diagram('''sequenceDiagram
participant A
participant B
participant C
A->>C: across'''))
    lines = canvas.to_string().splitlines()
    centers = [lines[1].index(name) for name in 'ABC']
    arrow_row = next(index for index, line in enumerate(lines) if '►' in line)
    assert canvas.get(arrow_row, centers[1]) == 'x'
    assert canvas.get(arrow_row, centers[0]) == canvas.get(arrow_row, centers[2]) == '┆'


def test_clearance_preserves_active_lifeline():
    canvas = render_sequence(parse_sequence_diagram('''sequenceDiagram
participant A
participant B
activate B
A->>B: request
B-->>A: reply
deactivate B'''))
    lines = canvas.to_string().splitlines()
    right = lines[1].index('B')
    for row, line in enumerate(lines):
        if '►' in line or '◄' in line:
            assert canvas.get(row, right) == '║'
            assert canvas.get(row, right - 1) == ' '
