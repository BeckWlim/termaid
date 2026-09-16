"""Common layout entry point and immutable plans for every diagram type.

Specialized algorithms keep their domain rules (lifelines, timelines, grids,
charts), but share cell occupancy, geometry merging, bounds and output plans.
No output adapter parses source or makes layout decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..graph.model import Graph
from ..utils import display_width
from .scene import LayoutScene

if TYPE_CHECKING:
    from rich.text import Text
    from ..output.styled import StyledDocument


@dataclass(frozen=True)
class StyleRule:
    key: str
    properties: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DiagramPlan:
    """Measured terminal cells and styles, detached from mutable layout state.

    Empty strings are continuation cells of wide glyphs. Rows retain the
    allocated frame so background styles can fill it. Content dimensions and
    overflow are measured separately; constraints never silently clip labels.
    """
    rows: tuple[tuple[tuple[str, str], ...], ...]
    styles: tuple[StyleRule, ...] = ()
    graph_based: bool = False
    max_width: int | None = None

    @classmethod
    def from_scene(cls, scene: LayoutScene | None, *, graph: Graph | None = None,
                   max_width: int | None = None) -> DiagramPlan:
        rows = tuple(tuple(row) for row in scene.iter_styled_rows()) if scene is not None else ()
        rules: list[StyleRule] = []
        if graph is not None:
            rules.extend(StyleRule(f"class:{name}", tuple(props.items()))
                         for name, props in graph.class_defs.items())
            rules.extend(StyleRule(f"nodestyle:{name}", tuple(props.items()))
                         for name, props in graph.node_styles.items())
            for index in range(len(graph.edges)):
                props = graph.link_styles.get(index, graph.link_styles.get(-1))
                if props:
                    rules.append(StyleRule(f"linkstyle:{index}", tuple(props.items())))
        return cls(rows, tuple(rules), graph is not None, max_width)

    def iter_styled_rows(self) -> Iterator[list[tuple[str, str]]]:
        for row in self.rows:
            yield list(row)

    def to_styled_pairs(self) -> list[list[tuple[str, str]]]:
        return [[(character, style) for character, style in row if character != ""]
                for row in self.rows]

    def to_string(self) -> str:
        lines = ["".join(character for character, style in row).rstrip() for row in self.rows]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    @property
    def width(self) -> int:
        return max((display_width(line) for line in self.to_string().splitlines()), default=0)

    @property
    def height(self) -> int:
        return len(self.to_string().splitlines())

    @property
    def width_overflow(self) -> int:
        return max(0, self.width - self.max_width) if self.max_width is not None else 0

    def to_rich(self, theme: str = "default") -> Text:
        from ..output.rich import render_plan_rich, render_sequence_rich
        return render_plan_rich(self, theme=theme) if self.graph_based else render_sequence_rich(self, theme=theme)

    def to_styled(self) -> StyledDocument:
        from ..output.styled import serialize_canvas
        return serialize_canvas(self)


def plan(
    source: str,
    *,
    use_ascii: bool = False,
    padding_x: int = 4,
    padding_y: int = 2,
    rounded_edges: bool = True,
    gap: int = 4,
    inline_edge_labels: bool = False,
    max_label_width: int | None = None,
    uniform_nodes: bool = False,
    arrow_position: str = "end",
    max_width: int | None = None,
    force_vertical: bool = False,
) -> DiagramPlan:
    """Resolve every diagram family into one complete, reusable output plan."""
    from termaid import _strip_frontmatter, parse

    if max_width is not None and max_width < 1:
        raise ValueError("max_width must be positive")
    if max_label_width is not None and max_label_width < 1:
        raise ValueError("max_label_width must be positive")

    style_graph: Graph | None = None
    canvas: LayoutScene | None
    extra: dict[str, int] = {}
    if padding_x != 4:
        extra["padding_x"] = padding_x
    if gap != 4:
        extra["gap"] = gap

    text = _strip_frontmatter(source.strip())
    if text.startswith("sequenceDiagram"):
        from ..parser.sequence import parse_sequence_diagram
        from ..renderer.sequence import render_sequence
        sequence_diagram = parse_sequence_diagram(text)
        canvas = render_sequence(
            sequence_diagram,
            use_ascii=use_ascii,
            max_label_width=max_label_width,
            **extra,
        )
    elif text.startswith("classDiagram"):
        from ..parser.classdiagram import parse_class_diagram
        from ..renderer.classdiagram import render_class_diagram
        canvas = render_class_diagram(
            parse_class_diagram(text), use_ascii=use_ascii, **extra
        )
    elif text.startswith("erDiagram"):
        from ..parser.erdiagram import parse_er_diagram
        from ..renderer.erdiagram import render_er_diagram
        canvas = render_er_diagram(
            parse_er_diagram(text), use_ascii=use_ascii, **extra
        )
    elif text.startswith("block"):
        from ..parser.blockdiagram import parse_block_diagram
        from ..renderer.blockdiagram import render_block_diagram
        canvas = render_block_diagram(
            parse_block_diagram(text), use_ascii=use_ascii, **extra
        )
    elif text.startswith("gitGraph") or (
        text.startswith("%%{init") and "gitGraph" in text
    ):
        from ..parser.gitgraph import parse_git_graph
        from ..renderer.gitgraph import render_git_graph
        canvas = render_git_graph(parse_git_graph(text), use_ascii=use_ascii)
    elif text.startswith("gantt"):
        from ..parser.timelines import parse_gantt
        from ..renderer.timelines import render_gantt
        canvas = render_gantt(parse_gantt(text), use_ascii=use_ascii)
    elif text.startswith("architecture"):
        from ..parser.architecture import parse_architecture
        from ..renderer.draw import render_graph_canvas
        architecture_graph = parse_architecture(text)
        style_graph = architecture_graph
        canvas = render_graph_canvas(
            architecture_graph,
            use_ascii=use_ascii,
            padding_x=padding_x,
            padding_y=padding_y,
            rounded_edges=rounded_edges,
            gap=gap,
            arrow_position=arrow_position,
            max_width=max_width,
        )
    elif text.startswith("pie"):
        from ..parser.charts import parse_pie_chart
        from ..renderer.charts import render_pie_chart
        canvas = render_pie_chart(parse_pie_chart(text), use_ascii=use_ascii)
    elif text.startswith("treemap"):
        from ..parser.trees import parse_treemap
        from ..renderer.trees import render_treemap
        canvas = render_treemap(parse_treemap(text), use_ascii=use_ascii)
    elif text.startswith("mindmap"):
        from ..parser.trees import parse_mindmap
        from ..renderer.trees import render_mindmap
        canvas = render_mindmap(
            parse_mindmap(text), use_ascii=use_ascii, rounded=rounded_edges
        )
    elif text.startswith("packet"):
        from ..parser.packet import parse_packet
        from ..renderer.packet import render_packet
        packet_extra: dict[str, int] = {}
        if padding_y != 2:
            packet_extra["padding_y"] = padding_y
        canvas = render_packet(
            parse_packet(text),
            use_ascii=use_ascii,
            rounded=rounded_edges,
            **packet_extra,
        )
    elif text.startswith("xychart"):
        from ..parser.charts import parse_xychart
        from ..renderer.charts import render_xychart
        canvas = render_xychart(
            parse_xychart(text), use_ascii=use_ascii, rounded=rounded_edges
        )
    elif text.startswith("journey"):
        from ..parser.boards import parse_journey
        from ..renderer.boards import render_journey
        canvas = render_journey(
            parse_journey(text),
            use_ascii=use_ascii,
            rounded=rounded_edges,
            **extra,
        )
    elif text.startswith("timeline"):
        from ..parser.timelines import parse_timeline
        from ..renderer.timelines import render_timeline
        canvas = render_timeline(parse_timeline(text), use_ascii=use_ascii)
    elif text.startswith("kanban"):
        from ..parser.boards import parse_kanban
        from ..renderer.boards import render_kanban
        canvas = render_kanban(
            parse_kanban(text), use_ascii=use_ascii, **extra
        )
    elif text.startswith("quadrantChart"):
        from ..parser.charts import parse_quadrant
        from ..renderer.charts import render_quadrant
        canvas = render_quadrant(parse_quadrant(text), use_ascii=use_ascii)
    else:
        graph = parse(text)
        style_graph = graph
        if force_vertical and graph.direction.normalized().is_horizontal:
            from ..graph.model import Direction
            graph.direction = Direction.TB
        from ..renderer.draw import render_graph_canvas
        canvas = render_graph_canvas(
            graph,
            use_ascii=use_ascii,
            padding_x=padding_x,
            padding_y=padding_y,
            rounded_edges=rounded_edges,
            gap=gap,
            inline_edge_labels=inline_edge_labels,
            max_label_width=max_label_width,
            uniform_nodes=uniform_nodes,
            max_width=max_width,
            arrow_position=arrow_position,
        )
    return DiagramPlan.from_scene(canvas, graph=style_graph, max_width=max_width)
