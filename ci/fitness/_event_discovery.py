"""Event class discovery for event sourcing fitness functions.

Scans domain/events/ directories for @event-decorated DomainEvent subclasses.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ci.fitness.conftest import repo_root

if TYPE_CHECKING:
    from pathlib import Path


def _inherits_domain_event(node: ast.ClassDef) -> bool:
    """Check if a class inherits from DomainEvent."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "DomainEvent":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "DomainEvent":
            return True
    return False


def _has_event_decorator(node: ast.ClassDef) -> bool:
    """Check if a class has the @event(...) decorator."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "event":
            return True
    return False


def discover_event_classes(root: Path | None = None) -> dict[str, Path]:
    """Scan domain/events/ directories for @event-decorated DomainEvent subclasses.

    Returns {ClassName: defining_file_path}.
    """
    root = root or repo_root()
    result: dict[str, Path] = {}

    for py_file in sorted(root.glob("packages/syn-domain/src/**/domain/events/**/*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and _inherits_domain_event(node)
                and _has_event_decorator(node)
            ):
                result[node.name] = py_file

    return result
