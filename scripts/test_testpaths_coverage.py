"""Every test file on disk must sit under a pytest testpath.

THE GATE THAT EXISTED COULD NOT CATCH THIS. The census counts tests pytest
SELECTED, so a file outside `testpaths` is invisible to it by construction: not
collected, not counted, not missed. Five separate suites had drifted out of
collection that way, including the staged-credential security tests, which
stayed broken and green simultaneously because nothing ran them.

This asks the filesystem instead of pytest, which is the only direction that
can see a file pytest never looked at.
"""

from __future__ import annotations

import ast
import pathlib
import tomllib

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Directories that legitimately hold test files pytest must NOT collect here.
_EXCLUDED = {
    # Architectural fitness checks run as their own suite via
    # `just fitness-invariants`, deliberately outside the normal run.
    "ci/fitness",
    # Submodules carry their own test configuration and CI.
    "lib",
}

_IGNORED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "build",
    "dist",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
}


def _testpaths() -> list[str]:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    paths = config["tool"]["pytest"]["ini_options"]["testpaths"]
    return [str(path).rstrip("/") for path in paths]


def _is_covered(directory: str, testpaths: list[str]) -> bool:
    return any(directory == path or directory.startswith(f"{path}/") for path in testpaths)


def _is_excluded(directory: str) -> bool:
    return any(
        directory == excluded or directory.startswith(f"{excluded}/") for excluded in _EXCLUDED
    )


def _discover_orphans() -> list[str]:
    testpaths = _testpaths()
    orphans: set[str] = set()

    for pattern in ("test_*.py", "*_test.py"):
        for path in _REPO_ROOT.rglob(pattern):
            if _IGNORED_PARTS & set(path.parts):
                continue
            directory = str(path.parent.relative_to(_REPO_ROOT))
            if _is_excluded(directory) or _is_covered(directory, testpaths):
                continue
            orphans.add(directory)

    return sorted(orphans)


def test_no_test_file_lives_outside_testpaths() -> None:
    """A test pytest never collects is not coverage, it is decoration.

    If this fails, either add the directory to `testpaths` in pyproject.toml,
    or add it to `_EXCLUDED` above WITH a reason - "it is run by a different
    job" is a reason; "it was failing" is not.
    """
    orphans = _discover_orphans()

    assert not orphans, (
        "test files exist in directories pytest never collects:\n  "
        + "\n  ".join(orphans)
        + "\n\nAdd each to testpaths in pyproject.toml, or to _EXCLUDED here "
        "with the reason it is run elsewhere."
    )


def _test_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pattern in ("test_*.py", "*_test.py"):
        for path in _REPO_ROOT.rglob(pattern):
            if _IGNORED_PARTS & set(path.parts):
                continue
            if _is_excluded(str(path.parent.relative_to(_REPO_ROOT))):
                continue
            files.append(path)
    return files


def test_no_test_method_hides_in_a_non_test_class() -> None:
    """pytest only collects methods inside classes matching `Test*`.

    A `test_` method on a helper class - `InMemoryRepo`, `FakeProvider` - is
    silently ignored: no error, no skip, no count. It is the same failure as a
    file outside testpaths, one level down, and equally invisible to a gate
    that asks pytest what it selected.
    """
    hidden: list[str] = []

    for path in _test_files():
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:  # pragma: no cover - ruff/CI catch these first
            continue

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name.startswith("Test"):
                continue
            methods = [
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and child.name.startswith("test_")
            ]
            if methods:
                relative = path.relative_to(_REPO_ROOT)
                hidden.append(f"{relative}::{node.name} ({len(methods)} methods)")

    assert not hidden, (
        "test methods live in classes pytest does not collect (must match "
        "`Test*`):\n  " + "\n  ".join(hidden)
    )
