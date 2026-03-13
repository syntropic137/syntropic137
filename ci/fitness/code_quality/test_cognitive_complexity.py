"""Fitness function: cognitive complexity limits.

Enforces maximum cognitive complexity per file and per function.
Uses the SonarSource cognitive complexity spec via _scanner.py.
"""

from __future__ import annotations

import pytest
from ci.fitness._scanner import scan_file
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

DEFAULT_MAX_COG_PER_FILE = 50
DEFAULT_MAX_COG_PER_FUNCTION = 25


def _get_file_params() -> list[tuple[str, int, int]]:
    """Return (rel_path, total_cog, max_cog) for each production file."""
    root = repo_root()
    exceptions = load_exceptions(root).get("cognitive_complexity", {})
    results = []
    for path in production_files(root):
        rp = rel_path(path, root)
        try:
            metrics = scan_file(path)
        except SyntaxError:
            continue
        max_cog = exceptions.get(rp, {}).get("max_cog", DEFAULT_MAX_COG_PER_FILE)
        results.append((rp, metrics.total_cog, max_cog))
    return results


def _get_function_params() -> list[tuple[str, str, int, int, int]]:
    """Return (rel_path, func_name, lineno, cog, max_cog) for functions above threshold."""
    root = repo_root()
    func_exceptions = load_exceptions(root).get("cognitive_complexity_function", {})
    results = []
    for path in production_files(root):
        rp = rel_path(path, root)
        try:
            metrics = scan_file(path)
        except SyntaxError:
            continue
        for fm in metrics.functions:
            func_key = f"{rp}::{fm.name}"
            func_exc = func_exceptions.get(func_key, {})
            max_cog = func_exc.get("max_cog", DEFAULT_MAX_COG_PER_FUNCTION)
            # Only parametrize functions that are near or above the limit
            if fm.cog > DEFAULT_MAX_COG_PER_FUNCTION * 0.8 or fm.cog > max_cog:
                results.append((rp, fm.name, fm.lineno, fm.cog, max_cog))
    return results


_FILE_PARAMS = _get_file_params()
_FUNC_PARAMS = _get_function_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,total_cog,max_cog",
    _FILE_PARAMS,
    ids=[p[0].split("/")[-1] for p in _FILE_PARAMS],
)
def test_file_cognitive_complexity(file_path: str, total_cog: int, max_cog: int) -> None:
    assert total_cog <= max_cog, (
        f"{file_path} has cognitive complexity {total_cog} (limit: {max_cog}). "
        f"Refactor to reduce complexity or add a grandfathered exception."
    )


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,func_name,lineno,cog,max_cog",
    _FUNC_PARAMS,
    ids=[f"{p[0].split('/')[-1]}::{p[1]}" for p in _FUNC_PARAMS],
)
def test_function_cognitive_complexity(
    file_path: str, func_name: str, lineno: int, cog: int, max_cog: int
) -> None:
    assert cog <= max_cog, (
        f"{file_path}:{lineno} {func_name}() has cognitive complexity {cog} (limit: {max_cog}). "
        f"Refactor or add a grandfathered exception."
    )
