"""Fitness function: bounded context isolation.

Each production file should reference at most 1 foreign bounded context.
Files in _shared/ directories are exempt (they serve multiple contexts by design).
TYPE_CHECKING imports are exempt.
"""

from __future__ import annotations

import pytest
from ci.fitness._imports import runtime_imports
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

# Only check files in domain and adapter packages
_CHECK_DIRS = [
    "packages/syn-domain/src",
    "packages/syn-adapters/src",
]


def _get_own_context(rp: str) -> str | None:
    """Determine which bounded context a file belongs to."""
    for ctx in _CONTEXT_NAMES:
        if f"/contexts/{ctx}/" in rp:
            return ctx
    return None


def _get_params() -> list[tuple[str, int, int]]:
    """Return (rel_path, foreign_count, max_contexts) for files with foreign imports."""
    root = repo_root()
    exceptions = load_exceptions(root).get("bounded_context_isolation", {})
    results = []

    for base_dir in _CHECK_DIRS:
        src_dir = root / base_dir
        if not src_dir.exists():
            continue
        for py_file in sorted(src_dir.rglob("*.py")):
            if py_file.name.startswith("test_") or py_file.name in ("conftest.py", "__init__.py"):
                continue
            rp = rel_path(py_file, root)
            # _shared directories are exempt
            if "/_shared/" in rp:
                continue

            own_ctx = _get_own_context(rp)
            try:
                imps = runtime_imports(py_file)
            except SyntaxError:
                continue

            foreign: set[str] = set()
            for imp in imps:
                for ctx in _CONTEXT_NAMES:
                    if (
                        f"contexts.{ctx}" in imp.module or f".{ctx}." in imp.module
                    ) and ctx != own_ctx:
                        foreign.add(ctx)

            max_ctx = exceptions.get(rp, {}).get("max_contexts", 1)
            if len(foreign) > 0:
                results.append((rp, len(foreign), max_ctx))

    return results


_PARAMS = _get_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,foreign_count,max_contexts",
    _PARAMS,
    ids=[p[0].split("/")[-1] for p in _PARAMS] if _PARAMS else [],
)
def test_bounded_context_isolation(file_path: str, foreign_count: int, max_contexts: int) -> None:
    assert foreign_count <= max_contexts, (
        f"{file_path} references {foreign_count} foreign bounded contexts (limit: {max_contexts}). "
        f"Files should reference at most 1 foreign context."
    )
