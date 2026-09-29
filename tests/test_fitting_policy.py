"""Quality feedback stays bounded and respects editor output limits."""
from __future__ import annotations

from termaid.core.canvas import DiagramPlan
from termaid.core.contracts import RenderConfig

import pytest

from termaid.layout.fitting import FitOptions, fit


def plan_text(text: str) -> DiagramPlan:
    return DiagramPlan(tuple(tuple((character, "default") for character in line)
                             for line in text.splitlines()))


def fitting_config() -> RenderConfig:
    return RenderConfig(gap=2, padding_x=2, padding_y=0, arrow_position='middle')


@pytest.mark.parametrize('invalid_retry', ['', 'width', 'height'])
def test_spacing_feedback_keeps_readable_candidate_within_both_limits(invalid_retry: str):
    calls: list[RenderConfig] = []
    referenced = 'drawing\n\n[1] full message'
    inline = 'drawing with full message'

    def render_candidate(options: RenderConfig) -> DiagramPlan:
        calls.append(options)
        if options.gap == 3:
            if invalid_retry == 'width':
                return plan_text('x' * 101)
            if invalid_retry == 'height':
                return plan_text('\n'.join(['row'] * 6))
            return plan_text(inline)
        return plan_text(referenced)

    output = fit(plan_text('x' * 120), render_candidate, fitting_config(), FitOptions(100, 'reflow', 5))
    assert output.plan.to_string() == (referenced if invalid_retry else inline)
    assert len(calls) <= 7  # Plus the initial render.
    assert sum(options.gap == 3 for options in calls) == 1
    assert all(options.arrow_position == 'middle' for options in calls)


def test_fitting_keeps_candidate_within_height_limit_even_with_smaller_label_budget():
    calls: list[RenderConfig] = []
    short_output = 'message\narrow'
    tall_output = '\n'.join(['message'] * 10)

    def render_candidate(options: RenderConfig) -> DiagramPlan:
        calls.append(options)
        return plan_text(short_output if options.max_label_width == 32 else tall_output)

    output = fit(plan_text(tall_output), render_candidate, fitting_config(), FitOptions(100, 'reflow', 4))
    assert output.plan.to_string() == short_output
    assert len(calls) <= 7


def test_vertical_fallback_preserves_eight_render_limit():
    calls: list[RenderConfig] = []

    def render_candidate(options: RenderConfig) -> DiagramPlan:
        calls.append(options)
        return plan_text('fits' if options.force_vertical else 'x' * 101)

    output = fit(plan_text('x' * 120), render_candidate, fitting_config(), FitOptions(100, 'reflow'))
    assert output.plan.to_string() == 'fits'
    assert len(calls) <= 7
    assert sum(options.force_vertical is True for options in calls) == 1
