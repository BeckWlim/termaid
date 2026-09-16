"""Keep sibling labels, sequence headers, and scope hints readable when fitted."""
from pathlib import Path
import json
import re

import pytest

from termaid.cli import main
from termaid.model.sequence import Block
from termaid.output.styled import render_styled
from termaid.parser.sequence import parse_sequence_diagram
from termaid.renderer.sequence import render_sequence
from termaid.utils import display_width

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('width', [68, 85, 100, 120, 160])
@pytest.mark.parametrize('output_format', ['text', 'styled-json'])
def test_production_sequence_headers_and_scope_titles(width, output_format, capsys):
    assert main([
        str(FIXTURES / 'production_eviction_sequence.mmd'), '--width', str(width),
        '--strict-width', '--fit-mode', 'reflow', '--gap', '2',
        '--padding-x', '2', '--padding-y', '0', '--format', output_format,
    ]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    if output_format == 'styled-json':
        document = json.loads(captured.out)
        lines = [''.join(chunk['text'] for chunk in row) for row in document['lines']]
        heading_chunks = [chunk for row in document['lines'] for chunk in row if '[par]' in chunk['text']]
        assert heading_chunks and all(chunk['style'] == 'subgraph_label' for chunk in heading_chunks)
        border_chunks = [chunk for row in document['lines'] for chunk in row if chunk['style'] == 'subgraph']
        assert border_chunks
    else:
        lines = captured.out.splitlines()
    assert max(map(display_width, lines)) <= width
    top_borders = list(re.finditer('┌─+┐', lines[0]))
    assert len(top_borders) == 5
    if width <= 120:  # The capped matching policy need not stretch short names forever.
        assert len({border.end() - border.start() for border in top_borders}) == 1
    bottom_index = next(index for index, line in enumerate(lines) if '└' in line)
    assert lines[bottom_index].count('└') == 5
    output = '\n'.join(lines)
    assert '[par] 前台逐 shard 查询并完成读取' in output
    if width >= 85:
        assert '[opt] 独立的存在性查询 RPC' in output
    source = (FIXTURES / 'production_eviction_sequence.mmd').read_text()
    message_count = sum('->>' in line or '-->>' in line for line in source.splitlines())
    assert output.count('▶') + output.count('◀') == message_count


def test_scope_wrapping_uses_frame_width_and_preserves_explicit_breaks():
    source = '''sequenceDiagram
participant A
participant B
participant C
par first heading<br/>second heading with detail
A->>C: go
and secondary condition with detail
C->>A: back
end'''
    diagram = parse_sequence_diagram(source)
    scope = diagram.events[0]
    assert isinstance(scope, Block)
    scope.label = scope.label.replace("<br/>", "\n")
    canvas = render_sequence(diagram, max_label_width=5)
    output = canvas.to_string()
    assert '[par] first heading' in output
    assert 'second heading with detail' in output
    assert '[secondary condition with detail]' in output
    assert canvas.width < 60


def test_scope_style_does_not_replace_message_or_node_styles():
    document = render_styled('sequenceDiagram\npar hint\nA->>B: payload\nend')
    styles = {chunk['style'] for row in document['lines'] for chunk in row}
    assert {'node', 'label', 'edge', 'arrow', 'edge_label', 'subgraph', 'subgraph_label'} <= styles
