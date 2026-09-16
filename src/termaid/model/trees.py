"""Data models for mindmaps, treemaps."""
from __future__ import annotations

from dataclasses import dataclass, field


# Mindmaps
# ------------------------------------------------------------------------

@dataclass
class MindmapNode:
    label: str
    children: list[MindmapNode] = field(default_factory=list)

    @property
    def depth(self) -> int:
        """Maximum depth of this subtree."""
        if not self.children:
            return 0
        return 1 + max(c.depth for c in self.children)


@dataclass
class Mindmap:
    root: MindmapNode | None = None
    warnings: list[str] = field(default_factory=list)


# Treemaps
# ------------------------------------------------------------------------

@dataclass
class TreemapNode:
    label: str
    value: float = 0
    children: list[TreemapNode] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        """Total value: own value for leaves, sum of children for sections."""
        if self.children:
            return sum(c.total_value for c in self.children)
        return self.value


@dataclass
class Treemap:
    roots: list[TreemapNode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        return sum(r.total_value for r in self.roots)
