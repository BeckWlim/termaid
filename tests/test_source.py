"""Source classification is independent of layout and directive contents."""
from dataclasses import FrozenInstanceError

import pytest

from termaid import DiagramType, parse, parse_source, plan


@pytest.mark.parametrize('diagram_type', list(DiagramType))
def test_classifies_each_family(diagram_type):
    assert parse_source(diagram_type.value).diagram_type is diagram_type


@pytest.mark.parametrize('header, expected_type', [
    ('graph LR', DiagramType.FLOWCHART),
    ('stateDiagram-v2', DiagramType.STATE),
    ('block-beta', DiagramType.BLOCK),
    ('architecture-beta', DiagramType.ARCHITECTURE),
    ('treemap-beta', DiagramType.TREEMAP),
    ('packet-beta', DiagramType.PACKET),
    ('xychart-beta', DiagramType.XYCHART),
    ('gitGraph TB:', DiagramType.GIT),
    ('pie showData', DiagramType.PIE),
])
def test_classifies_header_variants(header, expected_type):
    assert parse_source(header).diagram_type is expected_type


def test_preserves_directives_but_detects_actual_header():
    directive = '%%{init: {\n"gitGraph": {"mainBranchName": "trunk"}\n}}%%'
    body = 'sequenceDiagram\nAlice->>Bob: gitGraph'
    text = f'%% gitGraph is only a comment\n{directive}\n\n{body}'
    parsed_source = parse_source(f' \n---\ntitle: gitGraph\n---\n\n{text}\n ')
    assert parsed_source.diagram_type is DiagramType.SEQUENCE
    assert parsed_source.text == text
    assert parsed_source.body == body
    assert plan(parsed_source) == plan(body)
    with pytest.raises(FrozenInstanceError):
        parsed_source.text = 'changed'


@pytest.mark.parametrize('source', [
    '', '   ', '%% comment', '%%{init: {}}%%',
    '---\ntitle: empty\n---',
    'unknown\ngitGraph\ncommit', 'pieChart\n"A": 1', 'pie_chart\n"A": 1',
    '%%{init: {"gitGraph": {}}',
])
def test_missing_unknown_and_incomplete_headers_keep_fallback(source):
    assert parse_source(source).diagram_type is DiagramType.FLOWCHART


def test_git_directive_survives_preclassification():
    source = ('%% a leading comment\n'
              '%%{init: {"gitGraph": {"mainBranchName": "trunk"}}}%%\n'
              'gitGraph\ncommit id: "first"')
    parsed_source = parse_source(source)
    assert parsed_source.diagram_type is DiagramType.GIT
    output = plan(parsed_source).to_string()
    assert 'trunk' in output and 'first' in output
    assert plan(parsed_source) == plan(source)


def test_state_parse_uses_header_after_preamble():
    body = 'stateDiagram-v2\n[*] --> Ready\nReady --> Done'
    source = f'%% comment\n%%{{init: {{\n"theme": "dark"\n}}}}%%\n{body}'
    assert parse(source) == parse(body)


def test_pie_header_options_survive_preamble():
    body = 'pie showData\n"Input": 30\n"Output": 70'
    assert plan(f'%% comment\n%%{{init: {{}}}}%%\n{body}') == plan(body)
