"""Quality feedback stays bounded and respects editor output limits."""
from __future__ import annotations

from argparse import Namespace

import pytest

from termaid.cli import _auto_fit


def fitting_args(height_limit: int | None = None) -> Namespace:
    return Namespace(no_auto_fit=False, max_height=height_limit, fit_mode='reflow',
                     gap=2, padding_x=2, padding_y=0, ascii=False, sharp_edges=False,
                     inline_edge_labels=False, uniform_nodes=False, arrow_position='middle',
                     strict_width=True)


@pytest.mark.parametrize('invalid_retry', ['', 'width', 'height'])
def test_spacing_feedback_keeps_readable_candidate_within_both_limits(invalid_retry: str):
    calls: list[dict[str, object]] = []
    referenced = 'drawing\n\n[1] full message'
    inline = 'drawing with full message'

    def render_candidate(source: str, **options: object) -> str:
        calls.append(options)
        if options['gap'] == 3:
            if invalid_retry == 'width':
                return 'x' * 101
            if invalid_retry == 'height':
                return '\n'.join(['row'] * 6)
            return inline
        return referenced

    output = _auto_fit('x' * 120, 'source', fitting_args(5), render_candidate, target_width=100)
    assert output == (referenced if invalid_retry else inline)
    assert len(calls) <= 7  # Plus the initial render.
    assert sum(options['gap'] == 3 for options in calls) == 1
    assert all(options['arrow_position'] == 'middle' for options in calls)


def test_fitting_keeps_candidate_within_height_limit_even_with_smaller_label_budget():
    calls: list[dict[str, object]] = []
    short_output = 'message\narrow'
    tall_output = '\n'.join(['message'] * 10)

    def render_candidate(source: str, **options: object) -> str:
        calls.append(options)
        return short_output if options['max_label_width'] == 32 else tall_output

    output = _auto_fit(tall_output, 'source', fitting_args(4), render_candidate, target_width=100)
    assert output == short_output
    assert len(calls) <= 7


def test_vertical_fallback_preserves_eight_render_limit():
    calls: list[dict[str, object]] = []

    def render_candidate(source: str, **options: object) -> str:
        calls.append(options)
        return 'fits' if options['force_vertical'] else 'x' * 101

    output = _auto_fit('x' * 120, 'source', fitting_args(), render_candidate, target_width=100)
    assert output == 'fits'
    assert len(calls) <= 7
    assert sum(options['force_vertical'] is True for options in calls) == 1
