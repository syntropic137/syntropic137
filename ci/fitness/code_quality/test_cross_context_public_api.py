"""Fitness function: cross-context public API enforcement.

When a file imports from a foreign bounded context, the import path must
go through the context's public API package (contexts/<ctx>) or its ports
subpackage (contexts/<ctx>/ports). Reaching into slices/, domain/,
_shared/, or other internal subpaths is a violation.

Exemptions:
- TYPE_CHECKING imports are exempt.
- Files in _shared/ directories are exempt (they serve multiple contexts by design).
- Projection classes (names ending with "Projection") are exempt - they are
  slice-owned read models that the adapter composition root legitimately
  imports for subscription wiring (ADR-008, coordinator pattern).
"""

from __future__ import annotations

import pytest
from ci.fitness._imports import all_imports, extract_imports
from ci.fitness.conftest import load_exceptions, rel_path, repo_root

_CONTEXT_NAMES = frozenset(
    {
        "orchestration",
        "agent_sessions",
        "github",
        "artifacts",
        "organization",
        "agents",
    }
)

# Subdirectory suffixes considered part of a context's public surface.
# Empty string = the context package itself (contexts/<ctx>/__init__.py).
# "ports" = hexagonal port interfaces intended for adapter consumption.
_PUBLIC_SUFFIXES: frozenset[str] = frozenset({"", "ports"})

_CHECK_DIRS = [
    "packages/syn-domain/src",
    "packages/syn-adapters/src",
    "apps/syn-api/src",
]


def _get_own_context(rp: str) -> str | None:
    """Return the bounded context this file belongs to, or None."""
    for ctx in _CONTEXT_NAMES:
        if f"/contexts/{ctx}/" in rp:
            return ctx
    return None


def _is_deep_import(module: str, foreign_ctx: str) -> bool:
    """Return True if module reaches past the public API of foreign_ctx."""
    marker = f"contexts.{foreign_ctx}."
    idx = module.find(marker)
    if idx == -1:
        return False
    after = module[idx + len(marker) :]
    if not after:
        return False  # exactly "contexts.<ctx>" - public API root
    first_segment = after.split(".")[0]
    return first_segment not in _PUBLIC_SUFFIXES


def _has_private_names(names: list[str]) -> bool:
    """Return True if any imported name starts with underscore."""
    return any(n.startswith("_") for n in names)


def _is_projection_import(names: list[str]) -> bool:
    """Return True if all imported names are projection classes.

    Projection classes follow the naming convention ``*Projection`` (ADR-008).
    The composition root (coordinator, manager) legitimately imports these
    from foreign context slices for subscription wiring.
    """
    return bool(names) and all(n.endswith("Projection") for n in names)


def _get_params() -> list[tuple[str, int, int]]:
    """Return (rel_path, violation_count, budget) for files with deep imports."""
    root = repo_root()
    exceptions = load_exceptions(root).get("cross_context_public_api", {})
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
            if "/_shared/" in rp:
                continue

            own_ctx = _get_own_context(rp)

            # Build set of TYPE_CHECKING-guarded modules to exempt.
            try:
                typed_imps = extract_imports(py_file)
            except SyntaxError:
                continue
            type_checking_modules: set[str] = {
                imp.module for imp in typed_imps if imp.is_type_checking
            }

            # Use all_imports() to also catch function-body lazy imports.
            try:
                imps = all_imports(py_file)
            except SyntaxError:
                continue

            violation_count = 0
            for imp in imps:
                if imp.module in type_checking_modules:
                    continue
                if _is_projection_import(imp.names):
                    continue
                for ctx in _CONTEXT_NAMES:
                    if ctx == own_ctx:
                        continue
                    if f"contexts.{ctx}" not in imp.module:
                        continue
                    if _is_deep_import(imp.module, ctx):
                        violation_count += 1
                        break
                    elif _has_private_names(imp.names):
                        violation_count += 1
                        break

            budget = exceptions.get(rp, {}).get("deep_imports", 0)
            if violation_count > 0:
                results.append((rp, violation_count, budget))

    return results


_PARAMS = _get_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,violation_count,budget",
    _PARAMS,
    ids=[p[0].split("/")[-1] for p in _PARAMS] if _PARAMS else [],
)
def test_cross_context_public_api_only(
    file_path: str, violation_count: int, budget: int
) -> None:
    """Files must import from foreign contexts only through the public API.

    Forbidden: reaching into slices/, domain/, _shared/, or aggregate_*/ paths.
    Allowed: from syn_domain.contexts.<ctx> import Foo  (public __init__.py)
    Allowed: from syn_domain.contexts.<ctx>.ports import Bar  (hexagonal ports)
    Also forbidden: importing _-prefixed names from foreign contexts.
    """
    assert violation_count <= budget, (
        f"{file_path} has {violation_count} deep cross-context import(s) "
        f"(budget: {budget}). "
        "Import from `contexts.<ctx>` or `contexts.<ctx>.ports` directly, "
        "not from internal subpaths like `contexts.<ctx>.slices.*`."
    )
