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

## Architecture and feature ownership

Start with [the architecture map](docs/architecture.md). `source.py` classifies
headers using metadata from `registry.py`. `pipeline.prepare()` resolves one
renderer, whose typed callable builds a Canvas; `PreparedDiagram.plan()` freezes
it into a DiagramPlan. CLI fitting reuses that prepared renderer. Output adapters
serialize the selected plan.

Core definitions live in `core/`. Core families live in `diagrams/`; bundled
extensions live in `plugins/`. Keep a small feature's model, parser, and rendering
entry together. Share graph layout, routing, drawing, labels and text utilities
when their semantics fit. Avoid adding forwarding classes or separate files for
a feature's constants and small data models.

## Adding a diagram feature

1. Choose core or plugin based on semantic/model compatibility, algorithm reuse,
   entry cost, dependencies, maintenance, and product priority. Core currently
   includes flowchart, state, architecture, sequence, class and ER.
2. Add the feature implementation to its home, or an existing related plugin
   group. Expose a callable conforming to `Renderer`.
3. Register a `DiagramDefinition` with unique header aliases and a lazy loader.
   Bundled definitions live in `registry.py`; external plugins extend a registry
   explicitly. No dispatcher, enum, fitting or serializer changes are needed.
4. For feature settings, inherit `RenderConfig`; `ConfiguredRenderer[Options]`
   provides a typed inheritance boundary. Use `adapted_loader()` for another
   backend protocol. See the complete [plugin example](docs/plugins.md).
5. Add behavior tests, including output parity, repeated rendering and any
   feature-specific settings or directives. Run the full tests and compile gate.

```bash
uv run pytest tests/ -q
uv run python -m compileall -q src tests
uv run python benchmarks/audit_bindings.py
git diff --check
```

No static checker or linter is configured. The AST audit checks parameter
rebinding; review other binding/type transitions in changed execution boundaries.
Do not change approved snapshots merely to make a structural move pass.

## Adding a new node shape

1. Add the shape to `NodeShape` enum in `src/termaid/core/graph.py`
2. Add parser detection in `src/termaid/diagrams/flowchart.py` (`_parse_node`)
3. Add renderer in `src/termaid/renderer/shapes/__init__.py`
4. Register in `SHAPE_RENDERERS` dict
5. Add tests in `tests/test_shapes.py`

## Adding a test fixture

1. Create `tests/fixtures/flowcharts/my_test.mmd`
2. Run `uv run pytest tests/test_renderer.py -q` — it auto-generates the expected output
3. Review the generated `.txt` file in `tests/fixtures/expected/`
4. Run again to confirm it passes
