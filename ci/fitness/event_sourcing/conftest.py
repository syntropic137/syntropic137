"""Shared helpers for event sourcing fitness functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ci.fitness.conftest import repo_root

if TYPE_CHECKING:
    from pathlib import Path


def aggregate_files() -> list[Path]:
    """Find all non-test .py files in domain/aggregate_*/ directories."""
    root = repo_root()
    files: list[Path] = []
    for agg_dir in sorted(root.glob("packages/*/src/**/domain/aggregate_*")):
        for py_file in sorted(agg_dir.glob("*.py")):
            if py_file.name.startswith("test_") or py_file.name in ("conftest.py", "__init__.py"):
                continue
            files.append(py_file)
    return files
