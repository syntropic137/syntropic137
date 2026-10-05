"""Fitness function: every container the API creates names its host (#1310, 0.4).

The next API generation finds its predecessor's containers by ``syn.host_id``.
A creation path that forgets the labels makes containers no generation can
claim, and nothing fails until a hot upgrade strands them. So every place
production code creates a container must take its labels from ``host_labels()``.

A creation site is any of:

* a ``docker run`` / ``docker create`` argv - a literal list, or the positional
  arguments of a call, whose strings contain ``"docker", "run"`` adjacent, or
  start with ``"run"``/``"create"`` as the argument of a ``*docker*`` helper;
* a Docker SDK ``<x>.containers.create(...)`` or ``<x>.containers.run(...)``;
* an agentic_isolation ``WorkspaceConfig(...)``, which the provider turns into
  a ``docker run``.

The enclosing function must reference ``host_labels``. The scanner is pinned to
the paths known today, so a scanner that silently stops finding them fails too.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import production_files, rel_path

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.architecture

#: Today's creation paths: workspace, sidecar, capture recovery helper.
KNOWN_CREATION_MODULES = {
    "packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py",
    "packages/syn-adapters/src/syn_adapters/workspace_backends/docker/docker_sidecar_helpers.py",
    "packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py",
}


def _strings(nodes: list[ast.expr]) -> list[str | None]:
    return [
        n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None for n in nodes
    ]


def _is_docker_argv(values: list[str | None], *, docker_helper: bool) -> bool:
    for before, current in zip([None, *values], values, strict=False):
        if before == "docker" and current in {"run", "create"}:
            return True
    return docker_helper and bool(values) and values[0] in {"run", "create"}


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _creation_lines(func: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            docker_helper = "docker" in name.lower()
            if _is_docker_argv(_strings(node.args), docker_helper=docker_helper):
                lines.append(node.lineno)
            for arg in node.args:
                if isinstance(arg, ast.List | ast.Tuple) and _is_docker_argv(
                    _strings(arg.elts), docker_helper=docker_helper
                ):
                    lines.append(arg.lineno)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"create", "run"}
                and _call_name(node.func.value) == "containers"
            ):
                lines.append(node.lineno)
            if name == "WorkspaceConfig":
                lines.append(node.lineno)
        elif isinstance(node, ast.List) and _is_docker_argv(
            _strings(node.elts), docker_helper=False
        ):
            lines.append(node.lineno)
    return lines


def _references_host_labels(func: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id == "host_labels")
        or (isinstance(n, ast.arg) and n.arg == "host")
        for n in ast.walk(func)
    )


def _scan(path: Path) -> tuple[list[int], list[int]]:
    """(lines of creation sites, lines of those without host labels)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[int] = set()
    unlabelled: set[int] = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        lines = _creation_lines(func)
        found.update(lines)
        if lines and not _references_host_labels(func):
            unlabelled.update(lines)
    return sorted(found), sorted(unlabelled)


def test_every_container_creation_path_carries_host_labels() -> None:
    creation_modules: set[str] = set()
    violations: list[str] = []
    for path in production_files():
        found, unlabelled = _scan(path)
        if found:
            creation_modules.add(rel_path(path))
        violations.extend(f"{rel_path(path)}:{line}" for line in unlabelled)

    missing = KNOWN_CREATION_MODULES - creation_modules
    assert not missing, f"Scanner no longer finds known container creation paths: {missing}"
    assert not violations, (
        "Container creation without host labels; take them from "
        "syn_adapters.workspace_backends.host_labels.host_labels():\n  " + "\n  ".join(violations)
    )
