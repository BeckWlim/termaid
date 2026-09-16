"""Subgraph cycles stay compact and do not absorb their external callers."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from termaid import parse
from termaid.cli import main
from termaid.graph.model import Subgraph
from termaid.layout.graph_plan import plan_graph
from termaid.layout.layers import assign_layers, separate_subgraph_layers


FIXTURE = Path(__file__).parent / "fixtures" / "mooncake_memory_cycle.mmd"


def members(group: Subgraph) -> set[str]:
    return set(group.node_ids).union(*(members(child) for child in group.children))


@pytest.mark.parametrize("direction", ["TB", "BT", "LR", "RL"])
def test_nested_restore_cycle_preserves_membership_and_compact_layers(direction: str):
    source = FIXTURE.read_text(encoding="utf-8").replace("flowchart TB", f"flowchart {direction}")
    graph = parse(source)
    original_graph = deepcopy(graph)
    layers = separate_subgraph_layers(graph, assign_layers(graph))
    assert layers["Memory"] < layers["Offload"] < layers["SSD"]
    assert layers["SSD"] - layers["Memory"] == 2
    assert layers["Client"] < min(layers[node_id] for node_id in ("Memory", "NoF", "DFS", "Disk"))
    geometry = plan_graph(graph, padding_x=2, padding_y=0, gap=3, max_width=140)
    assert graph.nodes == original_graph.nodes
    assert graph.edges == original_graph.edges
    assert graph.direction == original_graph.direction
    assert graph.node_order == original_graph.node_order
    for group_id in ("Control", "Storage", "MemoryBackend"):
        group = graph.find_subgraph_by_id(group_id)
        original_group = original_graph.find_subgraph_by_id(group_id)
        assert group is not None and original_group is not None
        assert (group.label, group.node_ids, members(group)) == (
            original_group.label, original_group.node_ids, members(original_group),
        )
    assert len(geometry.layout.placements) == 9
    assert len(geometry.routes) == 11
    assert [route.edge for route in geometry.routes] == graph.edges
    assert geometry.height < 90
    for bounds in geometry.layout.subgraph_bounds:
        group_members = members(bounds.subgraph)
        for node_id, placement in geometry.layout.placements.items():
            if node_id in group_members:
                assert bounds.x < placement.draw_x
                assert bounds.y < placement.draw_y
                assert placement.draw_x + placement.draw_width < bounds.x + bounds.width
                assert placement.draw_y + placement.draw_height < bounds.y + bounds.height
            else:
                assert (
                    placement.draw_x + placement.draw_width <= bounds.x
                    or bounds.x + bounds.width <= placement.draw_x
                    or placement.draw_y + placement.draw_height <= bounds.y
                    or bounds.y + bounds.height <= placement.draw_y
                ), f"{node_id} overlaps unrelated frame {bounds.subgraph.id}"


@pytest.mark.parametrize("width", [80, 120, 140, 180])
@pytest.mark.parametrize("use_ascii", [False, True])
def test_nvim_options_render_cycle_without_empty_layer_explosion(width: int, use_ascii: bool, capsys):
    gap = max(1, min(4, width // 40))
    exit_code = main([
        str(FIXTURE), "--width", str(width), "--strict-width", "--fit-mode", "reflow",
        "--max-height", "90", "--gap", str(gap), "--padding-x", str(min(gap, 2)),
        "--padding-y", "0", "--format", "styled-json", "--diagnostics-format", "json",
        *(["--ascii"] if use_ascii else []),
    ])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert not captured.err
    document = json.loads(captured.out)
    lines = ["".join(chunk["text"] for chunk in row) for row in document["lines"]]
    assert len(lines) < 90
    assert max(map(len, lines)) <= width
    labels = " ".join(chunk["text"] for row in document["lines"] for chunk in row
                      if chunk["style"] in ("label", "edge_label"))
    assert all(identifier in labels for identifier in ("MasterService", "FileStorage", "LOCAL_DISK", "NOF_SSD"))


def test_acyclic_internal_paths_keep_longest_path_and_arrow_length():
    graph = parse("""flowchart TB
subgraph G
    A --> C
    A --> B
    B ----> C
end
subgraph H
    D
end
""")
    layers = separate_subgraph_layers(graph, assign_layers(graph))
    assert layers["A"] < layers["B"] < layers["C"]
    assert layers["C"] - layers["B"] == 3


def test_disconnected_internal_cycle_keeps_distinct_layers():
    graph = parse("""flowchart TB
subgraph G
    A
    B --> C --> B
end
subgraph H
    D
end
""")
    layers = separate_subgraph_layers(graph, assign_layers(graph))
    assert layers["C"] - layers["B"] == 1
    assert max(layers.values()) < len(graph.nodes)
