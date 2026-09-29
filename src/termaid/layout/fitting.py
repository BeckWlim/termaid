"""Compare readable render candidates within an editor's output limits."""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Callable, Literal

from termaid.utils import display_width
from termaid.core.canvas import DiagramPlan
from termaid.core.contracts import RenderConfig


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


@dataclass(frozen=True)
class FitOptions:
    width: int
    mode: Literal["compact", "wrap", "reflow"] = "compact"
    max_height: int | None = None

    def __post_init__(self) -> None:
        if self.width < 1:
            raise ValueError("Fit width must be positive")
        if self.max_height is not None and self.max_height < 1:
            raise ValueError("Fit height must be positive")
        if self.mode not in ("compact", "wrap", "reflow"):
            raise ValueError(f"Unknown fitting mode: {self.mode!r}")


@dataclass(frozen=True)
class FitResult:
    plan: DiagramPlan
    score: FitScore
    attempts: int


def fit(
    initial_plan: DiagramPlan,
    render_candidate: Callable[[RenderConfig], DiagramPlan],
    config: RenderConfig,
    options: FitOptions,
) -> FitResult:
    """Choose one candidate in at most eight attempts, including the initial plan.

    The caller owns source preparation, terminal policy and diagnostics. The
    callback receives independent immutable options for each rendering attempt.
    """
    attempts = 1

    def score(candidate: DiagramPlan, label_budget: int = 65) -> FitScore:
        return score_render(candidate.to_string(), options.width,
                            label_budget=label_budget, height_limit=options.max_height)

    def candidate(*, gap: int, padding_x: int, label_width: int | None = None,
                  force_vertical: bool = False) -> DiagramPlan:
        nonlocal attempts
        attempts += 1
        candidate_config = replace(config, gap=gap, padding_x=padding_x,
                                   max_label_width=label_width, force_vertical=force_vertical,
                                   max_width=options.width)
        return render_candidate(candidate_config)

    initial_score = score(initial_plan)
    if initial_score.width_overflow == 0 and (
        options.mode == "compact" or initial_score.references == initial_score.height_overflow == 0
    ):
        return FitResult(initial_plan, initial_score, attempts)

    best_plan = initial_plan
    best_score = initial_score
    if options.mode == "compact":
        for candidate_gap, candidate_padding in ((min(config.gap, 2), config.padding_x), (1, 0)):
            compact_plan = candidate(gap=candidate_gap, padding_x=candidate_padding)
            compact_score = score(compact_plan)
            if compact_score < best_score:
                best_plan, best_score = compact_plan, compact_score
            if compact_score.width_overflow == 0:
                return FitResult(compact_plan, compact_score, attempts)
    else:
        lower = 1
        upper = min(options.width, 64)
        for _ in range(6):
            if lower > upper:
                break
            label_width = (lower + upper) // 2
            wrapped_plan = candidate(gap=1, padding_x=0, label_width=label_width)
            wrapped_score = score(wrapped_plan, label_width)
            if wrapped_score < best_score:
                best_plan, best_score = wrapped_plan, wrapped_score
            if wrapped_score.width_overflow == 0:
                lower = label_width + 1
            else:
                upper = label_width - 1

        if best_score.width_overflow == 0 and best_score.height_overflow == 0:
            if best_score.references:
                spaced_budget = -best_score.negative_label_budget
                spaced_plan = candidate(gap=3, padding_x=0, label_width=spaced_budget)
                spaced_score = score(spaced_plan, spaced_budget)
                if spaced_score < best_score:
                    return FitResult(spaced_plan, spaced_score, attempts)
            return FitResult(best_plan, best_score, attempts)

        if options.mode == "reflow":
            vertical_budget = max(1, min(64, options.width - 2))
            vertical_plan = candidate(gap=1, padding_x=0, label_width=vertical_budget,
                                      force_vertical=True)
            vertical_score = score(vertical_plan, vertical_budget)
            if vertical_score < best_score:
                best_plan, best_score = vertical_plan, vertical_score

    return FitResult(best_plan, best_score, attempts)
