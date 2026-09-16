"""Generate a terminal-width review corpus and Mermaid Live comparison links.

Run with PYTHONPATH=src python benchmarks/layout_quality.py --output-dir /tmp/layout-review.
No browser, JavaScript runtime, or network is required for terminal measurements.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import redirect_stderr, redirect_stdout
import html
import io
import json
from pathlib import Path
import zlib

from termaid import parse
from termaid.cli import main as cli_main
from termaid.utils import display_width


FIXTURES = Path(__file__).parent / "fixtures" / "layout"


def live_url(source: str, layout: str = "dagre") -> str:
    state = {"code": source, "mermaid": {"theme": "default", "layout": layout},
             "autoSync": True, "updateDiagram": True}
    payload = json.dumps(state, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(zlib.compress(payload)).decode("ascii").rstrip("=")
    return f"https://mermaid.live/edit#pako:{encoded}"


def build_review(output_directory: Path, baseline_directory: Path | None = None) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    measurements: list[dict[str, str | int]] = []
    reference_graphs: list[dict[str, object]] = []
    sections: list[str] = []
    fixture_paths = sorted(FIXTURES.glob("*.mmd")) + [
        FIXTURES.parents[2] / 'tests' / 'fixtures' / 'production_supervisor_state.mmd',
    ]
    for fixture_path in fixture_paths:
        source = fixture_path.read_text(encoding="utf-8")
        graph = parse(source)
        reference_graphs.append({
            "name": fixture_path.stem,
            "nodes": [{"id": node_id, "label": graph.nodes[node_id].label}
                      for node_id in graph.node_order],
            "edges": [{"source": edge.source, "target": edge.target,
                       "min_length": edge.min_length} for edge in graph.edges],
            "compound": bool(graph.subgraphs),
        })
        views: list[str] = []
        for width in (80, 120, 160):
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exit_code = cli_main([
                    str(fixture_path), "--width", str(width), "--strict-width",
                    "--fit-mode", "reflow", "--padding-x", "1", "--padding-y", "0",
                    "--gap", "2", "--format", "styled-json",
                ])
            diagnostic_text = stderr_buffer.getvalue()
            if exit_code:
                measurements.append({"sample": fixture_path.stem, "budget": width,
                                     "exit_code": exit_code, "diagnostic": diagnostic_text})
                views.append(f"<h3>{width} columns</h3><pre>{html.escape(diagnostic_text)}</pre>")
                continue
            document = json.loads(stdout_buffer.getvalue())
            lines = ["".join(chunk["text"] for chunk in row) for row in document["lines"]]
            rendered = "\n".join(lines).rstrip()
            crossings = sum(chunk["text"].count("x") for row in document["lines"] for chunk in row
                            if chunk["style"] == "edge")
            references = sum(line.startswith("[") and "] " in line for line in lines)
            measurement = {"sample": fixture_path.stem, "budget": width, "exit_code": 0,
                           "width": max(map(display_width, lines), default=0), "height": len(lines),
                           "crossings": crossings, "references": references}
            measurements.append(measurement)
            (output_directory / f"{fixture_path.stem}-{width}.txt").write_text(rendered + "\n", encoding="utf-8")
            baseline_view = ""
            if baseline_directory is not None:
                baseline_path = baseline_directory / f"{fixture_path.stem}-{width}.txt"
                if baseline_path.exists():
                    baseline_text = baseline_path.read_text(encoding="utf-8")
                    baseline_view = ('<details><summary>Before optimization</summary><pre>'
                                     + html.escape(baseline_text) + '</pre></details>')
            views.append(f'<div class="view" data-width="{width}"><h3>{width} columns · '
                         f'{measurement["width"]} × {measurement["height"]} cells · '
                         f'{crossings} crossings · {references} references</h3>'
                         f'<pre>{html.escape(rendered)}</pre>{baseline_view}</div>')
        sections.append(
            f'<section><h2>{html.escape(fixture_path.stem)}</h2>'
            f'<p><a href="{live_url(source)}">Mermaid Live: Dagre</a> · '
            f'<a href="{live_url(source, "elk")}">Mermaid Live: ELK</a></p>'
            f'<details><summary>Source</summary><pre>{html.escape(source)}</pre></details>'
            + "".join(views) + "</section>"
        )
    (output_directory / "metrics.json").write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    (output_directory / "graphs.json").write_text(json.dumps(reference_graphs, indent=2) + "\n", encoding="utf-8")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Termaid layout review</title><style>
body{font:16px system-ui;margin:2rem;color:#202630;background:#f6f7f9}section{background:white;padding:1rem;margin:1rem 0;border:1px solid #ddd}
pre{font:13px/1.35 monospace;overflow:auto;padding:1rem;background:#f0f2f5;white-space:pre}a{color:#195bb9}h3{font-size:14px}
</style><h1>Terminal layout review</h1>
<p>Compare hierarchy and grouping with Mermaid; terminal output must fit its column budget.
Fewer crossings, bends, or rows alone do not guarantee a better layout. Inspect labels and connection ownership too.
Live links open the original source; browser rendering is not a pixel target for terminal output.</p>
<label>Terminal width: <select id="width"><option>80</option><option selected>120</option><option>160</option></select></label>
''' + "".join(sections) + '''<script>
const selector=document.getElementById('width');
function selectWidth(){document.querySelectorAll('.view').forEach(view=>view.hidden=view.dataset.width!==selector.value)}
selector.addEventListener('change',selectWidth);selectWidth();
</script></html>'''
    (output_directory / "index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path)
    arguments = parser.parse_args()
    build_review(arguments.output_dir, arguments.baseline_dir)
