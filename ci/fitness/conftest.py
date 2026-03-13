"""Shared fixtures and helpers for architectural fitness functions."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest


def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[2]


_PRODUCTION_DIRS = ["apps/*/src", "packages/*/src"]
_EXCLUDED_NAMES = {"conftest.py", "__init__.py"}


def production_files(root: Path | None = None) -> list[Path]:
    """Yield all production .py files under apps/*/src and packages/*/src."""
    root = root or repo_root()
    files: list[Path] = []
    for pattern in _PRODUCTION_DIRS:
        for py_file in root.glob(f"{pattern}/**/*.py"):
            if py_file.name in _EXCLUDED_NAMES:
                continue
            if py_file.name.startswith("test_"):
                continue
            files.append(py_file)
    return sorted(files)


def load_exceptions(root: Path | None = None) -> dict[str, Any]:
    """Load fitness_exceptions.toml from the ci/fitness directory."""
    root = root or repo_root()
    toml_path = root / "ci" / "fitness" / "fitness_exceptions.toml"
    if not toml_path.exists():
        return {}
    with toml_path.open("rb") as f:
        return tomllib.load(f)


def rel_path(path: Path, root: Path | None = None) -> str:
    """Return a path relative to repo root for use as exception keys."""
    root = root or repo_root()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "architecture: Architectural fitness functions (CI-enforced structural checks)",
    )
