"""Measured label placements shared by graph and sequence layouts.

Planning reads geometry without painting over it. A complete plan is checked
again before any text is committed, so a failed placement cannot leave fragments.
Coordinates and rectangle dimensions are terminal display cells.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from functools import cached_property
from typing import Protocol

from ..utils import display_width


class LabelSurface(Protocol):
    width: int
    height: int

    def get(self, row: int, col: int) -> str: ...
    def is_protected(self, row: int, col: int) -> bool: ...
    def resize(self, new_width: int, new_height: int) -> None: ...
    def put_text(
        self, row: int, col: int, text: str, style: str = "",
        overwrite_spaces: bool = False,
    ) -> None: ...


@dataclass(frozen=True)
class TextPlacement:
    owner: str
    row: int
    col: int
    lines: tuple[str, ...]
    style: str = "edge_label"
    inline: bool = False

    @cached_property
    def line_widths(self) -> tuple[int, ...]:
        return tuple(display_width(line) for line in self.lines)

    @cached_property
    def width(self) -> int:
        return max(self.line_widths, default=0)

    @property
    def height(self) -> int:
        return len(self.lines)

    def cells(self) -> Iterator[tuple[int, int]]:
        for offset, line_width in enumerate(self.line_widths):
            for column in range(self.col, self.col + line_width):
                yield self.row + offset, column


def placement_is_clear(
    surface: LabelSurface, placement: TextPlacement, *, max_width: int | None = None,
) -> bool:
    if placement.row < 0 or placement.col < 0:
        return False
    if max_width is not None and placement.col + placement.width > max_width:
        return False
    for row, col in placement.cells():
        if surface.is_protected(row, col):
            return False
        character = surface.get(row, col)
        if character != " " and not (placement.inline and character in "─┄━│┆┃-|"):
            return False
    return True


class LabelPlan:
    """Read-only geometry plus reserved text rectangles with stable owners.

The surface methods let existing graph placement heuristics propose labels
without changing their geometry. Reservations appear occupied to later labels.
"""

    def __init__(self, geometry: LabelSurface, max_width: int | None = None) -> None:
        self.geometry = geometry
        self.max_width = max_width
        self.width = geometry.width
        self.height = geometry.height
        self.owner = "label"
        self.placements: list[TextPlacement] = []
        self._occupied: set[tuple[int, int]] = set()

    def get(self, row: int, col: int) -> str:
        return "#" if (row, col) in self._occupied else self.geometry.get(row, col)

    def is_protected(self, row: int, col: int) -> bool:
        return (row, col) in self._occupied or self.geometry.is_protected(row, col)

    def resize(self, new_width: int, new_height: int) -> None:
        self.width = max(self.width, new_width)
        self.height = max(self.height, new_height)

    def add(self, placement: TextPlacement) -> bool:
        if not placement_is_clear(self, placement, max_width=self.max_width):
            return False
        self.placements.append(placement)
        self._occupied.update(placement.cells())
        self.resize(placement.col + placement.width, placement.row + placement.height)
        return True

    def put_text(
        self, row: int, col: int, text: str, style: str = "",
        overwrite_spaces: bool = False,
    ) -> None:
        # Graph callers have already checked whether inline placement is allowed.
        # Record that permission only for cells containing an existing connector.
        inline = any(self.geometry.get(row, column) != " "
                     for column in range(col, col + display_width(text)))
        placement = TextPlacement(self.owner, row, col, (text,), style, inline)
        if not self.add(placement):
            raise ValueError(f"Label placement conflicts with geometry: {self.owner}")

    def paint(self, target: LabelSurface) -> None:
        # Validate the entire batch before writing anything, including against
        # geometry painted after planning (notes, frames, and arrowheads).
        for placement in self.placements:
            if not placement_is_clear(target, placement, max_width=self.max_width):
                raise ValueError(f"Label placement conflicts with geometry: {placement.owner}")
        target.resize(self.width, self.height)
        for placement in self.placements:
            for offset, line in enumerate(placement.lines):
                target.put_text(placement.row + offset, placement.col, line,
                                style=placement.style, overwrite_spaces=True)
