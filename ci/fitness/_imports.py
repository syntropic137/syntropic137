"""Import analyzer for architectural fitness functions.

Walks AST to extract import information, distinguishing runtime imports
from TYPE_CHECKING-guarded imports.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ImportInfo:
    module: str  # e.g. "syn_adapters.projection_stores.protocol"
    names: list[str]  # e.g. ["ProjectionStoreProtocol"]
    is_type_checking: bool  # True if inside TYPE_CHECKING block
    lineno: int


def _is_type_checking_guard(node: ast.If) -> bool:
    """Check if an `if` node is guarded by TYPE_CHECKING."""
    test = node.test
    # `if TYPE_CHECKING:`
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    # `if typing.TYPE_CHECKING:`
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _extract_imports(nodes: list[ast.stmt], *, is_type_checking: bool = False) -> list[ImportInfo]:
    """Extract import info from a list of AST statements."""
    imports: list[ImportInfo] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ImportInfo(
                        module=alias.name,
                        names=[alias.asname or alias.name.split(".")[-1]],
                        is_type_checking=is_type_checking,
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            imports.append(
                ImportInfo(
                    module=module,
                    names=names,
                    is_type_checking=is_type_checking,
                    lineno=node.lineno,
                )
            )
        elif isinstance(node, ast.If) and _is_type_checking_guard(node):
            imports.extend(_extract_imports(node.body, is_type_checking=True))
        elif isinstance(node, (ast.If, ast.Try)):
            # Recurse into if/try bodies for conditional imports
            body_nodes: list[ast.stmt] = list(node.body)
            if hasattr(node, "orelse"):
                body_nodes.extend(node.orelse)  # type: ignore[union-attr]
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    body_nodes.extend(handler.body)
            imports.extend(_extract_imports(body_nodes, is_type_checking=is_type_checking))
    return imports


def extract_imports(path: Path) -> list[ImportInfo]:
    """Extract all imports from a Python file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    return _extract_imports(tree.body)


def runtime_imports(path: Path) -> list[ImportInfo]:
    """Extract only runtime (non-TYPE_CHECKING) imports from a file."""
    return [imp for imp in extract_imports(path) if not imp.is_type_checking]


def all_imports(path: Path) -> list[ImportInfo]:
    """Extract ALL imports including those inside function/method bodies.

    Uses ast.walk to traverse the entire AST, catching lazy imports that
    runtime_imports() misses (it only sees module-level statements).
    All returned imports have is_type_checking=False since TYPE_CHECKING
    status cannot be reliably determined for nested imports.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports: list[ImportInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ImportInfo(
                        module=alias.name,
                        names=[alias.asname or alias.name.split(".")[-1]],
                        is_type_checking=False,
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            imports.append(
                ImportInfo(
                    module=module,
                    names=names,
                    is_type_checking=False,
                    lineno=node.lineno,
                )
            )
    return imports
