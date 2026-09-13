"""Contract tests for semantic styled JSON output."""
from __future__ import annotations

from pathlib import Path

import pytest

from termaid import render
from termaid.output.styled import render_styled


FIXTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.mmd"))


def _plain(styled: dict) -> str:
    return "\n".join(
        "".join(chunk["text"] for chunk in line)
        for line in styled["lines"]
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_semantic_chunks_preserve_every_fixture_canvas(fixture: Path):
    source = fixture.read_text()
    styled = render_styled(source)
    assert styled["version"] == 1
    assert _plain(styled) == render(source)
    assert all(
        set(chunk) == {"text", "style"}
        and chunk["text"]
        and "\x1b" not in chunk["text"]
        for line in styled["lines"]
        for chunk in line
    )
