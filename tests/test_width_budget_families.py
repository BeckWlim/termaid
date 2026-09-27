"""Strict-width fitting of diagram families with scalable fixed geometry."""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from termaid import render
from termaid.cli import main
from termaid.utils import display_width


EXAMPLES = dict(re.findall(
    r"### ([^\n]+).*?```text\n(.*?)\n```",
    (Path(__file__).parent.parent / "docs" / "supported-diagrams.md").read_text(),
    re.S,
))


@pytest.mark.parametrize("name, content", [
    ("Gantt chart", ("Design", "Review", "Jan 01", "Jan 06")),
    ("Packet diagram", ("Source", "Destination", "15", "31")),
    ("Pie chart", ("Done", "Open", "60.0%", "40.0%")),
    ("Quadrant chart", ("Plan", "Ship")),
    ("XY chart", ("Mon", "Tue", "Wed")),
    ("Treemap", ("Project", "Code", "Tests")),
])
def test_fixed_geometry_scales_to_strict_40_columns(name, content, tmp_path, capsys):
    source_path = tmp_path / "example.mmd"
    source_path.write_text(EXAMPLES[name])
    assert main([str(source_path), "--width", "40", "--strict-width",
                 "--fit-mode", "reflow"]) == 0
    result = capsys.readouterr()
    assert not result.err
    assert max(map(display_width, result.out.splitlines())) <= 40
    assert all(text in result.out for text in content)


def test_packet_uses_complete_bit_rows_when_narrow():
    output = render('packet-beta\n  0-15: "Source"\n  16-31: "Destination"',
                    max_width=30)
    assert max(map(display_width, output.splitlines())) <= 30
    assert output.count("╭") == 2
    assert "Source" in output and "Destination" in output
    assert "15" in output and "16" in output and "31" in output


@pytest.mark.parametrize("source", [
    'gantt\n  title This title is much longer than twenty columns\n'
    '  section Build\n  Design :done, d1, 2024-01-01, 3d',
    'pie\n  title This title is much longer than twenty columns\n  "Done": 60',
    'quadrantChart\n  title This title is much longer than twenty columns\n'
    '  Plan: [0.2, 0.8]',
])
def test_impossible_title_reports_width_without_clipping(source, tmp_path, capsys):
    source_path = tmp_path / "example.mmd"
    source_path.write_text(source)
    assert main([str(source_path), "--width", "20", "--strict-width"]) == 2
    result = capsys.readouterr()
    assert not result.out
    assert "target is 20" in result.err
    assert "This title is much longer than twenty columns" in render(source, max_width=20)
