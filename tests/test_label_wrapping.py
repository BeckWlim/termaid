"""Shared wrapping keeps normal words and identifier segments intact when they fit."""
from pathlib import Path
import json

import pytest

from termaid import render
from termaid.cli import main
from termaid.output.styled import render_styled
from termaid.utils import display_width, wrap_display_text


@pytest.mark.parametrize('text,width,expected', [
    ('metadata_shard[s].mutex', 20, ['metadata_shard[s]', '.mutex']),
    ('metadata_shard[s].mutex', 12, ['metadata_', 'shard[s]', '.mutex']),
    ('metadata_shard[s].mutex', 9, ['metadata_', 'shard[s]', '.mutex']),
    ('RealClient', 8, ['Real', 'Client']),
    ('MasterService', 9, ['Master', 'Service']),
    ('HTTPServer', 6, ['HTTP', 'Server']),
    ('Client::BatchGet', 11, ['Client', '::BatchGet']),
    ('local-copy', 8, ['local-', 'copy']),
    ('path/to/file', 10, ['path/to/', 'file']),
    ('call metadata_shard[s].mutex', 20, ['call', 'metadata_shard[s]', '.mutex']),
    ('metadata_shard[s].mutex\nnext', 20, ['metadata_shard[s]', '.mutex', 'next']),
])
def test_meaningful_breakpoints(text, width, expected):
    assert wrap_display_text(text, width) == expected
    assert all(display_width(line) <= width for line in expected)


@pytest.mark.parametrize('text', [
    'metadata_shard[s].mutex', 'HTTPServer::GetResult', 'prefix_value-name/path',
    'abcdefghijk', '123.456789', '混合text测试.mutex',
])
@pytest.mark.parametrize('width', [2, 3, 5, 6, 8, 10, 12, 20, 40])
def test_fitting_preserves_every_character_and_display_width(text, width):
    lines = wrap_display_text(text, width)
    assert ''.join(lines) == text
    assert all(line and display_width(line) <= width for line in lines)


def test_unbreakable_suffix_still_obeys_strict_width():
    assert wrap_display_text('.mutex', 5) == ['.mute', 'x']
    assert wrap_display_text('metadata_shard[s].mutex', 12, hard_break=False) == ['metadata_shard[s].mutex']


@pytest.mark.parametrize('source', [
    'graph TD\nA["metadata_shard[s].mutex"]',
    'sequenceDiagram\nparticipant A as metadata_shard[s].mutex\nA->>A: work',
])
def test_flowchart_and_sequence_labels_keep_member_name_together(source):
    output = render(source, max_label_width=20)
    assert 'metadata_shard[s]' in output and '.mutex' in output
    assert 'metadata_shard[s].mu' not in output
    document = render_styled(source, max_label_width=20)
    assert any('.mutex' in ''.join(chunk['text'] for chunk in row) for row in document['lines'])


@pytest.mark.parametrize('width', [85, 100, 120, 160])
def test_actual_sequence_fitting_keeps_mutex_whole(width, capsys):
    fixture = Path(__file__).parent / 'fixtures/production_eviction_sequence.mmd'
    assert main([
        str(fixture), '--width', str(width), '--strict-width', '--fit-mode', 'reflow',
        '--gap', '2', '--padding-x', '2', '--padding-y', '0', '--format', 'styled-json',
    ]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    lines = [''.join(chunk['text'] for chunk in row) for row in document['lines']]
    assert max(map(display_width, lines)) <= width
    assert any('.mutex' in line for line in lines)
    output = '\n'.join(lines)
    assert output.count('▶') + output.count('◀') == 39


@pytest.mark.parametrize('text,width,expected', [
    ('Read complete words here', 14, ['Read complete', 'words here']),
    ('hello,world', 8, ['hello,', 'world']),
    ('获取mutex结束', 8, ['获取', 'mutex', '结束']),
    ('RPC结束', 5, ['RPC', '结束']),
    ("don't split words", 7, ["don't", 'split', 'words']),
    ('first paragraph\n\nsecond paragraph', 12, ['first', 'paragraph', '', 'second', 'paragraph']),
])
def test_normal_text_keeps_complete_words(text, width, expected):
    assert wrap_display_text(text, width) == expected


@pytest.mark.parametrize('width', [8, 10, 12, 20])
def test_prose_words_are_never_split_when_each_word_can_fit(width):
    text = 'Read complete words and keep ordinary prose readable'
    lines = wrap_display_text(text, width)
    assert ' '.join(lines).split() == text.split()
    assert all(display_width(line) <= width for line in lines)


@pytest.mark.parametrize('source', [
    'graph TD\nA[Read complete words here]',
    'sequenceDiagram\nparticipant A as Read complete words here\nA->>A: work',
])
def test_normal_node_labels_keep_words_together(source):
    output = render(source, max_label_width=14)
    assert 'Read complete' in output and 'words here' in output


@pytest.mark.parametrize('text,width,expected', [
    ('BatchQuery 返回，T_metadata 结束', 20, ['BatchQuery 返回，', 'T_metadata 结束']),
    ('错误，T_replica_rpc 结束', 20, ['错误，', 'T_replica_rpc 结束']),
    ('返回整批 descriptor 或逐 key 错误，T_replica_rpc 结束', 28,
     ['返回整批 descriptor 或逐 key', '错误，T_replica_rpc 结束']),
    ('alpha beta gamma', 10, ['alpha beta', 'gamma']),
])
def test_clause_breaks_and_exact_fit_words(text, width, expected):
    assert wrap_display_text(text, width) == expected
