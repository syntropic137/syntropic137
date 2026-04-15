"""Fitness function: typed cross-context boundaries (ADR-063).

Cross-context Protocol definitions must not use ``dict[str, str]`` or
``dict[str, Any]`` for parameters that carry domain identity. This
fitness function scans Protocol classes in boundary files for untyped
dict parameters and flags them.

The goal is to prevent the class of bugs where one context passes
repository identity (or other domain concepts) through an untyped dict,
and the receiving context fishes it out with implicit key conventions
that pyright cannot verify.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
Pattern:  ADR-063 (docs/adrs/ADR-063-cross-context-anti-corruption-layer.md)
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import load_exceptions, rel_path, repo_root

if TYPE_CHECKING:
    from pathlib import Path

_CHECK_DIRS = [
    "packages/syn-domain/src",
    "packages/syn-adapters/src",
    "apps/syn-api/src",
]

# Patterns that indicate untyped dict crossing a boundary
_UNTYPED_DICT_RE = re.compile(r"dict\s*\[\s*str\s*,\s*(str|Any|object)\s*\]")

# Parameter names that are known-safe generic dicts (not domain identity)
_SAFE_PARAM_NAMES = frozenset(
    {
        "filters",
        "metadata",
        "headers",
        "extra",
        "config",
        "options",
        "kwargs",
        "record",
    }
)


class _ProtocolDictVisitor(ast.NodeVisitor):
    """Find Protocol methods with untyped dict parameters."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.violations: list[tuple[str, str, int]] = []  # (protocol, method, line)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Only check Protocol classes
        is_protocol = any(
            (isinstance(b, ast.Name) and b.id == "Protocol")
            or (isinstance(b, ast.Attribute) and b.attr == "Protocol")
            for b in node.bases
        )
        if not is_protocol:
            self.generic_visit(node)
            return

        for item in ast.walk(node):
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name.startswith("_") and item.name != "__init__":
                continue  # skip private methods
            self._check_function(node.name, item)
        self.generic_visit(node)

    def _check_function(
        self,
        protocol_name: str,
        func: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for arg in func.args.args:
            if arg.arg == "self":
                continue
            if arg.arg in _SAFE_PARAM_NAMES:
                continue
            annotation = arg.annotation
            if annotation is None:
                continue
            # Get the source text of the annotation
            ann_text = ast.get_source_segment(self.source, annotation)
            if ann_text and _UNTYPED_DICT_RE.search(ann_text):
                self.violations.append((protocol_name, arg.arg, arg.lineno))


def _scan_file(py_file: Path) -> list[tuple[str, str, int]]:
    """Scan a file for Protocol definitions with untyped dict parameters."""
    try:
        source = py_file.read_text()
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = _ProtocolDictVisitor(source)
    visitor.visit(tree)
    return visitor.violations


def _get_params() -> list[tuple[str, str, str, int, int]]:
    """Return (rel_path, protocol, param, line, budget) for violations."""
    root = repo_root()
    exceptions = load_exceptions(root).get("typed_cross_context_boundaries", {})
    results = []

    for base_dir in _CHECK_DIRS:
        src_dir = root / base_dir
        if not src_dir.exists():
            continue

        for py_file in sorted(src_dir.rglob("*.py")):
            if py_file.name.startswith("test_") or py_file.name in (
                "conftest.py",
                "__init__.py",
            ):
                continue

            rp = rel_path(py_file, root)
            violations = _scan_file(py_file)

            for protocol_name, param_name, line in violations:
                key = f"{rp}:{protocol_name}.{param_name}"
                budget = exceptions.get(key, {}).get("budget", 0)
                results.append((rp, protocol_name, param_name, line, budget))

    return results


_PARAMS = _get_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,protocol_name,param_name,line,budget",
    _PARAMS,
    ids=[f"{p[1]}.{p[2]}" for p in _PARAMS] if _PARAMS else [],
)
def test_no_untyped_dict_in_protocols(
    file_path: str,
    protocol_name: str,
    param_name: str,
    line: int,
    budget: int,
) -> None:
    """Protocol methods at context boundaries must use typed value objects.

    Parameters carrying domain identity (repositories, execution IDs, etc.)
    should use value objects like RepositoryRef, not dict[str, str] with
    implicit key conventions (ADR-063).
    """
    assert budget > 0, (
        f"{file_path}:{line} - Protocol {protocol_name} has untyped "
        f"dict parameter '{param_name}'. Use a typed value object instead "
        f"of dict[str, str/Any/object] at context boundaries (ADR-063)."
    )
