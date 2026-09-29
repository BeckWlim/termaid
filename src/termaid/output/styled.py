"""Versioned semantic styled-output adapter."""
from __future__ import annotations

from typing import TypedDict

from termaid.core.canvas import Canvas
from termaid.core.canvas import DiagramPlan


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


# Retained documented import; canonical rendering lives in the public API.
from termaid import render_styled as render_styled
