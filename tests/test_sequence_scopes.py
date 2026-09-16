"""Scope frames must enclose their own contents without clipping nested events."""
from __future__ import annotations

import pytest

from termaid import render
from termaid.parser.sequence import parse_sequence_diagram
from termaid.renderer.sequence import render_sequence
from termaid.utils import display_width


def frame_at(lines: list[str], label: str) -> tuple[int, int, int, int]:
    label_row = next(index for index, line in enumerate(lines) if label in line)
    top_row = label_row - 1
    left = lines[top_row].rindex("┌")
    right = lines[top_row].index("┐", left)
    bottom_row = next(
        index for index in range(label_row + 1, len(lines))
        if lines[index][left:left + 1] == "└"
    )
    assert lines[bottom_row][right:right + 1] == "┘"
    return left, right, top_row, bottom_row


@pytest.mark.parametrize("kind,branch", [("par", "and"), ("alt", "else"), ("critical", "option")])
def test_frame_covers_all_branches_but_excludes_unrelated_participants(kind: str, branch: str):
    source = f"""sequenceDiagram
participant A
participant B
participant C
participant D
participant E
A->>E: before
{kind} work
B->>C: one
{branch} other
C->>D: two
end
A->>E: after
"""
    lines = render(source).splitlines()
    centers = [lines[1].index(name) for name in "ABCDE"]
    left, right, top, bottom = frame_at(lines, f"[{kind}] work")
    assert centers[0] < left < centers[1]
    assert centers[3] < right < centers[4]
    assert next(index for index, line in enumerate(lines) if "before" in line) < top
    assert next(index for index, line in enumerate(lines) if "after" in line) > bottom
    for row in range(top + 1, bottom):
        assert lines[row][left] == lines[row][right] == "│"
    divider = next(line for line in lines if "[other]" in line)
    assert divider[left] == divider[right] == "│"


@pytest.mark.parametrize("depth", [3, 6])
@pytest.mark.parametrize("padding_x,gap", [(4, 16), (0, 4)])
def test_deep_frames_stay_outside_messages(depth: int, padding_x: int, gap: int):
    source = "\n".join([
        "sequenceDiagram", "participant A", "participant B",
        *(f"alt level{index}" for index in range(depth)),
        "A->>B: inside", *("end" for _ in range(depth)), "B->>A: outside",
    ])
    canvas = render_sequence(parse_sequence_diagram(source), padding_x=padding_x, gap=gap)
    lines = canvas.to_string().splitlines()
    frames = [frame_at(lines, f"[alt] level{index}") for index in range(depth)]
    for outer_frame, inner_frame in zip(frames, frames[1:]):
        outer_left, outer_right, outer_top, outer_bottom = outer_frame
        inner_left, inner_right, inner_top, inner_bottom = inner_frame
        assert outer_left < inner_left < inner_right < outer_right
        assert outer_top < inner_top < inner_bottom < outer_bottom
    inner_left, inner_right, inner_top, inner_bottom = frames[-1]
    arrow_row = next(line for line in lines[inner_top:inner_bottom] if "▶" in line)
    assert inner_left < arrow_row.index("─") < arrow_row.index("▶") < inner_right
    assert arrow_row[inner_left] == arrow_row[inner_right] == "│"


@pytest.mark.parametrize("event", [
    "A->>A: long self message",
    "Note left of A: long note",
    "Note right of B: long note",
    "Note over A,B: long spanning note",
])
def test_frame_encloses_notes_and_self_messages(event: str):
    source = f"sequenceDiagram\nparticipant A\nparticipant B\npar scope\n{event}\nend"
    lines = render(source).splitlines()
    left, right, top, bottom = frame_at(lines, "[par] scope")
    for row in range(top + 1, bottom):
        assert lines[row][left] == lines[row][right] == "│"
        assert not lines[row][:left].strip(" ┆")
        assert not lines[row][right + 1:].strip(" ┆")


def test_autonumbered_self_message_fits_inside_frame():
    source = "sequenceDiagram\nautonumber\npar work\nA->>A: thinking\nend"
    lines = render(source).splitlines()
    left, right, top, bottom = frame_at(lines, "[par] work")
    label_row = next(line for line in lines if "1: thinking" in line)
    assert left < label_row.index("1: thinking")
    assert label_row.index("1: thinking") + len("1: thinking") < right
    for row in lines[top + 1:bottom]:
        assert row[left] == row[right] == "│"


@pytest.mark.parametrize("use_ascii", [False, True])
def test_long_scope_and_branch_labels_fit_without_clipping(use_ascii: bool):
    source = """sequenceDiagram
participant A
participant B
alt a long condition whose entire title must remain visible
A->>B: yes
else another lengthy condition with a visible ending
B->>A: no
end
"""
    canvas = render_sequence(parse_sequence_diagram(source), use_ascii=use_ascii, max_label_width=12)
    output = canvas.to_string()
    assert "visible" in output and "ending" in output
    assert "yes" in output and "no" in output
    assert canvas.width < 45
    assert max(display_width(line) for line in output.splitlines()) <= canvas.width
    if not use_ascii:
        lines = output.splitlines()
        left, right, top, bottom = frame_at(lines, "[alt]")
        for row in lines[top + 1:bottom]:
            assert row[left] == row[right] == "│"


@pytest.mark.parametrize("kind", ["par", "alt", "opt", "loop", "critical", "break", "rect"])
def test_empty_scope_keeps_complete_label_and_borders(kind: str):
    output = render(f"sequenceDiagram\nparticipant A\n{kind} empty scope\nend")
    assert f"[{kind}] empty scope" in output
    left, right, top, bottom = frame_at(output.splitlines(), f"[{kind}]")
    assert left < right and top < bottom


@pytest.mark.parametrize("width", [32, 68, 100])
def test_styled_cli_keeps_nested_scopes_within_width(width: int, tmp_path, capsys):
    import json
    from termaid.cli import main

    source_path = tmp_path / "scopes.mmd"
    source_path.write_text("""sequenceDiagram
participant A
participant B
par outer condition with a long title
alt inner
A->>B: inside
else another long condition
B->>A: reply
end
and branch
B->>B: retry
end
A->>B: outside
""")
    exit_code = main([
        str(source_path), "--width", str(width), "--strict-width",
        "--fit-mode", "reflow", "--max-height", "4096", "--format", "styled-json",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    document = json.loads(captured.out)
    assert document["version"] == 1
    lines = ["".join(chunk["text"] for chunk in row) for row in document["lines"]]
    assert all(display_width(line) <= width for line in lines)
    outer_left, outer_right, outer_top, outer_bottom = frame_at(lines, "[par]")
    inner_left, inner_right, inner_top, inner_bottom = frame_at(lines, "[alt]")
    assert outer_left < inner_left < inner_right < outer_right
    assert outer_top < inner_top < inner_bottom < outer_bottom
    outside_row = next(index for index, line in enumerate(lines) if "outside" in line)
    assert outside_row > outer_bottom
