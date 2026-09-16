"""termaid - Render Mermaid diagram syntax as beautiful Unicode art in the terminal."""
from __future__ import annotations

import re

from .graph.model import Graph
from .parser.flowchart import parse_flowchart
from .parser.statediagram import parse_state_diagram


__version__ = "0.8.0"

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter (---...---) from the beginning of mermaid source."""
    return _FRONTMATTER_RE.sub("", text)


def parse(source: str) -> Graph:
    """Parse mermaid syntax and return a Graph model.

    Auto-detects diagram type (flowchart or state diagram).

    Args:
        source: Mermaid diagram source text

    Returns:
        Parsed Graph model
    """
    text = _strip_frontmatter(source.strip())
    if text.startswith("stateDiagram"):
        return parse_state_diagram(text)
    return parse_flowchart(text)


def render(
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
) -> str:
    """Render mermaid syntax as Unicode (or ASCII) art.

    Args:
        source: Mermaid diagram source text
        use_ascii: Use ASCII characters instead of Unicode box-drawing
        padding_x: Horizontal padding inside node boxes
        padding_y: Vertical padding inside node boxes
        gap: Space between nodes (default: 4)
        inline_edge_labels: Attach flowchart labels directly to their edges

    Returns:
        Rendered diagram as a string

    Example:
        >>> from termaid import render
        >>> print(render("graph LR\\n  A --> B --> C"))
    """
    from .layout.engine import plan

    return plan(
        source, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical,
    ).to_string()


def render_rich(
    source: str,
    *,
    use_ascii: bool = False,
    padding_x: int = 4,
    padding_y: int = 2,
    rounded_edges: bool = True,
    theme: str = "default",
    gap: int = 4,
    inline_edge_labels: bool = False,
    max_label_width: int | None = None,
    uniform_nodes: bool = False,
    arrow_position: str = "end",
    max_width: int | None = None,
    force_vertical: bool = False,
):
    """Render mermaid syntax as a Rich Text object with colors.

    Requires: pip install termaid[rich]

    Args:
        source: Mermaid diagram source text
        use_ascii: Use ASCII characters instead of Unicode
        padding_x: Horizontal padding inside node boxes
        padding_y: Vertical padding inside node boxes
        theme: Color theme name (default, terra, neon, mono, amber, phosphor)
        gap: Space between nodes (default: 4)
        inline_edge_labels: Attach flowchart labels directly to their edges

    Returns:
        rich.text.Text object
    """
    from .layout.engine import plan

    return plan(
        source, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical,
    ).to_rich(theme=theme)


# Lazy import for MermaidWidget
def __getattr__(name: str):
    if name == "MermaidWidget":
        from .output.widget import _get_widget_class
        return _get_widget_class()
    raise AttributeError(f"module 'termaid' has no attribute {name!r}")


from .layout.engine import DiagramPlan, plan
