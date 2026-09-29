"""Plugins share fitting and output contracts without core implementation imports."""
from __future__ import annotations

from dataclasses import dataclass, replace
import subprocess
import sys

import pytest

from termaid import (
    Canvas, ConfiguredRenderer, DiagramDefinition, DiagramRegistry,
    DiagramUnavailableError, ParsedSource, RenderConfig, RenderResult,
    Renderer, adapted_loader, parse_source, plan, prepare, render,
)
from termaid.layout.fitting import FitOptions, fit
from termaid.registry import DEFAULT_REGISTRY


def label_result(label: str) -> RenderResult:
    canvas = Canvas(len(label), 1)
    canvas.put_text(0, 0, label, style="label")
    return RenderResult(canvas)


@dataclass(frozen=True)
class BadgeOptions(RenderConfig):
    label: str = "badge"
    decoration: str = "+"


class BadgeRenderer(ConfiguredRenderer[BadgeOptions]):
    def __init__(self) -> None:
        super().__init__(BadgeOptions())
        self.seen: list[BadgeOptions] = []

    def render(self, source: ParsedSource, config: BadgeOptions) -> RenderResult:
        self.seen.append(config)
        padding = " " * config.padding_x
        return label_result(config.decoration + config.label + padding + config.decoration)


def test_typed_plugin_options_survive_fitting_and_serialize():
    renderer = BadgeRenderer()
    loads: list[str] = []

    def load() -> Renderer:
        loads.append("badge")
        return renderer

    registry = DEFAULT_REGISTRY.register(DiagramDefinition("example.badge", ("badge",), load))
    prepared = prepare("badge", registry=registry)
    config = BadgeOptions(label="hello", decoration="*", padding_x=20)
    initial = prepared.plan(config)
    fitted = fit(initial, prepared.plan, config, FitOptions(10))
    assert fitted.plan.to_string() == "*hello*"
    assert fitted.attempts == 3
    assert loads == ["badge"]
    assert all(options.label == "hello" and options.decoration == "*" for options in renderer.seen)
    assert config.padding_x == 20
    assert fitted.plan.to_rich().plain == "*hello*"
    assert fitted.plan.to_styled()["lines"][0][0]["text"] == "*hello*"
    assert render("badge", config, registry=registry) == initial.to_string()
    assert plan(parse_source("badge", registry=registry), config, registry=registry) == initial


def test_inherited_renderer_applies_defaults_and_rejects_unrelated_options():
    renderer = BadgeRenderer()
    source = ParsedSource("example.badge", "badge", "badge")
    renderer(source, RenderConfig(padding_x=1))
    assert renderer.seen == [BadgeOptions(padding_x=1)]

    @dataclass(frozen=True)
    class OtherOptions(RenderConfig):
        other: int = 42

    with pytest.raises(TypeError, match="BadgeOptions"):
        renderer(source, OtherOptions())


def test_native_protocol_adapter_preserves_its_concrete_backend():
    class FutureBackend:
        def paint(self, content: str, ascii_mode: bool) -> str:
            return ("plain:" if ascii_mode else "styled:") + content

    def adapt(backend: FutureBackend) -> Renderer:
        def invoke(source: ParsedSource, config: RenderConfig) -> RenderResult:
            return label_result(backend.paint(source.body, config.use_ascii))
        return invoke

    definition = DiagramDefinition(
        "example.future", ("future",), adapted_loader(FutureBackend, adapt),
        native_protocol="example.paint.v2",
    )
    registry = DiagramRegistry((definition,))
    assert render("future", use_ascii=True, registry=registry) == "plain:future"
    assert definition.contract_version == 1


def test_registry_extension_is_a_snapshot_and_requires_no_enum_change():
    renderer = BadgeRenderer()
    definition = DiagramDefinition("example.badge", ("badge", "badge-beta"), lambda: renderer)
    registry = DEFAULT_REGISTRY.register(definition)
    source = parse_source("%% gitGraph\nbadge-beta", registry=registry)
    assert source.diagram_id == "example.badge"
    assert source.diagram_type == "example.badge"
    assert DEFAULT_REGISTRY.identify("badge") == "flowchart"
    prepared = prepare(source, registry=registry)
    with pytest.raises(DiagramUnavailableError, match="not registered"):
        prepare(source)
    assert prepared.plan(RenderConfig()).to_string().startswith("+badge")
    with pytest.raises(TypeError):
        registry._headers["bad"] = "example.badge"


@pytest.mark.parametrize("change", ["identifier", "header", "alias"])
def test_registry_rejects_ambiguous_registrations(change):
    definition = DEFAULT_REGISTRY.definitions[0]
    if change == "identifier":
        duplicate = replace(definition, headers=("newFlow",))
    elif change == "header":
        duplicate = replace(definition, diagram_id="example.other")
    else:
        with pytest.raises(ValueError, match="Duplicate header"):
            replace(definition, headers=("newFlow", "newFlow"))
        return
    with pytest.raises(ValueError, match="Duplicate|Ambiguous"):
        DEFAULT_REGISTRY.register(duplicate)


def test_incompatible_plugin_fails_before_loading_without_affecting_core():
    def load() -> Renderer:
        raise AssertionError("incompatible plugin must not load")

    registry = DEFAULT_REGISTRY.register(DiagramDefinition("example.bad", ("bad",), load, contract_version=99))
    with pytest.raises(DiagramUnavailableError, match="contract 99"):
        plan("bad", registry=registry)
    assert plan("flowchart LR\nA --> B", registry=registry).to_string()


def test_missing_plugin_dependency_does_not_fall_back_to_flowchart():
    def load() -> Renderer:
        raise ModuleNotFoundError("optional-engine")

    registry = DEFAULT_REGISTRY.register(DiagramDefinition("example.missing", ("missing",), load))
    with pytest.raises(DiagramUnavailableError, match="optional-engine") as caught:
        plan("missing", registry=registry)
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)
    assert registry.identify("unrecognized") == "flowchart"


def test_typed_config_and_keyword_options_have_an_explicit_boundary():
    config = RenderConfig(gap=1, use_ascii=True)
    assert plan("flowchart LR\nA --> B", config) == plan("flowchart LR\nA --> B", gap=1, use_ascii=True)
    with pytest.raises(ValueError, match="not both"):
        plan("flowchart LR\nA --> B", config, gap=8)


def test_core_rendering_and_classification_keep_plugins_and_optional_uis_unloaded():
    process = subprocess.run(
        [sys.executable, "-c", """
import sys
import termaid
assert not any(name.startswith('termaid.diagrams.') for name in sys.modules)
assert termaid.parse_source('gitGraph\\ncommit').diagram_id == 'gitGraph'
assert termaid.render('flowchart LR\\nA --> B')
assert not any(name.startswith(('termaid.plugins', 'rich', 'textual')) for name in sys.modules)
"""], capture_output=True, text=True, check=False,
    )
    assert process.returncode == 0, process.stderr
