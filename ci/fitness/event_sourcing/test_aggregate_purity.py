"""Fitness function: aggregate purity.

Aggregates must be pure domain objects:
- No async functions (aggregates are synchronous)
- No IO module imports (aiohttp, httpx, asyncio, subprocess, socket, etc.)
- No infrastructure imports (sqlmodel, asyncpg, psycopg, redis, minio, supabase)
- No open() calls
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import rel_path
from ci.fitness.event_sourcing.conftest import aggregate_files

if TYPE_CHECKING:
    from pathlib import Path

_FORBIDDEN_MODULES = frozenset(
    {
        "aiohttp",
        "httpx",
        "asyncio",
        "subprocess",
        "socket",
        "sqlmodel",
        "asyncpg",
        "psycopg",
        "redis",
        "minio",
        "supabase",
    }
)


def _check_aggregate(path: Path) -> list[str]:
    """Return list of violation descriptions for an aggregate file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            violations.append(
                f"line {node.lineno}: async def {node.name} (aggregates must be sync)"
            )

        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_MODULES:
                    violations.append(f"line {node.lineno}: imports {alias.name}")

        if isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _FORBIDDEN_MODULES:
                violations.append(f"line {node.lineno}: imports {node.module}")

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ):
            violations.append(f"line {node.lineno}: open() call (aggregates must not do IO)")

    return violations


_AGGREGATE_FILES = aggregate_files()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "agg_file",
    _AGGREGATE_FILES,
    ids=[rel_path(f) for f in _AGGREGATE_FILES],
)
def test_aggregate_purity(agg_file: Path) -> None:
    """Aggregate files must be pure domain objects with no IO or async."""
    violations = _check_aggregate(agg_file)
    if violations:
        rp = rel_path(agg_file)
        msg = f"{rp} has aggregate purity violations:\n" + "\n".join(f"  {v}" for v in violations)
        pytest.fail(msg)
