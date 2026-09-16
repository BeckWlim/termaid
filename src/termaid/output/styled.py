"""Versioned semantic styled-output adapter."""
from __future__ import annotations

from typing import TypedDict

from ..renderer.canvas import Canvas
from ..layout.engine import DiagramPlan


class StyledChunk(TypedDict):
    text: str
    style: str


class StyledDocument(TypedDict):
    version: int
    lines: list[list[StyledChunk]]


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


def serialize_canvas(canvas: Canvas | DiagramPlan | None) -> StyledDocument:
    """Return compact, theme-independent chunks for non-terminal clients."""
    if canvas is None:
        return {"version": 1, "lines": []}
    lines: list[list[StyledChunk]] = []
    for raw_row in canvas.iter_styled_rows():
        last_cell = len(raw_row)
        while last_cell > 0 and raw_row[last_cell - 1][0] in ("", " "):
            last_cell -= 1
        chunks: list[StyledChunk] = []
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
    uniform_nodes: bool = False,
    arrow_position: str = "end",
    max_width: int | None = None,
    force_vertical: bool = False,
) -> StyledDocument:
    """Render Mermaid source as versioned semantic chunks without Rich."""
    from ..layout.engine import plan

    return plan(
        source, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical,
    ).to_styled()
