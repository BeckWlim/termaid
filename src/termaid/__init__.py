"""termaid - Render Mermaid diagram syntax as beautiful Unicode art in the terminal."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.text import Text
    from termaid.output.styled import StyledDocument

from termaid.core.graph import Graph
from termaid.core.canvas import Canvas, DiagramPlan
from termaid.core.contracts import (
    ConfiguredRenderer,
    DiagramDefinition,
    DiagramType,
    ParsedSource,
    RenderConfig,
    RenderResult,
    Renderer,
    adapted_loader,
)
from termaid.pipeline import plan, prepare
from termaid.registry import DEFAULT_REGISTRY, DiagramRegistry, DiagramUnavailableError
from termaid.source import parse_source


__version__ = "0.8.0"


def parse(source: str) -> Graph:
    """Parse mermaid syntax and return a Graph model.

    Auto-detects diagram type (flowchart or state diagram).

    Args:
        source: Mermaid diagram source text

    Returns:
        Parsed Graph model
    """
    from termaid.diagrams.flowchart import parse_flowchart
    from termaid.diagrams.state import parse_state_diagram

    parsed_source = parse_source(source)
    if parsed_source.diagram_type is DiagramType.STATE:
        return parse_state_diagram(parsed_source.body)
    return parse_flowchart(parsed_source.body)


def render(
    source: str | ParsedSource,
    config: RenderConfig | None = None,
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
    registry: DiagramRegistry = DEFAULT_REGISTRY,
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
    return plan(
        source, config, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical,
        registry=registry,
    ).to_string()


def render_rich(
    source: str | ParsedSource,
    config: RenderConfig | None = None,
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
    registry: DiagramRegistry = DEFAULT_REGISTRY,
) -> Text:
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
    return plan(
        source, config, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical,
        registry=registry,
    ).to_rich(theme=theme)


# Lazy import for MermaidWidget
def __getattr__(name: str):
    if name == "MermaidWidget":
        from termaid.output.widget import _get_widget_class
        return _get_widget_class()
    raise AttributeError(f"module 'termaid' has no attribute {name!r}")


def render_styled(
    source: str | ParsedSource,
    config: RenderConfig | None = None,
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
    registry: DiagramRegistry = DEFAULT_REGISTRY,
) -> StyledDocument:
    """Render Mermaid source as versioned semantic chunks without Rich."""
    return plan(
        source, config, use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical, registry=registry,
    ).to_styled()
