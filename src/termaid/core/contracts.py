"""Typed boundaries shared by the pipeline, core features, and plugins."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum
import re
from typing import Callable, Generic, Protocol, TypeVar, runtime_checkable

from .canvas import Canvas
from .graph import Graph


ConfigT = TypeVar("ConfigT", bound="RenderConfig")
BackendT = TypeVar("BackendT")


class DiagramType(str, Enum):
    """Convenient built-in names; registrations may use other string identifiers."""

    FLOWCHART = "flowchart"
    STATE = "stateDiagram"
    SEQUENCE = "sequenceDiagram"
    CLASS = "classDiagram"
    ER = "erDiagram"
    BLOCK = "block"
    GIT = "gitGraph"
    GANTT = "gantt"
    ARCHITECTURE = "architecture"
    PIE = "pie"
    TREEMAP = "treemap"
    MINDMAP = "mindmap"
    PACKET = "packet"
    XYCHART = "xychart"
    JOURNEY = "journey"
    TIMELINE = "timeline"
    KANBAN = "kanban"
    QUADRANT = "quadrantChart"


@dataclass(frozen=True)
class ParsedSource:
    """Classified source, with directives retained separately from the body."""

    diagram_id: str
    text: str
    body: str

    @property
    def diagram_type(self) -> DiagramType | str:
        """Built-in enum alias, or the identifier of an external diagram."""
        try:
            return DiagramType(self.diagram_id)
        except ValueError:
            return self.diagram_id


@dataclass(frozen=True)
class RenderConfig:
    """Common immutable options; feature entry points translate family defaults."""

    use_ascii: bool = False
    padding_x: int = 4
    padding_y: int = 2
    rounded_edges: bool = True
    gap: int = 4
    inline_edge_labels: bool = False
    max_label_width: int | None = None
    uniform_nodes: bool = False
    arrow_position: str = "end"
    max_width: int | None = None
    force_vertical: bool = False

    def __post_init__(self) -> None:
        if self.max_width is not None and self.max_width < 1:
            raise ValueError("max_width must be positive")
        if self.max_label_width is not None and self.max_label_width < 1:
            raise ValueError("max_label_width must be positive")

    def spacing_overrides(self) -> dict[str, int]:
        """Keep family spacing defaults unless common defaults were changed."""
        spacing: dict[str, int] = {}
        if self.padding_x != 4:
            spacing["padding_x"] = self.padding_x
        if self.gap != 4:
            spacing["gap"] = self.gap
        return spacing

    def with_common(self: ConfigT, common: RenderConfig) -> ConfigT:
        """Apply common settings while retaining a subclass's typed feature fields."""
        return replace(
            self, use_ascii=common.use_ascii, padding_x=common.padding_x,
            padding_y=common.padding_y, rounded_edges=common.rounded_edges,
            gap=common.gap, inline_edge_labels=common.inline_edge_labels,
            max_label_width=common.max_label_width, uniform_nodes=common.uniform_nodes,
            arrow_position=common.arrow_position, max_width=common.max_width,
            force_vertical=common.force_vertical,
        )


@dataclass(frozen=True)
class RenderResult:
    scene: Canvas | None
    graph: Graph | None = None


@runtime_checkable
class Renderer(Protocol):
    def __call__(self, source: ParsedSource, config: RenderConfig, /) -> RenderResult:
        """Parse and draw one independent candidate on the shared canvas."""
        ...


class ConfiguredRenderer(Generic[ConfigT], ABC):
    """Optional inheritance boundary for renderers with typed feature settings.

    Plain RenderConfig requests inherit the feature defaults. Explicit feature
    configurations must match this renderer's type; unrelated options are errors.
    """

    def __init__(self, defaults: ConfigT) -> None:
        self.defaults = defaults

    def __call__(self, source: ParsedSource, config: RenderConfig) -> RenderResult:
        config_type = type(self.defaults)
        if isinstance(config, config_type):
            return self.render(source, config)
        if type(config) is RenderConfig:
            return self.render(source, self.defaults.with_common(config))
        raise TypeError(f"Expected {config_type.__name__} options, got {type(config).__name__}")

    @abstractmethod
    def render(self, source: ParsedSource, config: ConfigT) -> RenderResult:
        """Implement with the concrete feature configuration, without casting."""
        raise NotImplementedError


def adapted_loader(
    load_backend: Callable[[], BackendT],
    adapt_backend: Callable[[BackendT], Renderer],
) -> Callable[[], Renderer]:
    """Lazily bridge a native/future protocol to this version's renderer contract.

    The adapter retains its backend's concrete type. Source, options and output
    translation belong to that adapter, not the dispatcher or output formats.
    """
    def load_renderer() -> Renderer:
        return adapt_backend(load_backend())

    return load_renderer


@dataclass(frozen=True)
class DiagramDefinition:
    """Registration metadata; loading implementation code is deferred."""

    diagram_id: str
    headers: tuple[str, ...]
    load_renderer: Callable[[], Renderer]
    contract_version: int = 1
    core: bool = False
    native_protocol: str = "termaid.renderer.v1"

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", self.diagram_id) is None:
            raise ValueError(f"Invalid diagram identifier: {self.diagram_id!r}")
        if not self.headers or any(re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", header) is None
                                   for header in self.headers):
            raise ValueError("Diagram headers must be nonempty Mermaid header tokens")
        if len(set(self.headers)) != len(self.headers):
            raise ValueError(f"Duplicate header in {self.diagram_id!r}")
