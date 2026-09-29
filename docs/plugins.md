# Diagram plugins and typed options

[Architecture](architecture.md) · [Contributing](../CONTRIBUTING.md)

Plugins implement the same renderer contract as core features. A descriptor
provides a stable identifier, exact header aliases and a lazy loader. Registering
it returns a new immutable registry; it does not modify global state.

Keep the feature's small model, parser and render entry in one module. Use the
shared Graph workflow if the semantics fit, or draw a Canvas with a specialized
layout. The pipeline freezes the result and handles all output formats.

## Typed feature settings

This complete example extends common options and uses the optional renderer base:

```python
from dataclasses import dataclass

from termaid import (
    Canvas, ConfiguredRenderer, DiagramDefinition, ParsedSource,
    RenderConfig, RenderResult, plan,
)
from termaid.registry import DEFAULT_REGISTRY
from termaid.utils import display_width


@dataclass(frozen=True)
class BadgeOptions(RenderConfig):
    label: str = "ready"
    border: str = "*"


class BadgeRenderer(ConfiguredRenderer[BadgeOptions]):
    def __init__(self) -> None:
        super().__init__(BadgeOptions())

    def render(self, source: ParsedSource, config: BadgeOptions) -> RenderResult:
        text = f"{config.border} {config.label} {config.border}"
        canvas = Canvas(display_width(text), 1)
        canvas.put_text(0, 0, text, style="label")
        return RenderResult(canvas)


registry = DEFAULT_REGISTRY.register(DiagramDefinition(
    diagram_id="example.badge",
    headers=("badge", "badge-beta"),
    load_renderer=BadgeRenderer,
))
diagram = plan("badge", BadgeOptions(label="done"), registry=registry)
assert diagram.to_string() == "* done *"
```

`ConfiguredRenderer` calls the subclass with its concrete configuration type.
A plain `RenderConfig` inherits feature defaults; an unrelated feature config
raises `TypeError`. Override `__post_init__()` when validating extra fields and
call `super().__post_init__()` to preserve common validation. Frozen dataclass
subclasses work with fitting because `dataclasses.replace()` preserves their
type and extra fields.

A simple plugin can instead provide a function
`render(source: ParsedSource, config: RenderConfig) -> RenderResult`.
Inheritance is useful for typed settings or reusable behavior; it is not
required for registration.

Use the config argument for typed settings. Existing keyword rendering options
remain available, but must stay at their defaults when a config is supplied.
Renderers should treat each call as an independent candidate, even when the
same renderer instance is reused.

## Fitting without terminal or CLI dependencies

```python
from termaid import prepare
from termaid.layout.fitting import FitOptions, fit

prepared = prepare("badge", registry=registry)
config = BadgeOptions(label="done", max_width=20)
initial = prepared.plan(config)
result = fit(initial, prepared.plan, config, FitOptions(width=20, mode="wrap"))
assert result.attempts <= 8
```

Classification and loading happen once. Fitting can change spacing, label width
and orientation while retaining typed feature settings. A plugin must implement
the common options relevant to its geometry; the fitter measures actual output
and cannot make an unsupported layout policy work automatically. The CLI applies
warnings and strict output constraints after selecting a candidate.

## Adapting another renderer protocol

`contract_version=1` describes the interface received by Termaid. A backend with
another interface needs a typed adapter. `adapted_loader()` loads and adapts it
only when selected; both sides of the adapter retain their concrete types.

The following small native backend illustrates the boundary:

```python
from termaid import Renderer, adapted_loader


class NativeRendererV2:
    def paint(self, content: str, width_limit: int | None) -> list[str]:
        return ["native: " + content]


def adapt_native(backend: NativeRendererV2) -> Renderer:
    def render_native(source: ParsedSource, config: RenderConfig) -> RenderResult:
        lines = backend.paint(source.body, config.max_width)
        canvas = Canvas(max((display_width(line) for line in lines), default=0), len(lines))
        for row, line in enumerate(lines):
            canvas.put_text(row, 0, line, style="label")
        return RenderResult(canvas)
    return render_native


native_definition = DiagramDefinition(
    "example.native", ("native",),
    adapted_loader(NativeRendererV2, adapt_native),
    native_protocol="example.paint.v2",
)
native_registry = registry.register(native_definition)
assert plan("native", registry=native_registry).to_string() == "native: native"
```

`native_protocol` identifies the backend for inspection; it does not bypass the
contract check. Unsupported Termaid contract versions fail before loading.
There is no claim that an arbitrary future interface works without an adapter.
Keep options, source translation and output conversion inside the adapter;
dispatch, fitting and serializers do not need backend-specific branches.

## Registration rules

- Use a unique namespaced identifier for external plugins and exact header aliases
  containing letters, digits or hyphens, starting with a letter.
- Duplicate identifiers or aliases are rejected, including collisions with core.
- The classifier uses registry metadata rather than a closed enum. `DiagramType`
  remains a convenience for built-ins only.
- Keep a `ParsedSource` with its registry. Planning a classified identifier absent
  from the supplied registry fails explicitly.
- Complete `source.text` retains directives; `source.body` starts at the header.
  Git uses complete text for its configuration. Classification is not full syntax
  validation; unknown headers retain the historical flowchart fallback.
- Missing optional dependencies in the selected loader become
  `DiagramUnavailableError`; unrelated core diagrams remain usable.
- Bundled plugin families stay installed and enabled by default. Package discovery,
  downloads and separate plugin distributions are outside this implementation.

Plugin tests should cover repeated calls, option inheritance, fitting limits,
Unicode cells, serialization parity, missing dependencies and any native adapter.
`tests/test_plugins.py` exercises these contracts with a working extension.
