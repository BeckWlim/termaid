# Contributing to termaid

## Development setup

```bash
git clone https://github.com/fasouto/termaid.git
cd termaid
uv sync --all-extras
```

## Running tests

```bash
uv run pytest tests/ -q
```

To update snapshot tests after changing rendering output:

```bash
uv run pytest tests/ --update-snapshots
```

## Project structure

```
src/termaid/
  __init__.py          # Public API: render(), render_rich(), parse()
  cli.py               # CLI entry point (argparse)
  graph/               # Graph data model (Node, Edge, Subgraph, NodeShape)
  model/               # Diagram data models, grouped by related functionality
  parser/              # Mermaid syntax parsing
  layout/              # Shared plans, cell geometry, labels, and graph placement
  routing/             # A* edge routing (flowcharts)
  renderer/            # Canvas rendering, shapes, charsets, themes
  output/              # Output formats (text, rich, textual widget)
tests/
  fixtures/flowcharts/ # .mmd input fixtures + expected .txt outputs
```

### Architecture

Start with `layout/engine.py`: `plan()` dispatches parsing and rendering, then
returns an immutable `DiagramPlan`. The public API and CLI use that same entry
point. Output adapters serialize the selected plan as text, Rich, or styled JSON.

The main boundaries are `model/`, `parser/`, `layout/`, and `renderer/`. Small,
related diagram implementations share matching filenames across the model,
parser, and renderer directories:

| Module | Components |
| --- | --- |
| `charts.py` | Pie, quadrant, and XY charts |
| `trees.py` | Mindmaps and treemaps |
| `boards.py` | User journeys and kanban boards |
| `timelines.py` | Gantt schedules and timelines |

Each component has a named section with its own model, parsing, or rendering
functions. Larger implementations remain separate: sequence, class, ER, block,
and git diagrams. Packet diagrams also retain their own protocol-specific files.

Flowcharts, state diagrams, and architecture diagrams parse into the shared
`graph/` model and use `layout/`, `routing/`, and `renderer/draw.py`. Other diagram
renderers place their geometry on the shared `layout.scene.LayoutScene`.

Within `layout/`, `grid.py` orchestrates graph layout, `layers.py` orders nodes,
`placement.py` sizes and places them, and `geometry.py` handles subgraph bounds
and coordinate conversion. `graph_plan.py` combines placement and routes;
`labels.py` reserves text regions, and `fitting.py` scores output candidates.

Internal imports follow the grouped filenames, for example
`from termaid.parser.charts import parse_pie_chart` and
`from termaid.model.trees import Mindmap`. The former per-diagram paths for these
groups have been removed. Public imports such as `termaid.render`,
`termaid.parse`, and `termaid.plan` are unchanged.

## Adding a new diagram type

1. Add dataclasses to the appropriate module in `src/termaid/model/`
2. Add parsing functions to the matching module in `src/termaid/parser/`
3. Add rendering functions to the matching module in `src/termaid/renderer/` (returns a `LayoutScene`)
4. Add dispatch in `src/termaid/layout/engine.py` (`plan()`)
5. Add tests

Use an existing group when its responsibility fits. Give a substantial or
unrelated component its own file; avoid growing a catch-all module. Prefix
component-specific constants or helpers when their names would collide.

## Adding a new node shape

1. Add the shape to `NodeShape` enum in `src/termaid/graph/shapes.py`
2. Add parser detection in `src/termaid/parser/flowchart.py` (`_parse_node`)
3. Add renderer in `src/termaid/renderer/shapes/__init__.py`
4. Register in `SHAPE_RENDERERS` dict
5. Add tests in `tests/test_shapes.py`

## Adding a test fixture

1. Create `tests/fixtures/flowcharts/my_test.mmd`
2. Run `uv run pytest tests/test_renderer.py -q` — it auto-generates the expected output
3. Review the generated `.txt` file in `tests/fixtures/expected/`
4. Run again to confirm it passes
