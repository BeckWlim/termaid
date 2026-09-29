"""Keep feature ownership and foundational imports independent of dispatch."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "termaid"


def imports_in(path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = ["termaid", *path.relative_to(SOURCE_ROOT).parent.parts]
                modules.append(".".join([*package[:len(package) - node.level + 1], node.module or ""]))
            else:
                modules.append(node.module or "")
    return modules


@pytest.mark.parametrize("directory", ["core", "layout", "routing", "renderer"])
def test_shared_modules_do_not_import_features_dispatch_or_cli(directory):
    forbidden = ("termaid.diagrams", "termaid.plugins", "termaid.pipeline", "termaid.registry", "termaid.cli")
    for path in (SOURCE_ROOT / directory).rglob("*.py"):
        assert not [module for module in imports_in(path) if module.startswith(forbidden)], path
        assert "termaid" not in imports_in(path), path


@pytest.mark.parametrize("directory", ["diagrams", "plugins"])
def test_features_do_not_call_public_api_or_registry(directory):
    for path in (SOURCE_ROOT / directory).rglob("*.py"):
        assert not [module for module in imports_in(path)
                    if module == "termaid" or module.startswith(("termaid.pipeline", "termaid.registry", "termaid.cli"))], path


def test_serializers_do_not_import_layout_or_rendering_engines():
    for name in ("rich.py", "styled.py"):
        path = SOURCE_ROOT / "output" / name
        assert not [module for module in imports_in(path)
                    if module.startswith(("termaid.layout", "termaid.routing", "termaid.pipeline", "termaid.diagrams", "termaid.plugins", "termaid.renderer.graph"))]


def test_removed_layer_trees_are_not_reintroduced_as_forwarding_shims():
    for directory in ("model", "parser", "graph"):
        assert not list((SOURCE_ROOT / directory).rglob("*.py"))
