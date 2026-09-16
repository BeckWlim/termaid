"""Machine-readable failures at the editor subprocess boundary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from termaid.cli import main


@pytest.mark.parametrize("output_format", ["text", "styled-json"])
@pytest.mark.parametrize("constraint,code,detail", [
    (["--width", "1", "--strict-width"], "width_exceeded", "width"),
    (["--max-height", "1"], "height_exceeded", "height"),
])
def test_constraints_emit_one_diagnostic_and_preserve_output_file(
    tmp_path: Path, capsys, output_format: str,
    constraint: list[str], code: str, detail: str,
):
    source_path = tmp_path / "input.mmd"
    source_path.write_text("graph TD\n  A --> B\n", encoding="utf-8")
    output_path = tmp_path / "output.txt"
    output_path.write_text("previous result", encoding="utf-8")
    exit_code = main([
        str(source_path), "--diagnostics-format", "json",
        "--format", output_format, "-o", str(output_path), *constraint,
    ])
    captured = capsys.readouterr()
    diagnostic = json.loads(captured.err)
    assert exit_code == diagnostic["exit_code"] == 2
    assert diagnostic["version"] == 1
    assert diagnostic["severity"] == "error"
    assert diagnostic["code"] == code
    assert diagnostic["details"][f"actual_{detail}"] > diagnostic["details"][f"max_{detail}"] == 1
    assert captured.out == ""
    assert output_path.read_text(encoding="utf-8") == "previous result"


@pytest.mark.parametrize("arguments,source,expected_code,expected_exit", [
    (["--unknown-option"], "graph LR; A-->B", "invalid_arguments", 2),
    (["--width", "bad"], "graph LR; A-->B", "invalid_arguments", 2),
    (["--width", "0"], "graph LR; A-->B", "invalid_arguments", 2),
    (["--strict-width"], "graph LR; A-->B", "invalid_arguments", 2),
    (["--max-height", "0"], "graph LR; A-->B", "invalid_arguments", 2),
    ([], "  \n", "input_empty", 1),
    ([], "not a diagram", "render_empty", 1),
    (["--json", "flowchart"], "{bad json", "input_conversion_failed", 1),
])
def test_subprocess_failures_are_json_on_stderr(
    arguments: list[str], source: str, expected_code: str, expected_exit: int,
):
    completed = subprocess.run(
        [sys.executable, "-m", "termaid", *arguments,
         "--diagnostics-format=json", "--format", "styled-json"],
        input=source, capture_output=True, text=True, check=False,
    )
    diagnostic = json.loads(completed.stderr)
    assert completed.returncode == diagnostic["exit_code"] == expected_exit
    assert diagnostic["code"] == expected_code
    assert diagnostic["message"]
    assert completed.stdout == ""


def test_io_errors_are_distinguishable(tmp_path: Path, capsys):
    source_path = tmp_path / "input.mmd"
    arguments = [str(source_path), "--diagnostics-format", "json"]
    assert main(arguments) == 1
    missing = json.loads(capsys.readouterr().err)
    assert missing["code"] == "input_not_found"
    assert missing["details"]["path"] == str(source_path)

    source_path.write_bytes(b"\xff")
    assert main(arguments) == 1
    unreadable = json.loads(capsys.readouterr().err)
    assert unreadable["code"] == "input_read_failed"

    source_path.write_text("graph LR; A-->B", encoding="utf-8")
    assert main([*arguments, "--format", "styled-json", "-o", str(tmp_path)]) == 1
    unwritable = json.loads(capsys.readouterr().err)
    assert unwritable["code"] == "output_write_failed"


@pytest.mark.parametrize("exception_type", [RuntimeError, OSError])
@pytest.mark.parametrize("output_format", ["text", "styled-json"])
def test_renderer_exceptions_are_not_misclassified_as_io_errors(
    tmp_path: Path, capsys, monkeypatch,
    exception_type: type[Exception], output_format: str,
):
    import termaid.layout.engine as engine

    def fail(*args: object, **kwargs: object) -> None:
        raise exception_type("failure\nwith details")

    monkeypatch.setattr(engine, "plan", fail)
    source_path = tmp_path / "input.mmd"
    source_path.write_text("graph LR; A-->B", encoding="utf-8")
    assert main([str(source_path), "--diagnostics-format", "json", "--format", output_format]) == 1
    captured = capsys.readouterr()
    diagnostic = json.loads(captured.err)
    assert len(captured.err.splitlines()) == 1
    assert diagnostic["code"] == "render_failed"
    assert diagnostic["details"]["exception_type"] == exception_type.__name__
    assert "failure\nwith details" in diagnostic["message"]
    assert captured.out == ""


def test_warning_keeps_successful_styled_output(tmp_path: Path, capsys):
    source_path = tmp_path / "input.mmd"
    source_path.write_text("graph LR; A-->B", encoding="utf-8")
    assert main([str(source_path), "--width", "1", "--diagnostics-format", "json",
                 "--format", "styled-json"]) == 0
    captured = capsys.readouterr()
    warning = json.loads(captured.err)
    assert warning["severity"] == "warning"
    assert warning["code"] == "width_exceeded"
    assert warning["exit_code"] == 0
    assert json.loads(captured.out)["lines"]


def test_success_keeps_existing_styled_schema(tmp_path: Path, capsys):
    source_path = tmp_path / "input.mmd"
    source_path.write_text("graph LR; A-->B", encoding="utf-8")
    assert main([str(source_path), "--diagnostics-format", "json", "--format", "styled-json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert set(json.loads(captured.out)) == {"version", "lines"}
