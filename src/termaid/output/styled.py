"""Versioned semantic styled-output adapter."""
from __future__ import annotations

from typing import Any

from ..renderer.canvas import Canvas


_SEMANTIC_STYLES = {
    "active",
    "arrow",
    "bold_label",
    "crit",
    "default",
    "done",
    "edge",
    "edge_label",
    "italic_label",
    "label",
    "milestone",
    "node",
    "normal",
    "subgraph",
    "subgraph_label",
}


def _semantic_style(style: str) -> str:
    """Collapse renderer-private identifiers into stable semantic roles."""
    if style in _SEMANTIC_STYLES:
        return style
    if style.startswith(("class:", "nodestyle:")):
        return "node"
    if style.startswith("linkstyle:"):
        return "edge"
    if style.startswith(("section:", "sectionfg:")):
        return style
    return "default"


def serialize_canvas(canvas: Canvas | None) -> dict[str, Any]:
    """Return compact, theme-independent chunks for non-terminal clients."""
    if canvas is None:
        return {"version": 1, "lines": []}
    lines: list[list[dict[str, str]]] = []
    for raw_row in canvas.to_styled_pairs():
        last_cell = len(raw_row)
        while last_cell > 0 and raw_row[last_cell - 1][0] in ("", " "):
            last_cell -= 1
        chunks: list[dict[str, str]] = []
        for character, raw_style in raw_row[:last_cell]:
            if character == "":
                continue
            style = _semantic_style(raw_style)
            if chunks and chunks[-1]["style"] == style:
                chunks[-1]["text"] += character
            else:
                chunks.append({"text": character, "style": style})
        lines.append(chunks)
    while lines and not lines[-1]:
        lines.pop()
    return {"version": 1, "lines": lines}


def render_styled(
    source: str,
    *,
    use_ascii: bool = False,
    padding_x: int = 4,
    padding_y: int = 2,
    rounded_edges: bool = True,
    gap: int = 4,
    inline_edge_labels: bool = False,
    max_label_width: int | None = None,
    force_vertical: bool = False,
) -> dict[str, Any]:
    """Render Mermaid source as versioned semantic chunks without Rich."""
    from termaid import _strip_frontmatter, parse

    extra: dict[str, int] = {}
    if padding_x != 4:
        extra["padding_x"] = padding_x
    if gap != 4:
        extra["gap"] = gap

    text = _strip_frontmatter(source.strip())
    if text.startswith("sequenceDiagram"):
        from ..parser.sequence import parse_sequence_diagram
        from ..renderer.sequence import render_sequence
        diagram = parse_sequence_diagram(text)
        canvas = render_sequence(
            diagram,
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
        from ..parser.gantt import parse_gantt
        from ..renderer.gantt import render_gantt
        canvas = render_gantt(parse_gantt(text), use_ascii=use_ascii)
    elif text.startswith("architecture"):
        from ..parser.architecture import parse_architecture
        from ..renderer.draw import render_graph_canvas
        canvas = render_graph_canvas(
            parse_architecture(text),
            use_ascii=use_ascii,
            padding_x=padding_x,
            padding_y=padding_y,
            rounded_edges=rounded_edges,
            gap=gap,
        )
    elif text.startswith("pie"):
        from ..parser.piechart import parse_pie_chart
        from ..renderer.piechart import render_pie_chart
        canvas = render_pie_chart(parse_pie_chart(text), use_ascii=use_ascii)
    elif text.startswith("treemap"):
        from ..parser.treemap import parse_treemap
        from ..renderer.treemap import render_treemap
        canvas = render_treemap(parse_treemap(text), use_ascii=use_ascii)
    elif text.startswith("mindmap"):
        from ..parser.mindmap import parse_mindmap
        from ..renderer.mindmap import render_mindmap
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
        from ..parser.xychart import parse_xychart
        from ..renderer.xychart import render_xychart
        canvas = render_xychart(
            parse_xychart(text), use_ascii=use_ascii, rounded=rounded_edges
        )
    elif text.startswith("journey"):
        from ..parser.journey import parse_journey
        from ..renderer.journey import render_journey
        canvas = render_journey(
            parse_journey(text),
            use_ascii=use_ascii,
            rounded=rounded_edges,
            **extra,
        )
    elif text.startswith("timeline"):
        from ..parser.timeline import parse_timeline
        from ..renderer.timeline import render_timeline
        canvas = render_timeline(parse_timeline(text), use_ascii=use_ascii)
    elif text.startswith("kanban"):
        from ..parser.kanban import parse_kanban
        from ..renderer.kanban import render_kanban
        canvas = render_kanban(
            parse_kanban(text), use_ascii=use_ascii, **extra
        )
    elif text.startswith("quadrantChart"):
        from ..parser.quadrant import parse_quadrant
        from ..renderer.quadrant import render_quadrant
        canvas = render_quadrant(parse_quadrant(text), use_ascii=use_ascii)
    else:
        graph = parse(text)
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
        )
    return serialize_canvas(canvas)
