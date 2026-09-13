"""Tests for the CLI interface."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from termaid.cli import main
from termaid.utils import display_width


class TestCliMain:
    def test_file_input(self, tmp_path: Path):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A --> B")
        result = main([str(mmd)])
        assert result == 0

    def test_missing_file(self):
        result = main(["/nonexistent/file.mmd"])
        assert result == 1

    def test_ascii_flag(self, tmp_path: Path):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A --> B")
        result = main([str(mmd), "--ascii"])
        assert result == 0

    def test_version_flag(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0

    def test_empty_file(self, tmp_path: Path):
        mmd = tmp_path / "empty.mmd"
        mmd.write_text("")
        result = main([str(mmd)])
        assert result == 1

    def test_padding_flags(self, tmp_path: Path):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A --> B")
        result = main([str(mmd), "--padding-x", "6", "--padding-y", "3"])
        assert result == 0


class TestCliOutput:
    def test_styled_json_is_semantic_and_independent_of_rich(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        mmd = tmp_path / "styled.mmd"
        mmd.write_text("graph LR\n  A[Start] -->|yes| B[Done]\n")
        monkeypatch.setenv("NO_COLOR", "1")
        result = main([str(mmd), "--format", "styled-json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        chunks = [chunk for line in payload["lines"] for chunk in line]
        assert result == 0
        assert captured.err == ""
        assert payload["version"] == 1
        assert {chunk["style"] for chunk in chunks} >= {
            "node", "edge", "arrow", "edge_label"
        }
        assert "Start" in "".join(chunk["text"] for chunk in chunks)
        assert "\x1b" not in captured.out

    def test_output_flag(self, tmp_path: Path):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A --> B")
        out_file = tmp_path / "result.txt"
        result = main([str(mmd), "-o", str(out_file)])
        assert result == 0
        content = out_file.read_text()
        assert "A" in content
        assert "B" in content

    def test_output_bad_path(self, tmp_path: Path):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A --> B")
        result = main([str(mmd), "-o", "/nonexistent/dir/out.txt"])
        assert result == 1


class TestCliWidth:
    def test_width_flag_compacts(self, tmp_path: Path, capsys):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A-->B-->C-->D-->E-->F-->G-->H")
        result = main([str(mmd), "--width", "70"])
        assert result == 0
        output = capsys.readouterr().out
        max_w = max(len(line) for line in output.split("\n"))
        assert max_w <= 70

    def test_width_flag_no_change_if_fits(self, tmp_path: Path, capsys):
        mmd = tmp_path / "test.mmd"
        mmd.write_text("graph LR\n  A-->B")
        result = main([str(mmd), "--width", "200"])
        assert result == 0

    def test_strict_width_requires_explicit_target(self, capsys):
        result = main(["--strict-width"])
        captured = capsys.readouterr()
        assert result == 2
        assert captured.out == ""
        assert "requires --width" in captured.err

    def test_strict_width_reflows_and_wraps_long_tokens(self, tmp_path: Path, capsys):
        mmd = tmp_path / "long-token-flow.mmd"
        mmd.write_text(
            "flowchart LR\n"
            "  A[StartProcessingWithoutSpaces] --> "
            "B[ContinueProcessingWithoutSpaces] --> C[Done]\n"
        )
        result = main([
            str(mmd), "--width", "40", "--strict-width",
            "--fit-mode", "reflow",
        ])
        captured = capsys.readouterr()
        assert result == 0
        assert captured.err == ""
        assert "►" in captured.out
        assert all(display_width(line) <= 40 for line in captured.out.splitlines())

    def test_strict_width_wraps_sequence_text(self, tmp_path: Path, capsys):
        mmd = tmp_path / "sequence.mmd"
        mmd.write_text(
            "sequenceDiagram\n"
            "  participant A as AlphaLongParticipant\n"
            "  participant B as BetaLongParticipant\n"
            "  A->>B: LongMessageWithoutAnySpacesInIt\n"
        )
        result = main([
            str(mmd), "--width", "40", "--strict-width",
            "--fit-mode", "reflow",
        ])
        captured = capsys.readouterr()
        assert result == 0
        assert captured.err == ""
        assert "►" in captured.out
        assert all(display_width(line) <= 40 for line in captured.out.splitlines())

    def test_strict_width_uses_available_sequence_width(self, tmp_path: Path, capsys):
        mmd = tmp_path / "adaptive-sequence.mmd"
        mmd.write_text(
            "sequenceDiagram\n"
            "  participant A as Request Client\n"
            "  participant B as Storage Client\n"
            "  participant C as Metadata Service\n"
            "  participant D as Shard Lock\n"
            "  participant E as Eviction Worker\n"
            "  A->>B: Start a storage request\n"
            "  B->>C: Resolve replica metadata and acquire lease\n"
            "  C->>D: Wait for shared shard access\n"
            "  E->>D: Apply eviction candidate under exclusive access\n"
            "  D-->>C: Release shared access\n"
            "  C-->>B: Return the selected replica descriptor\n"
            "  B-->>A: Complete payload transfer and validation\n"
        )
        result = main([
            str(mmd), "--width", "120", "--strict-width",
            "--fit-mode", "reflow",
        ])
        captured = capsys.readouterr()
        rendered_width = max(
            display_width(line) for line in captured.out.splitlines()
        )
        assert result == 0
        assert captured.err == ""
        assert 108 <= rendered_width <= 120

    def test_strict_width_never_emits_oversized_canvas(self, tmp_path: Path, capsys):
        mmd = tmp_path / "impossible.mmd"
        mmd.write_text(
            "sequenceDiagram\n"
            "  participant A\n"
            "  participant B\n"
            "  participant C\n"
            "  participant D\n"
            "  participant E\n"
        )
        result = main([
            str(mmd), "--width", "8", "--strict-width",
            "--fit-mode", "reflow",
        ])
        captured = capsys.readouterr()
        assert result == 2
        assert captured.out == ""
        assert "target is 8" in captured.err

    def test_max_height_never_emits_oversized_canvas(self, tmp_path: Path, capsys):
        mmd = tmp_path / "tall.mmd"
        mmd.write_text("graph TD\n  A --> B --> C\n")
        result = main([str(mmd), "--max-height", "2"])
        captured = capsys.readouterr()
        assert result == 2
        assert captured.out == ""
        assert "exceeds 2 output rows" in captured.err


class TestCliNoColor:
    def test_no_color_env(self):
        from termaid.cli import _use_color
        import argparse, os
        old = os.environ.get("NO_COLOR")
        try:
            os.environ["NO_COLOR"] = "1"
            args = argparse.Namespace(theme="neon")
            assert _use_color(args) is False
        finally:
            if old is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = old


class TestCliPipe:
    def test_pipe_input(self):
        result = subprocess.run(
            [sys.executable, "-m", "termaid"],
            input="graph LR\n  A --> B",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "A" in result.stdout
        assert "B" in result.stdout

    def test_pipe_ascii(self):
        result = subprocess.run(
            [sys.executable, "-m", "termaid", "--ascii"],
            input="graph LR\n  A --> B",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "+" in result.stdout  # ASCII box char
        assert "┌" not in result.stdout  # No unicode

    def test_pipe_chain(self):
        result = subprocess.run(
            [sys.executable, "-m", "termaid"],
            input="graph LR\n  A --> B --> C --> D",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "A" in result.stdout
        assert "D" in result.stdout


def _boom(*args, **kwargs):
    raise RuntimeError("internal failure")


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestRenderErrorPropagation:
    def test_render_raises_on_internal_error(self, monkeypatch):
        import termaid.output.text as text_out
        monkeypatch.setattr(text_out, "render_text", _boom)
        from termaid import render
        with pytest.raises(RuntimeError, match="internal failure"):
            render("graph LR\n  A --> B")

    def test_render_failure_exits_nonzero(self, tmp_path: Path, monkeypatch, capsys):
        import termaid.output.text as text_out
        monkeypatch.setattr(text_out, "render_text", _boom)
        mmd = tmp_path / "t.mmd"
        mmd.write_text("graph LR\n  A --> B")
        result = main([str(mmd)])
        captured = capsys.readouterr()
        assert result == 1
        assert "internal failure" in captured.err
        assert "Failed to render" not in captured.out

    def test_render_failure_does_not_write_output_file(self, tmp_path: Path, monkeypatch):
        import termaid.output.text as text_out
        monkeypatch.setattr(text_out, "render_text", _boom)
        mmd = tmp_path / "t.mmd"
        mmd.write_text("graph LR\n  A --> B")
        out = tmp_path / "out.txt"
        result = main([str(mmd), "-o", str(out)])
        assert result == 1
        assert not out.exists()


class TestThemeOptionInteractions:
    """--theme must not silently drop -o, --show-ids, --gap, or --width."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        pytest.importorskip("rich")
        monkeypatch.delenv("NO_COLOR", raising=False)

    def _render_to_file(self, tmp_path: Path, source: str, extra_args: list[str], name: str = "out.txt") -> str:
        mmd = tmp_path / "t.mmd"
        mmd.write_text(source)
        out = tmp_path / name
        result = main([str(mmd), "--theme", "default", "-o", str(out), *extra_args])
        assert result == 0
        assert out.exists()
        return _strip_ansi(out.read_text())

    def test_theme_respects_output_file(self, tmp_path: Path, capsys):
        content = self._render_to_file(tmp_path, "graph LR\n  A --> B", [])
        assert "A" in content and "B" in content
        assert capsys.readouterr().out == ""

    def test_theme_respects_show_ids(self, tmp_path: Path):
        content = self._render_to_file(
            tmp_path, "graph LR\n  A[Start] --> B[End]", ["--show-ids"]
        )
        assert "A: Start" in content

    def test_theme_respects_gap(self, tmp_path: Path):
        source = "graph LR\n  A --> B --> C"
        wide = self._render_to_file(tmp_path, source, ["--gap", "8"], "wide.txt")
        narrow = self._render_to_file(tmp_path, source, ["--gap", "1"], "narrow.txt")
        def max_width(text: str) -> int:
            return max(len(line) for line in text.splitlines())
        assert max_width(narrow) < max_width(wide)

    def test_theme_respects_width(self, tmp_path: Path):
        source = "graph LR\n  A[aaaa] --> B[bbbb] --> C[cccc] --> D[dddd]"
        full = self._render_to_file(tmp_path, source, [], "full.txt")
        fitted = self._render_to_file(tmp_path, source, ["--width", "40"], "fitted.txt")
        def max_width(text: str) -> int:
            return max(len(line) for line in text.splitlines())
        assert max_width(fitted) < max_width(full)
