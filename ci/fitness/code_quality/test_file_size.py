"""Fitness function: file size limits.

Enforces a maximum LOC per production file. Files exceeding the default
limit must have a grandfathered exception in fitness_exceptions.toml.
"""

from __future__ import annotations

import pytest
from ci.fitness._scanner import scan_file
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

DEFAULT_MAX_LOC_PER_FILE = 500


def _get_file_params() -> list[tuple[str, int, int]]:
    """Discover production files and return (rel_path, loc, max_loc) triples."""
    root = repo_root()
    exceptions = load_exceptions(root).get("file_size", {})
    results = []
    for path in production_files(root):
        rp = rel_path(path, root)
        try:
            metrics = scan_file(path)
        except SyntaxError:
            continue
        max_loc = exceptions.get(rp, {}).get("max_loc", DEFAULT_MAX_LOC_PER_FILE)
        results.append((rp, metrics.loc, max_loc))
    return results


_PARAMS = _get_file_params()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,loc,max_loc",
    _PARAMS,
    ids=[p[0].split("/")[-1] for p in _PARAMS],
)
def test_file_size(file_path: str, loc: int, max_loc: int) -> None:
    assert loc <= max_loc, (
        f"{file_path} has {loc} LOC (limit: {max_loc}). "
        f"Refactor to reduce size or add a grandfathered exception with an issue link."
    )
