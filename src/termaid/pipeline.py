"""Classify once, resolve a renderer, and freeze each independent candidate."""
from __future__ import annotations

from dataclasses import dataclass

from .core.canvas import DiagramPlan
from .core.contracts import ParsedSource, RenderConfig, Renderer
from .registry import DEFAULT_REGISTRY, DiagramRegistry
from .source import parse_source


@dataclass(frozen=True)
class PreparedDiagram:
    """Source and resolved renderer, reusable across fitting candidates."""

    source: ParsedSource
    renderer: Renderer

    def plan(self, config: RenderConfig) -> DiagramPlan:
        result = self.renderer(self.source, config)
        return DiagramPlan.from_scene(result.scene, graph=result.graph, max_width=config.max_width)


def prepare(source: str | ParsedSource, *, registry: DiagramRegistry = DEFAULT_REGISTRY) -> PreparedDiagram:
    parsed_source = parse_source(source, registry=registry) if isinstance(source, str) else source
    return PreparedDiagram(parsed_source, registry.resolve(parsed_source.diagram_id))


def plan(
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
) -> DiagramPlan:
    """Build one plan using a typed config or the existing keyword options.

    With a config, keyword rendering options must remain at their defaults.
    Plugin config subclasses are preserved through preparation and fitting.
    """
    keyword_config = RenderConfig(
        use_ascii=use_ascii, padding_x=padding_x, padding_y=padding_y,
        rounded_edges=rounded_edges, gap=gap, inline_edge_labels=inline_edge_labels,
        max_label_width=max_label_width, uniform_nodes=uniform_nodes,
        arrow_position=arrow_position, max_width=max_width, force_vertical=force_vertical,
    )
    if config is not None and keyword_config != RenderConfig():
        raise ValueError("Use a RenderConfig or keyword rendering options, not both")
    render_config = config if config is not None else keyword_config
    return prepare(source, registry=registry).plan(render_config)
