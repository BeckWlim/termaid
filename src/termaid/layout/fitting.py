"""Compare readable render candidates within an editor's output limits."""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..utils import display_width


@dataclass(frozen=True, order=True)
class FitScore:
    """Hard limits first, then references, readable nodes, and output height.

    Smaller is better. Width utilization is intentionally not an objective:
    growing a diagram is useful only when it improves its content.
    """
    width_overflow: int
    height_overflow: int
    references: int
    negative_label_budget: int
    height: int
    width: int


def score_render(
    text: str, width_limit: int, *, label_budget: int,
    height_limit: int | None = None,
) -> FitScore:
    lines = text.splitlines()
    width = max((display_width(line) for line in lines), default=0)
    height = len(lines)
    # Graph reference entries are anchored at column zero, below the drawing.
    # Count entries rather than occurrences of markers on the routes.
    _, separator, footer = text.rpartition("\n\n")
    references = sum(bool(re.match(r"^\[\d+\] \S", line))
                     for line in footer.splitlines()) if separator else 0
    return FitScore(max(0, width - width_limit),
                    max(0, height - height_limit) if height_limit is not None else 0,
                    references, -label_budget, height, width)
