"""AST audit for assignments to function parameters in production Python code."""
from __future__ import annotations

import ast
from pathlib import Path


def parameter_assignments(source_path: Path) -> list[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = function.args
        parameter_names = {argument.arg for argument in (
            *arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
        )}
        parameter_names.update(argument.arg for argument in (arguments.vararg, arguments.kwarg)
                               if argument is not None)
        pending = list(function.body)
        while pending:
            node = pending.pop()
            # Nested scopes are audited on their own, not against this scope.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in parameter_names:
                problems.append(f"{source_path}:{node.lineno}: {function.name} rebinds parameter {node.id}")
            pending.extend(ast.iter_child_nodes(node))
    return problems


def main() -> int:
    source_directory = Path(__file__).resolve().parents[1] / "src" / "termaid"
    source_paths = sorted(source_directory.rglob("*.py"))
    problems = [problem for source_path in source_paths for problem in parameter_assignments(source_path)]
    for problem in problems:
        print(problem)
    print(f"Parameter-binding audit: {len(source_paths)} modules, {len(problems)} violations.")
    print("No configured static checker; this audit does not prove complete type safety.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
