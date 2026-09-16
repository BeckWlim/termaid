"""CLI entry point for termaid."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from contextlib import nullcontext
from typing import TYPE_CHECKING, Callable, NoReturn, TypeVar
from .diagnostics import Diagnostic
from .utils import display_width
from .layout.engine import DiagramPlan
from .layout.fitting import score_render

if TYPE_CHECKING:
    from rich.text import Text


RenderResult = TypeVar("RenderResult", str, DiagramPlan)


class _ArgumentParser(argparse.ArgumentParser):
    diagnostics_format = "text"

    def error(self, message: str) -> NoReturn:
        if self.diagnostics_format == "json":
            Diagnostic("invalid_arguments", message, exit_code=2).emit("json")
            self.exit(2)
        super().error(message)


def _report(
    args: argparse.Namespace, code: str, message: str,
    *, exit_code: int = 1, **details: str | int,
) -> int:
    return Diagnostic(code, message, exit_code=exit_code, details=details).emit(
        args.diagnostics_format
    )


def _check_output(text: str, args: argparse.Namespace) -> int | None:
    if not text.strip():
        return _report(args, "render_empty", "Input produced no renderable diagram.")
    actual_width = _max_line_width(text)
    actual_height = len(text.splitlines())
    if args.strict_width and args.width is not None and actual_width > args.width:
        return _report(
            args, "width_exceeded",
            f"diagram is {actual_width} cols wide but target is {args.width}. "
            "Try: less -S, or use 'graph TD' for vertical layout.",
            exit_code=2, actual_width=actual_width, max_width=args.width,
        )
    if args.max_height is not None and actual_height > args.max_height:
        return _report(
            args, "height_exceeded",
            f"diagram exceeds {args.max_height} output rows.",
            exit_code=2, actual_height=actual_height, max_height=args.max_height,
        )
    return None


def _get_version() -> str:
    """Get version from package metadata, falling back to the source version."""
    try:
        from importlib.metadata import version
        return version("termaid")
    except Exception:
        from termaid import __version__
        return __version__


def _max_line_width(text: str) -> int:
    """Return the width of the longest line in text."""
    return max((display_width(line) for line in text.split("\n")), default=0)


def _plain(result: str | DiagramPlan) -> str:
    """Measure canonical geometry, independently of the output adapter."""
    return result if isinstance(result, str) else result.to_string()


def _auto_fit(
    result: RenderResult,
    source: str,
    args: argparse.Namespace,
    render_fn: Callable[..., RenderResult],
    target_width: int | None = None,
) -> RenderResult:
    """Re-render with smaller gap/padding if the diagram exceeds target width.

    target_width: explicit width limit (from --width), or None to use
    terminal width.  Disabled when --no-auto-fit is set or output is
    not a terminal (unless --width is explicitly given).
    """
    if target_width is None and (args.no_auto_fit or not sys.stdout.isatty()):
        return result
    width_limit = target_width if target_width is not None else shutil.get_terminal_size().columns
    initial_score = score_render(_plain(result), width_limit, label_budget=65,
                                 height_limit=args.max_height)
    if initial_score.width_overflow == 0 and (
        args.fit_mode == "compact" or initial_score.references == initial_score.height_overflow == 0
    ):
        return result

    def render_candidate(*, gap: int, padding_x: int, label_width: int | None = None,
                         force_vertical: bool = False) -> RenderResult:
        return render_fn(
            source,
            use_ascii=args.ascii,
            padding_x=padding_x,
            padding_y=args.padding_y,
            rounded_edges=not args.sharp_edges,
            gap=gap,
            inline_edge_labels=args.inline_edge_labels,
            uniform_nodes=args.uniform_nodes,
            arrow_position=args.arrow_position,
            max_width=width_limit,
            max_label_width=label_width,
            force_vertical=force_vertical,
        )

    best_result = result
    best_score = initial_score
    if args.fit_mode == "compact":
        # Spacing-only mode preserves labels and attempts at most three layouts.
        for candidate_gap, candidate_padding in ((min(args.gap, 2), args.padding_x), (1, 0)):
            candidate = render_candidate(gap=candidate_gap, padding_x=candidate_padding)
            candidate_score = score_render(_plain(candidate), width_limit, label_budget=65,
                                           height_limit=args.max_height)
            if candidate_score < best_score:
                best_result, best_score = candidate, candidate_score
            if candidate_score.width_overflow == 0:
                return candidate
    else:
        # Keep the eight-render bound: initial + six measured candidates +
        # optional spacing/reflow retry. Compare every visited candidate by quality.
        lower = 1
        upper = min(width_limit, 64)
        for _ in range(6):
            if lower > upper:
                break
            label_width = (lower + upper) // 2
            candidate = render_candidate(gap=1, padding_x=0, label_width=label_width)
            candidate_score = score_render(_plain(candidate), width_limit,
                                           label_budget=label_width, height_limit=args.max_height)
            if candidate_score < best_score:
                best_result, best_score = candidate, candidate_score
            if candidate_score.width_overflow == 0:
                lower = label_width + 1
            else:
                upper = label_width - 1

        if best_score.width_overflow == 0 and best_score.height_overflow == 0:
            if best_score.references:
                # Feed label failures back into layout once. Extra routing
                # space may remove references without shrinking node names.
                spaced_budget = -best_score.negative_label_budget
                spaced_result = render_candidate(gap=3, padding_x=0,
                                                 label_width=spaced_budget)
                spaced_score = score_render(_plain(spaced_result), width_limit,
                                            label_budget=spaced_budget, height_limit=args.max_height)
                if spaced_score < best_score:
                    return spaced_result
            return best_result

        if args.fit_mode == "reflow":
            vertical_budget = max(1, min(64, width_limit - 2))
            vertical_result = render_candidate(gap=1, padding_x=0, label_width=vertical_budget,
                                               force_vertical=True)
            vertical_score = score_render(_plain(vertical_result), width_limit,
                                          label_budget=vertical_budget, height_limit=args.max_height)
            if vertical_score < best_score:
                best_result, best_score = vertical_result, vertical_score

    if best_score.width_overflow > 0 and not args.strict_width:
        Diagnostic(
            "width_exceeded",
            f"diagram is {best_score.width} cols wide "
            f"but target is {width_limit}. "
            f"Try: less -S, or use 'graph TD' for vertical layout.",
            exit_code=0, severity="warning",
            details={"actual_width": best_score.width, "max_width": width_limit},
        ).emit(args.diagnostics_format)
    return best_result


def _read_source(args: argparse.Namespace) -> str | None:
    """Read diagram source from file or stdin. Returns None on error."""
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            _report(args, "input_not_found", f"File not found: {args.file}", path=args.file)
            return None
        except (OSError, UnicodeDecodeError) as e:
            _report(args, "input_read_failed", f"Error reading file: {e}", path=args.file)
            return None
    elif not sys.stdin.isatty():
        try:
            return sys.stdin.read()
        except (OSError, UnicodeDecodeError) as e:
            _report(args, "input_read_failed", f"Error reading stdin: {e}")
            return None
    else:
        _report(args, "input_missing", "No input provided. Pass a file or pipe input.")
        return None


def _use_color(args: argparse.Namespace) -> bool:
    """Determine whether to use color output, respecting NO_COLOR."""
    if args.theme is None:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    # Resolve the diagnostic transport before parsing other options, so even
    # argparse failures can be consumed by an editor's process callback.
    diagnostic_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    diagnostic_parser.add_argument("--diagnostics-format", default="text")
    diagnostic_args, _ = diagnostic_parser.parse_known_args(argv)
    parser = _ArgumentParser(
        prog="termaid",
        description="Render Mermaid diagrams as Unicode art in the terminal",
    )
    parser.diagnostics_format = diagnostic_args.diagnostics_format
    parser.add_argument(
        "--diagnostics-format", choices=["text", "json"], default="text",
        help="Emit human-readable diagnostics or versioned JSON lines on stderr.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Mermaid diagram file (.mmd). Reads from stdin if not provided.",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="Use ASCII characters instead of Unicode box-drawing",
    )
    parser.add_argument(
        "--padding-x",
        type=int,
        default=4,
        help="Horizontal padding inside node boxes (default: 4)",
    )
    parser.add_argument(
        "--padding-y",
        type=int,
        default=2,
        help="Vertical padding inside node boxes (default: 2)",
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=4,
        help="Space between nodes (default: 4). Use 1 or 2 for compact diagrams.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Target output width in terminal display cells.",
    )
    parser.add_argument(
        "--arrow-position", choices=("end", "middle", "border"), default="end",
        help="Graph arrowheads: border endpoints (default), middle segments, or explicit border placement",
    )
    parser.add_argument(
        "--uniform-nodes", action="store_true",
        help="Use common flowchart node dimensions before width fitting and routing.",
    )
    parser.add_argument(
        "--strict-width",
        action="store_true",
        help="Exit unsuccessfully instead of emitting output wider than --width.",
    )
    parser.add_argument(
        "--fit-mode",
        choices=["compact", "wrap", "reflow"],
        default="wrap",
        help=(
            "Width fitting strategy: spacing only, semantic label wrapping, "
            "or wrapping plus vertical flowchart reflow (default: wrap)."
        ),
    )
    parser.add_argument(
        "--max-height",
        type=int,
        default=None,
        help="Exit unsuccessfully when output exceeds this many rows.",
    )
    parser.add_argument(
        "--sharp-edges",
        action="store_true",
        help="Use sharp corners on edge turns instead of rounded",
    )
    parser.add_argument(
        "--theme",
        default=None,
        choices=["default", "terra", "neon", "mono", "amber", "phosphor",
                 "gruvbox", "monokai", "dracula", "nord", "solarized"],
        help="Color theme. Requires 'rich' package (pip install termaid[rich]).",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch interactive TUI viewer. Requires 'textual' (pip install termaid[tui]).",
    )
    parser.add_argument(
        "--no-auto-fit",
        action="store_true",
        help="Disable automatic compaction when diagram exceeds terminal width",
    )
    parser.add_argument(
        "--inline-edge-labels",
        action="store_true",
        help="Attach labels directly to their edges",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        metavar="FILE",
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "styled-json"],
        default="text",
        help="Output plain text or versioned semantic style chunks.",
    )
    parser.add_argument(
        "--show-ids",
        action="store_true",
        help="Show node IDs alongside labels (e.g. 'A: Start') for debugging.",
    )
    parser.add_argument(
        "--json",
        default=None,
        metavar="TYPE",
        choices=["treemap", "pie", "mindmap", "flowchart", "xychart"],
        help="Read JSON/tabular data from stdin and render as TYPE (treemap, pie, mindmap, flowchart).",
    )
    parser.add_argument(
        "--themes",
        action="store_true",
        help="List available color themes and exit.",
    )
    parser.add_argument(
        "--demo",
        nargs="?",
        const="all",
        default=None,
        metavar="TYPE",
        help="Render sample diagrams. Use 'all' or a type name (flowchart, sequence, etc.).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )

    args = parser.parse_args(argv)

    if args.strict_width and args.width is None:
        return _report(args, "invalid_arguments", "--strict-width requires --width.", exit_code=2)
    if args.width is not None and args.width < 1:
        return _report(args, "invalid_arguments", "--width must be positive.", exit_code=2)
    if args.max_height is not None and args.max_height < 1:
        return _report(args, "invalid_arguments", "--max-height must be positive.", exit_code=2)

    if args.themes:
        return _list_themes()

    if args.demo is not None:
        return _run_demo(args)

    # Read input
    raw_source = _read_source(args)
    if raw_source is None:
        return 1

    normalized_source = raw_source.strip()
    if not normalized_source:
        return _report(args, "input_empty", "Empty input.")

    # JSON ingest: convert structured data to Mermaid syntax
    if args.json:
        try:
            from .ingest import json_to_mermaid
            diagram_source = json_to_mermaid(normalized_source, args.json)
        except Exception as e:
            return _report(args, "input_conversion_failed", f"Error converting JSON to {args.json}: {e}")
    else:
        diagram_source = normalized_source

    # TUI mode
    if args.tui:
        return _run_tui(diagram_source, args)

    # --show-ids: patch node labels before rendering
    render_source = _apply_show_ids(diagram_source) if args.show_ids else diagram_source

    # Every output format fits and validates the same immutable plan. Adapters
    # serialize only the selected candidate; they never participate in fitting.
    from .layout.engine import plan

    try:
        initial_plan = plan(
            render_source,
            use_ascii=args.ascii,
            padding_x=args.padding_x,
            padding_y=args.padding_y,
            rounded_edges=not args.sharp_edges,
            gap=args.gap,
            inline_edge_labels=args.inline_edge_labels,
            uniform_nodes=args.uniform_nodes,
            arrow_position=args.arrow_position,
            max_width=args.width,
        )
        fitted_plan = _auto_fit(
            initial_plan, render_source, args, render_fn=plan,
            target_width=args.width,
        )
        plain_output = fitted_plan.to_string()
        constraint_exit_code = _check_output(plain_output, args)
        if constraint_exit_code is not None:
            return constraint_exit_code
    except Exception as error:
        return _report(
            args, "render_failed", f"Error rendering diagram: {error}",
            exception_type=type(error).__name__,
        )

    use_color = args.output_format == "text" and _use_color(args)
    rich_output: Text | None = None
    try:
        if args.output_format == "styled-json":
            serialized_output = json.dumps(
                fitted_plan.to_styled(), ensure_ascii=False, separators=(",", ":"),
            )
        elif use_color:
            rich_output = fitted_plan.to_rich(theme=args.theme or "default")
            serialized_output = plain_output
        else:
            serialized_output = plain_output
    except ImportError:
        return _report(
            args, "dependency_missing",
            "'rich' package required for --theme. Install with: pip install termaid[rich]",
            dependency="rich",
        )
    except Exception as error:
        return _report(
            args, "render_failed", f"Error serializing diagram: {error}",
            exception_type=type(error).__name__,
        )

    try:
        output_context = (open(args.output, "w", encoding="utf-8") if args.output
                          else nullcontext(sys.stdout))
        with output_context as output_file:
            if rich_output is not None:
                from rich.console import Console
                console = Console(
                    file=output_file, force_terminal=True if args.output else None,
                    width=max(fitted_plan.width, 80) if args.output else None,
                )
                console.print(rich_output)
            else:
                output_file.write(serialized_output + "\n")
    except OSError as error:
        return _report(
            args, "output_write_failed", f"Error writing output: {error}",
            path=args.output or "<stdout>",
        )
    return 0


def _run_tui(source: str, args: argparse.Namespace) -> int:
    """Launch the TUI viewer."""
    try:
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from termaid import render as _render
    except ImportError:
        return _report(args, "dependency_missing", "'textual' package required for --tui. Install with: pip install termaid[tui]", dependency="textual")

    class DiagramApp(App):
        CSS = "Static { width: auto; height: auto; }"

        def compose(self) -> ComposeResult:
            yield Static(_render(
                source,
                use_ascii=args.ascii,
                padding_x=args.padding_x,
                padding_y=args.padding_y,
                rounded_edges=not args.sharp_edges,
                gap=args.gap,
            ))

    DiagramApp().run()
    return 0


def _apply_show_ids(source: str) -> str:
    """Rewrite flowchart source so node labels include their IDs.

    For each node where label != id, appends a node definition line
    ``ID["ID: Label"]`` to the source so the parser picks up the new label.
    Non-flowchart diagrams are returned unchanged.
    """
    try:
        from termaid import parse
        graph = parse(source)
    except Exception:
        return source

    # Build rewrite lines for nodes where label differs from ID
    extra_lines: list[str] = []
    for nid, node in graph.nodes.items():
        if node.label != nid:
            # Escape quotes in the combined label
            safe_label = f"{nid}: {node.label}".replace('"', "'")
            extra_lines.append(f'  {nid}["{safe_label}"]')

    if not extra_lines:
        return source

    # Append the redefinition lines after the header
    lines = source.split("\n")
    # Insert after the first line (the graph/flowchart header)
    return lines[0] + "\n" + "\n".join(extra_lines) + "\n" + "\n".join(lines[1:])



def _list_themes() -> int:
    """List available color themes."""
    themes = [
        ("default",   "text",  "Cyan nodes, yellow arrows, white labels"),
        ("terra",     "text",  "Warm earth tones (browns, oranges)"),
        ("neon",      "text",  "Magenta nodes, green arrows, cyan edges"),
        ("mono",      "text",  "White/gray monochrome"),
        ("amber",     "text",  "Amber/gold CRT-style"),
        ("phosphor",  "text",  "Green phosphor terminal"),
        ("gruvbox",   "solid", "Gruvbox dark palette"),
        ("monokai",   "solid", "Monokai dark with pink/green accents"),
        ("dracula",   "solid", "Dracula purple/pink/green palette"),
        ("nord",      "solid", "Nord muted blue/cyan arctic palette"),
        ("solarized", "solid", "Solarized dark blue/yellow/cyan"),
    ]
    for name, kind, desc in themes:
        tag = f"[{kind}]"
        print(f"  {name:12s} {tag:8s} {desc}")
    return 0


_DEMO_SOURCES = {
    "flowchart": ("Flowchart", "graph TD\n  A[Start] --> B{Decision}\n  B -->|Yes| C[Process]\n  B -->|No| D[End]\n  C --> D"),
    "sequence": ("Sequence diagram", "sequenceDiagram\n  Client->>Server: GET /api\n  Server->>DB: SELECT\n  DB-->>Server: rows\n  Server-->>Client: 200 JSON"),
    "class": ("Class diagram", "classDiagram\n  class Animal {\n    +String name\n    +makeSound()\n  }\n  class Dog {\n    +fetch()\n  }\n  Animal <|-- Dog"),
    "er": ("ER diagram", "erDiagram\n  CUSTOMER ||--o{ ORDER : places\n  ORDER ||--|{ ITEM : contains"),
    "state": ("State diagram", "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running : start\n  Running --> Done : complete\n  Done --> [*]"),
    "block": ("Block diagram", "block-beta\n  columns 3\n  Frontend API Database"),
    "git": ("Git graph", "gitGraph\n  commit\n  branch develop\n  commit\n  commit\n  checkout main\n  merge develop\n  commit"),
    "pie": ("Pie chart", 'pie title Languages\n  "Python" : 45\n  "Go" : 30\n  "Rust" : 25'),
    "treemap": ("Treemap", 'treemap-beta\n  "Backend"\n    "API": 35\n    "Auth": 15\n  "Frontend"\n    "React": 30\n    "CSS": 10'),
    "mindmap": ("Mindmap", "mindmap\n  Project\n    Design\n      Wireframes\n      Mockups\n    Development\n      Frontend\n      Backend\n    Testing"),
    "timeline": ("Timeline", "timeline\n    title Roadmap\n    section Q1\n        Research : Analysis\n        Design : Wireframes\n    section Q2\n        Build : Frontend, Backend\n        Launch : Beta"),
    "kanban": ("Kanban", "kanban\n    Todo\n        Design homepage\n        Fix login bug\n    In Progress\n        API integration\n    Done\n        Project setup"),
    "journey": ("User journey", "journey\n    title My working day\n    section Go to work\n        Make tea: 5: Me\n        Go upstairs: 3: Me\n        Do work: 1: Me, Cat\n    section Go home\n        Go downstairs: 5: Me\n        Sit down: 5: Me"),
    "xychart": ("XY chart", 'xychart-beta\n    title "Monthly Revenue"\n    x-axis [Jan, Feb, Mar, Apr, May, Jun]\n    y-axis "Revenue (k)"\n    bar [12, 18, 25, 20, 30, 35]'),
    "quadrant": ("Quadrant chart", 'quadrantChart\n    title Priority Matrix\n    x-axis Low Effort --> High Effort\n    y-axis Low Impact --> High Impact\n    quadrant-1 Do First\n    quadrant-2 Schedule\n    quadrant-3 Delegate\n    quadrant-4 Eliminate\n    Task A: [0.3, 0.8]\n    Task B: [0.8, 0.9]\n    Task C: [0.2, 0.2]'),
}


def _run_demo(args: argparse.Namespace) -> int:
    """Render sample diagrams."""
    demo_type = args.demo.lower()
    if demo_type == "all":
        keys = list(_DEMO_SOURCES.keys())
    elif demo_type in _DEMO_SOURCES:
        keys = [demo_type]
    else:
        return _report(args, "invalid_arguments", f"Unknown demo type: {demo_type}. Available: all, {', '.join(_DEMO_SOURCES.keys())}")

    use_color = _use_color(args)

    for key in keys:
        title, source = _DEMO_SOURCES[key]
        print(f"=== {title} ===")
        if use_color:
            try:
                from termaid import render_rich
                from rich import print as rprint
                rprint(render_rich(source, theme=args.theme or "default"))
            except ImportError:
                from termaid import render
                print(render(source))
        else:
            from termaid import render
            print(render(source))
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
