"""Shared geometry, routing safety, and output-adapter contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from termaid import parse
from termaid.cli import main
from termaid.layout.engine import DiagramPlan
from termaid.layout.graph_plan import plan_graph
from termaid.routing.router import RoutingError, path_cells


@pytest.mark.parametrize("direction", ["TB", "TD", "BT", "LR", "RL"])
@pytest.mark.parametrize("label_width", [None, 8])
def test_same_level_blocks_use_shared_tracks(direction: str, label_width: int | None):
    graph = parse(f'''flowchart {direction}
Root[Root]
subgraph Workers [Workers]
Short[Short]
Tall["Line one<br/>Line two<br/>Line three"]
Decision{{Choose}}
end
Root --> Short
Root --> Tall
Root --> Decision
Short --> Sink
Tall --> Sink
Decision --> Sink
''')
    geometry = plan_graph(graph, padding_x=2, padding_y=0, gap=3,
                          max_label_width=label_width, max_width=120)
    peers = [geometry.layout.placements[node_id] for node_id in ("Short", "Tall", "Decision")]
    if graph.direction.is_vertical:
        assert len({placement.draw_y for placement in peers}) == 1
        assert len({placement.draw_height for placement in peers}) == 1
        assert len({placement.draw_x for placement in peers}) == 3
    else:
        assert len({placement.draw_x for placement in peers}) == 1
        assert len({placement.draw_width for placement in peers}) == 1
        assert len({placement.draw_y for placement in peers}) == 3
    assert len(geometry.routes) == 6


def test_failed_routing_reports_an_error_instead_of_drawing_a_diagonal(
    tmp_path: Path, monkeypatch, capsys,
):
    monkeypatch.setattr("termaid.routing.router.find_path", lambda *args, **kwargs: None)
    source_path = tmp_path / "diagram.mmd"
    source_path.write_text("flowchart TB\nA --> B", encoding="utf-8")
    assert main([str(source_path), "--format", "styled-json", "--diagnostics-format", "json"]) == 1
    captured = capsys.readouterr()
    diagnostic = json.loads(captured.err)
    assert captured.out == ""
    assert diagnostic["code"] == "render_failed"
    assert diagnostic["details"]["exception_type"] == "RoutingError"
    assert "A -> B" in diagnostic["message"]
    with pytest.raises(RoutingError, match="Non-orthogonal"):
        list(path_cells([(0, 0), (2, 2)]))


@pytest.mark.parametrize("direction", ["TB", "BT", "LR", "RL"])
def test_subgraph_self_loop_attaches_to_its_frame_without_crossing_members(direction: str):
    graph = parse(f"flowchart {direction}\nsubgraph Group\nA --> B\nend\nGroup --> Group")
    geometry = plan_graph(graph)
    frame = geometry.layout.subgraph_bounds[0]
    loop = next(route for route in geometry.routes if route.edge.source == "Group")
    assert len(loop.draw_path) == 4
    for col, row in loop.draw_path[::len(loop.draw_path) - 1]:
        assert (col in (frame.x, frame.x + frame.width - 1)
                or row in (frame.y, frame.y + frame.height - 1))
    cells = list(path_cells(loop.draw_path))
    for col, row in cells:
        assert not (frame.x < col < frame.x + frame.width - 1
                    and frame.y < row < frame.y + frame.height - 1)


def test_cli_formats_fit_identical_plans_and_serialize_only_the_winner(
    tmp_path: Path, monkeypatch, capsys,
):
    import termaid.layout.engine as engine

    source_path = tmp_path / "diagram.mmd"
    source_path.write_text("graph LR\nA --> B --> C --> D --> E --> F --> G", encoding="utf-8")
    original_plan = engine.plan
    original_styled = DiagramPlan.to_styled
    original_rich = DiagramPlan.to_rich
    candidates: list[dict[str, object]] = []
    serializations: list[tuple[str, DiagramPlan]] = []

    def tracked_plan(source: str, **options) -> DiagramPlan:
        candidates.append(options)
        return original_plan(source, **options)

    def tracked_styled(diagram_plan: DiagramPlan):
        serializations.append(("styled-json", diagram_plan))
        return original_styled(diagram_plan)

    def tracked_rich(diagram_plan: DiagramPlan, theme: str = "default"):
        serializations.append(("rich", diagram_plan))
        return original_rich(diagram_plan, theme=theme)

    monkeypatch.setattr(engine, "plan", tracked_plan)
    monkeypatch.setattr(DiagramPlan, "to_styled", tracked_styled)
    monkeypatch.setattr(DiagramPlan, "to_rich", tracked_rich)
    monkeypatch.delenv("NO_COLOR", raising=False)
    candidate_sequences: list[list[dict[str, object]]] = []
    for adapter_options in ([], ["--format", "styled-json"], ["--theme", "default"]):
        candidates.clear()
        serializations.clear()
        assert main([str(source_path), "--width", "40", "--strict-width", "--fit-mode", "reflow",
                     *adapter_options]) == 0
        captured = capsys.readouterr()
        assert not captured.err
        assert 1 < len(candidates) <= 8
        candidate_sequences.append(list(candidates))
        assert len(serializations) == (1 if adapter_options else 0)
        if serializations:
            assert serializations[0][1].width <= 40
    assert candidate_sequences[0] == candidate_sequences[1] == candidate_sequences[2]
