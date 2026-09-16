"""All diagram families resolve once, then share output-independent plans."""
from dataclasses import FrozenInstanceError

import pytest

from termaid import plan, render, render_rich
from termaid.layout.engine import DiagramPlan
from termaid.layout.scene import LayoutScene
from termaid.output.styled import render_styled
from termaid.utils import display_width

SOURCES = {
    'flowchart': 'flowchart LR\nA[Input] -->|send| B[Output]',
    'state': 'stateDiagram-v2\n[*] --> Ready\nReady --> Done: finish',
    'architecture': 'architecture-beta\nservice a(server)[Input]\nservice b(server)[Output]\na:R --> L:b',
    'sequence': 'sequenceDiagram\nAlice->>Bob: hello',
    'class': 'classDiagram\nclass Animal\nclass Dog\nAnimal <|-- Dog',
    'er': 'erDiagram\nPERSON ||--o{ ORDER : places',
    'block': 'block-beta\ncolumns 2\nA["Input"] B["Output"]\nA --> B',
    'git': 'gitGraph\ncommit\nbranch feature\ncheckout feature\ncommit',
    'gantt': 'gantt\nsection Work\nTask :a1, 2024-01-01, 3d',
    'pie': 'pie\n"Input": 30\n"Output": 70',
    'treemap': 'treemap-beta\n"Input": 30\n"Output": 70',
    'mindmap': 'mindmap\n  root((Root))\n    Input\n    Output',
    'packet': 'packet-beta\n0-15: "Source"\n16-31: "Target"',
    'xychart': 'xychart-beta\nx-axis [one, two]\ny-axis 0 --> 10\nbar [3, 8]',
    'journey': 'journey\nsection Work\nTask: 5: Alice',
    'timeline': 'timeline\n2024 : Plan\n2025 : Deliver',
    'kanban': 'kanban\n  Todo\n    Design\n  Done\n    Build',
    'quadrant': 'quadrantChart\nInput: [0.2, 0.8]\nOutput: [0.8, 0.2]',
}


def plain_styled(document):
    return '\n'.join(''.join(chunk['text'] for chunk in row) for row in document['lines'])


@pytest.mark.parametrize('source', SOURCES.values(), ids=SOURCES)
@pytest.mark.parametrize('use_ascii', [False, True])
@pytest.mark.parametrize('custom_options', [False, True])
def test_all_families_share_geometry_across_adapters(source, use_ascii, custom_options):
    options = {'padding_x': 2, 'padding_y': 0, 'gap': 7, 'rounded_edges': False} if custom_options else {}
    diagram_plan = plan(source, use_ascii=use_ascii, **options)
    assert isinstance(diagram_plan, DiagramPlan)
    output = diagram_plan.to_string()
    assert output
    assert output == render(source, use_ascii=use_ascii, **options)
    assert output == plain_styled(diagram_plan.to_styled())
    assert output == plain_styled(render_styled(source, use_ascii=use_ascii, **options))
    # Rich retains background-bearing trailing spaces for chart sections.
    assert output == '\n'.join(line.rstrip() for line in diagram_plan.to_rich().plain.splitlines()).rstrip('\n')
    assert diagram_plan.to_rich().plain == render_rich(source, use_ascii=use_ascii, **options).plain
    assert diagram_plan.width == max(map(display_width, output.splitlines()))
    assert diagram_plan.height == len(output.splitlines())


def test_frozen_plan_is_detached_and_serializes_without_layout(monkeypatch):
    scene = LayoutScene(8, 2)
    scene.put_text(0, 0, '内存', style='label')
    diagram_plan = DiagramPlan.from_scene(scene, max_width=3)
    scene.put_text(0, 0, 'changed')
    assert diagram_plan.to_string() == '内存'
    assert diagram_plan.width == 4 and diagram_plan.width_overflow == 1
    with pytest.raises(FrozenInstanceError):
        diagram_plan.rows = ()

    def fail(*args, **kwargs):
        raise AssertionError('serializing a plan must not run layout')

    monkeypatch.setattr('termaid.layout.engine.plan', fail)
    assert diagram_plan.to_rich().plain == '内存'
    assert plain_styled(diagram_plan.to_styled()) == '内存'


def test_plan_retains_custom_graph_styles():
    diagram_plan = plan('flowchart LR\nA --> B\nstyle A fill:#123456\nlinkStyle 0 stroke:#abcdef')
    rules = {rule.key: dict(rule.properties) for rule in diagram_plan.styles}
    assert rules['nodestyle:A']['fill'] == '#123456'
    assert rules['linkstyle:0']['stroke'] == '#abcdef'
    assert any('#abcdef' in str(span.style) for span in diagram_plan.to_rich().spans)


@pytest.mark.parametrize('direction', ['RL', 'BT'])
def test_orientation_keeps_text_order_and_characters(direction):
    source = f'flowchart {direction}\nA["Server<br/>内存"] -->|receive value| B["Disk<br/>SSD"]'
    output = plan(source, gap=8).to_string()
    assert 'Server' in output and '内存' in output and 'receive' in output and 'value' in output
    assert 'revreS' not in output and 'recei^e' not in output
    assert output.index('Server') < output.index('内存')


def test_crossing_sweeps_reduce_crossings_without_breaking_groups():
    from termaid import parse
    from termaid.layout.layers import _count_crossings, _greedy_crossing_sweeps
    graph = parse('flowchart TB\nA --> D\nB --> C')
    original = [['A', 'B'], ['C', 'D']]
    ordered = _greedy_crossing_sweeps(graph, original)
    assert _count_crossings(graph, original) == 1
    assert _count_crossings(graph, ordered) == 0
    assert original == [['A', 'B'], ['C', 'D']]
    assert ordered == _greedy_crossing_sweeps(graph, original)


def test_layout_preserves_declared_blocks_and_connections():
    from copy import deepcopy
    from termaid import parse
    from termaid.layout.graph_plan import plan_graph

    source = '''flowchart TB
subgraph Storage[Storage resources]
Memory[Memory]
Disk[Disk]
end
Client -->|put| Memory
Memory -->|reply| Client
Client -->|offload| Disk
Memory --> Disk
Master -.-> Storage'''
    graph = parse(source)
    original_nodes = deepcopy(graph.nodes)
    original_edges = deepcopy(graph.edges)
    original_members = {group.id: tuple(group.node_ids) for group in graph.subgraphs}
    geometry = plan_graph(graph, padding_x=0, padding_y=0, gap=1)
    assert set(geometry.layout.placements) == set(original_nodes)
    assert len(geometry.layout.placements) == len(original_nodes)
    assert geometry.graph.edges == original_edges
    assert len(geometry.routes) == len(original_edges)
    assert [route.edge for route in geometry.routes] == original_edges
    assert graph.nodes == original_nodes and graph.edges == original_edges
    assert {group.id: tuple(group.node_ids) for group in graph.subgraphs} == original_members
