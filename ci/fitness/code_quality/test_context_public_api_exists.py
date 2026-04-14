"""Fitness function: every bounded context must have a public API (ADR-062).

Each active bounded context must have a non-empty ``__init__.py`` with at
least one re-export (``from ... import``) or an ``__all__`` assignment.
This ensures consumers can import from the context root instead of reaching
into internal subpackages.

Zero-tolerance: no exceptions file. If a context exists, it must export.
"""

from __future__ import annotations

import ast

import pytest
from ci.fitness.conftest import repo_root

_CONTEXT_NAMES = [
    "orchestration",
    "agent_sessions",
    "github",
    "artifacts",
    "organization",
]

_CONTEXTS_DIR = "packages/syn-domain/src/syn_domain/contexts"


def _has_public_api(init_path: ast.Module) -> bool:
    """Check if an __init__.py AST has at least one re-export or __all__."""
    for node in init_path.body:
        # from foo import bar
        if isinstance(node, ast.ImportFrom):
            return True
        # __all__ = [...]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    return True
    return False


def _get_params() -> list[tuple[str, bool]]:
    """Return (context_name, has_public_api) for each context."""
    root = repo_root()
    results = []
    for ctx in _CONTEXT_NAMES:
        init_file = root / _CONTEXTS_DIR / ctx / "__init__.py"
        if not init_file.exists():
            results.append((ctx, False))
            continue
        try:
            source = init_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
            results.append((ctx, _has_public_api(tree)))
        except SyntaxError:
            results.append((ctx, False))
    return results


_PARAMS = _get_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "context_name,has_api",
    _PARAMS,
    ids=[p[0] for p in _PARAMS],
)
def test_context_has_public_api(context_name: str, has_api: bool) -> None:
    """Every bounded context must export a public API via __init__.py.

    The context's __init__.py must contain at least one ``from ... import``
    statement or an ``__all__`` assignment. Docstring-only __init__.py files
    force consumers to import from internal paths, violating encapsulation.
    """
    assert has_api, (
        f"Bounded context '{context_name}' has no public API. "
        f"Add re-exports to {_CONTEXTS_DIR}/{context_name}/__init__.py "
        f"so consumers can import from the context root."
    )
