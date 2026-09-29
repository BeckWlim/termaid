"""Immutable diagram registrations and lazy loading for core and plugins."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from importlib import import_module
from types import MappingProxyType
from typing import Mapping

from .core.contracts import DiagramDefinition, Renderer


class DiagramUnavailableError(ValueError):
    """A classified family cannot be loaded from the selected registry."""


@dataclass(frozen=True)
class DiagramRegistry:
    """A snapshot: extending it returns a new registry without changing callers."""

    definitions: tuple[DiagramDefinition, ...]
    _by_id: Mapping[str, DiagramDefinition] = field(init=False, repr=False, compare=False)
    _headers: Mapping[str, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_id: dict[str, DiagramDefinition] = {}
        headers: dict[str, str] = {}
        for definition in self.definitions:
            if definition.diagram_id in by_id:
                raise ValueError(f"Duplicate diagram identifier: {definition.diagram_id!r}")
            by_id[definition.diagram_id] = definition
            for header in definition.headers:
                if header in headers:
                    raise ValueError(f"Ambiguous diagram header: {header!r}")
                headers[header] = definition.diagram_id
        object.__setattr__(self, "definitions", tuple(self.definitions))
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))
        object.__setattr__(self, "_headers", MappingProxyType(headers))

    def register(self, definition: DiagramDefinition) -> DiagramRegistry:
        return DiagramRegistry((*self.definitions, definition))

    def identify(self, header: str) -> str:
        """Preserve flowchart fallback only for unrecognized headers."""
        return self._headers.get(header, "flowchart")

    def resolve(self, diagram_id: str) -> Renderer:
        definition = self._by_id.get(diagram_id)
        if definition is None:
            raise DiagramUnavailableError(f"Diagram {diagram_id!r} is not registered")
        if definition.contract_version != 1:
            raise DiagramUnavailableError(
                f"Diagram {diagram_id!r} requires renderer contract {definition.contract_version}; supported: 1"
            )
        try:
            renderer = definition.load_renderer()
        except ImportError as error:
            raise DiagramUnavailableError(f"Cannot load diagram {diagram_id!r}: {error}") from error
        if not isinstance(renderer, Renderer):
            raise DiagramUnavailableError(f"Diagram {diagram_id!r} did not provide a callable renderer")
        return renderer


def _load(module_name: str, entry_name: str) -> Renderer:
    module = import_module(module_name)
    renderer_object: object = getattr(module, entry_name)
    if not isinstance(renderer_object, Renderer):
        raise TypeError(f"{module_name}.{entry_name} is not a renderer")
    return renderer_object


def _definition(diagram_id: str, headers: tuple[str, ...], module: str,
                entry: str = "render", *, core: bool = False) -> DiagramDefinition:
    return DiagramDefinition(diagram_id, headers, partial(_load, f"termaid.{module}", entry), core=core)


# This is the single source of registered header aliases. No feature imports here.
DEFAULT_REGISTRY = DiagramRegistry((
    _definition("flowchart", ("flowchart", "graph"), "diagrams.flowchart", core=True),
    _definition("stateDiagram", ("stateDiagram", "stateDiagram-v2"), "diagrams.state", core=True),
    _definition("sequenceDiagram", ("sequenceDiagram",), "diagrams.sequence.render", core=True),
    _definition("classDiagram", ("classDiagram",), "diagrams.classdiagram", core=True),
    _definition("erDiagram", ("erDiagram",), "diagrams.erdiagram", core=True),
    _definition("architecture", ("architecture", "architecture-beta"), "diagrams.architecture", core=True),
    _definition("block", ("block", "block-beta"), "plugins.blockdiagram"),
    _definition("gitGraph", ("gitGraph",), "plugins.gitgraph"),
    _definition("packet", ("packet", "packet-beta"), "plugins.packet"),
    _definition("gantt", ("gantt",), "plugins.timelines", "render_gantt_source"),
    _definition("timeline", ("timeline",), "plugins.timelines", "render_timeline_source"),
    _definition("pie", ("pie",), "plugins.charts", "render_pie_source"),
    _definition("quadrantChart", ("quadrantChart",), "plugins.charts", "render_quadrant_source"),
    _definition("xychart", ("xychart", "xychart-beta"), "plugins.charts", "render_xychart_source"),
    _definition("treemap", ("treemap", "treemap-beta"), "plugins.trees", "render_treemap_source"),
    _definition("mindmap", ("mindmap",), "plugins.trees", "render_mindmap_source"),
    _definition("journey", ("journey",), "plugins.boards", "render_journey_source"),
    _definition("kanban", ("kanban",), "plugins.boards", "render_kanban_source"),
))
