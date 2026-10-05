"""Shared fixtures and helpers for architectural fitness functions.

See ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md).
"""

from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path
from typing import Any

import pytest


def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[2]


_PRODUCTION_DIRS = ["apps/*/src", "packages/*/src"]
_EXCLUDED_NAMES = {"conftest.py", "__init__.py"}


def production_files(
    root: Path | None = None, *, include_package_inits: bool = False
) -> list[Path]:
    """Yield all production .py files under apps/*/src and packages/*/src.

    ``__init__.py`` is skipped unless ``include_package_inits``: most gates
    measure modules, but a class can be declared in a package initializer too.
    """
    root = root or repo_root()
    excluded = _EXCLUDED_NAMES - {"__init__.py"} if include_package_inits else _EXCLUDED_NAMES
    files: list[Path] = []
    for pattern in _PRODUCTION_DIRS:
        for py_file in root.glob(f"{pattern}/**/*.py"):
            if py_file.name in excluded:
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
    config.addinivalue_line(
        "markers",
        "host_tool(name): needs an executable the agent workspace image does not ship (#1109)",
    )


#: Set by `just fitness-invariants-agent`, and by nothing else. Only there may a
#: missing host tool skip a test; everywhere else it fails, because `preflight`
#: and CI promise those tools and a check that skips is a check that cannot fail.
AGENT_WORKSPACE_ENV = "SYN_FITNESS_IN_AGENT_WORKSPACE"


def pytest_runtest_setup(item: pytest.Item) -> None:
    if os.environ.get(AGENT_WORKSPACE_ENV) != "1":
        return
    for mark in item.iter_markers("host_tool"):
        tool = str(mark.args[0])
        if shutil.which(tool) is None:
            pytest.skip(
                f"NOT RUN in agent workspace: {item.nodeid} needs `{tool}`, "
                "which is not on PATH (#1109). CI's Architectural Fitness job runs it."
            )
