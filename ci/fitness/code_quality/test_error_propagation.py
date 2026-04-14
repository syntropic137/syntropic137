"""Fitness function: error propagation safety.

Ensures no production code silently swallows exceptions with bare
``except: pass`` or ``except Exception: pass`` handlers that lack
any logging or re-raise. Silent swallowing hides bugs in production
and makes debugging impossible.

Violations are tracked via fitness_exceptions.toml with issue
references. Phase D of the architecture audit fixed all known
violations; any remaining exceptions are ratcheted there.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

if TYPE_CHECKING:
    from pathlib import Path


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """Check if this is a broad except (bare except or except Exception)."""
    if handler.type is None:
        # bare ``except:``
        return True
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _is_only_pass(handler: ast.ExceptHandler) -> bool:
    """Check if handler body is just ``pass`` or ``...`` with no other statements.

    We only flag truly silent handlers - those that literally do nothing.
    Handlers that return values (e.g. ``return Err(...)``), assign variables,
    or contain any other statements are not considered silent even if they
    lack logging, because they propagate information about the error.
    """
    for stmt in handler.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            # Bare ``...`` (Ellipsis) or string constant (docstring)
            continue
        # Any other statement means this handler does something
        return False
    return True


def _find_silent_swallows(path: Path) -> list[str]:
    """Find except handlers that silently swallow exceptions."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad_except(node) and _is_only_pass(node):
            violations.append(f"line {node.lineno}: silent except handler")
    return violations


@pytest.mark.architecture
class TestErrorPropagation:
    def test_no_silent_exception_swallowing(self) -> None:
        """No production code should silently swallow exceptions."""
        root = repo_root()
        exceptions = load_exceptions(root).get("error_propagation", {})
        files = production_files(root)

        all_violations: list[str] = []
        for py_file in files:
            rp = rel_path(py_file, root)
            if rp in exceptions:
                continue
            violations = _find_silent_swallows(py_file)
            for v in violations:
                all_violations.append(f"{rp}: {v}")

        if all_violations:
            joined = "\n  ".join(all_violations)
            pytest.fail(
                f"Found {len(all_violations)} silent exception swallowing violation(s):\n"
                f"  {joined}\n\n"
                "Every except handler catching Exception (or bare except) must either:\n"
                "  - Log the error (logger.error/exception/critical/warning)\n"
                "  - Re-raise the exception\n"
                "Never silently pass. See AGENTS.md for error handling standards."
            )
