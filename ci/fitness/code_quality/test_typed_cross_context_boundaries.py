"""Fitness function: typed cross-context boundaries (ADR-063).

Cross-context boundary definitions (Protocol classes and abstract base
classes) must not use ``dict[str, str]``, ``dict[str, Any]``, or
``dict[str, object]`` for parameters or return types that carry domain
identity. This fitness function scans these boundary classes for untyped
dict signatures and flags them.

The goal is to prevent the class of bugs where one context passes
domain identity (e.g. repository, execution ID) through an untyped dict
and the receiving context fishes it out with implicit key conventions
that pyright cannot verify. The trigger-fired execution bug that
motivated ADR-063 is exactly this pattern.

What this enforces (ADR-063 §3):
- Protocol classes (PEP 544 structural typing)
- Abstract base classes (``abc.ABC`` or ``@abstractmethod``)
- Both parameter annotations and return type annotations

What this does NOT enforce:
- Concrete class methods (too noisy without a clear "boundary" definition)
- Pydantic/dataclass field types (events are exempt per ADR-063 §4)
- Module-level functions

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

# Parameter/return slot names that are known-safe generic dicts (not domain
# identity). These carry opaque key/value pairs (config maps, HTTP headers,
# webhook payloads, etc.) and aren't the kind of cross-context identity smuggling
# ADR-063 is targeting.
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
        "input_mapping",  # trigger -> workflow input map (opaque k/v)
        "payload",  # raw webhook payload before normalization
        "data",  # raw deserialized blob in from_dict factories
        "permissions",  # GitHub App permission map
    }
)


class _BoundaryDictVisitor(ast.NodeVisitor):
    """Find Protocol/ABC methods with untyped dict parameters or returns."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.violations: list[tuple[str, str, str, int]] = []
        # (class_name, method_name, slot, line)  where slot is "param:<name>" or "return"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if _is_boundary_class(node):
            for item in ast.walk(node):
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name.startswith("_") and item.name != "__init__":
                    continue  # skip private methods
                self._check_function(node.name, item)
        self.generic_visit(node)

    def _check_function(
        self,
        class_name: str,
        func: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        # Parameters
        for arg in func.args.args:
            if arg.arg == "self" or arg.arg in _SAFE_PARAM_NAMES:
                continue
            ann = arg.annotation
            if ann is None:
                continue
            ann_text = ast.get_source_segment(self.source, ann)
            if ann_text and _UNTYPED_DICT_RE.search(ann_text):
                self.violations.append((class_name, func.name, f"param:{arg.arg}", arg.lineno))

        # Return type
        if func.returns is not None:
            ret_text = ast.get_source_segment(self.source, func.returns)
            if ret_text and _UNTYPED_DICT_RE.search(ret_text):
                self.violations.append((class_name, func.name, "return", func.lineno))


def _is_boundary_class(node: ast.ClassDef) -> bool:
    """Return True if class is a Protocol or abstract base class.

    Boundary classes are the contract definitions that cross context lines:
    - PEP 544 Protocols (``class X(Protocol):``)
    - Abstract bases (``class X(ABC):`` or any method with ``@abstractmethod``)
    """
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in ("Protocol", "ABC"):
            return True
        if isinstance(base, ast.Attribute) and base.attr in ("Protocol", "ABC"):
            return True
    # Fallback: any @abstractmethod decorator marks the class as abstract.
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in item.decorator_list:
                dec_name = (
                    dec.id
                    if isinstance(dec, ast.Name)
                    else dec.attr
                    if isinstance(dec, ast.Attribute)
                    else None
                )
                if dec_name == "abstractmethod":
                    return True
    return False


def _scan_file(py_file: Path) -> list[tuple[str, str, str, int]]:
    """Scan a file for Protocol/ABC methods with untyped dict signatures."""
    try:
        source = py_file.read_text()
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = _BoundaryDictVisitor(source)
    visitor.visit(tree)
    return visitor.violations


def _get_params() -> list[tuple[str, str, str, str, int, int]]:
    """Return (rel_path, class, method, slot, line, budget) for violations."""
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

            for class_name, method_name, slot, line in violations:
                key = f"{rp}:{class_name}.{method_name}.{slot}"
                budget = exceptions.get(key, {}).get("budget", 0)
                results.append((rp, class_name, method_name, slot, line, budget))

    return results


_PARAMS = _get_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,class_name,method_name,slot,line,budget",
    _PARAMS,
    ids=[f"{p[1]}.{p[2]}.{p[3]}" for p in _PARAMS] if _PARAMS else [],
)
def test_no_untyped_dict_at_cross_context_boundaries(
    file_path: str,
    class_name: str,
    method_name: str,
    slot: str,
    line: int,
    budget: int,
) -> None:
    """Boundary classes must use typed value objects, not raw dicts.

    Protocol and abstract base class methods that cross bounded context
    boundaries must declare their parameters and return types with concrete
    value objects (e.g. ``RepositoryRef``) rather than ``dict[str, str|Any|object]``
    with implicit key conventions. See ADR-063.
    """
    assert budget > 0, (
        f"{file_path}:{line} - {class_name}.{method_name} has untyped "
        f"dict at {slot}. Use a typed value object instead of "
        f"dict[str, str/Any/object] at context boundaries (ADR-063)."
    )
