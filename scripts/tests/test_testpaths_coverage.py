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
import sys
import tomllib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# The marker gate's definition of "not first-party", shared so the two guards
# cannot disagree. It skips `.claude/worktrees`, which holds whole repo copies:
# without it this guard reported every directory of every agent worktree as an
# orphan, the same false positive the marker gate once shipped.
from check_test_markers import is_excluded

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Directories that legitimately hold test files pytest must NOT collect here.
_EXCLUDED = {
    # Architectural fitness checks run as their own suite via
    # `just fitness-invariants`, deliberately outside the normal run.
    "ci/fitness",
    # Git submodules: their own repositories, their own CI. Listed
    # INDIVIDUALLY and not as "lib", because lib also holds ordinary tracked
    # content. Excluding the whole directory hid 34 tests in lib/ui-feedback -
    # this guard institutionalising the very gap it exists to find.
    "lib/agent-paradise-standards-system",
    "lib/agentic-workspace",
    "lib/event-sourcing-platform",
    "lib/syntropic137-claude-plugin",
    "lib/syntropic137-skills",
    # KNOWN GAPS, each with an issue. Listed rather than silently uncovered:
    # an exclusion someone has to read is not the same as a directory nobody
    # knows about.
    #
    # lib/ui-feedback (#856): a separate application with its own
    # dependencies. Wiring it into the root suite is its own change, not a
    # side effect of a testpaths fix.
    "lib/ui-feedback",
    # Experiment evidence for ADR-014 section 7, run by hand
    # (`uv run pytest docs/experiments/resumability-fork -q -s`, optionally
    # against a real event store via EXP_GRPC_ADDR). They measure behaviour
    # at a point in time; they are not regression tests.
    "docs/experiments/resumability-fork",
    # syn_tests/integration (#857): adding it regresses the integration gate.
    # The tests guard on `collector_url`, but the fixture DEFAULTS that to a
    # non-empty localhost URL, so they do not skip in CI - they fail against a
    # collector that was never started, and the job runs with -x.
    "syn_tests/integration",
}

#: Single files, not directories, so a new test file beside them is still
#: found. These are executable end-to-end programs whose names happen to match
#: `*_test.py`; collecting them would import them, which mutates sys.path and
#: reconfigures root logging (#858). Excluding all of `scripts` for their sake
#: hid three real test modules there, and this guard itself, which therefore
#: never ran (#1935). Pytest modules belong in scripts/tests.
_EXCLUDED_FILES = {
    "scripts/e2e_agent_in_container_test.py",
    "scripts/e2e_github_app_test.py",
    "scripts/e2e_workspace_test.py",
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
            if _IGNORED_PARTS & set(path.parts) or is_excluded(path.relative_to(_REPO_ROOT)):
                continue
            if str(path.relative_to(_REPO_ROOT)) in _EXCLUDED_FILES:
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


#: `ci/fitness` is run by its own job, so it is exempt from the testpaths
#: check, but a `test_` method on a non-`Test*` class is skipped there too. It
#: is scanned for hidden methods like everything else (#1935).
_HIDDEN_METHOD_SCANNED = {"ci/fitness"}


def _test_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pattern in ("test_*.py", "*_test.py"):
        for path in _REPO_ROOT.rglob(pattern):
            if _IGNORED_PARTS & set(path.parts) or is_excluded(path.relative_to(_REPO_ROOT)):
                continue
            if str(path.relative_to(_REPO_ROOT)) in _EXCLUDED_FILES:
                continue
            directory = str(path.parent.relative_to(_REPO_ROOT))
            scanned = any(
                directory == kept or directory.startswith(f"{kept}/")
                for kept in _HIDDEN_METHOD_SCANNED
            )
            if _is_excluded(directory) and not scanned:
                continue
            files.append(path)
    return files


def _hidden_methods(path: pathlib.Path) -> list[str]:
    """Each non-`Test*` class in `path` that declares `test_` methods."""
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except SyntaxError:  # pragma: no cover - ruff/CI catch these first
        return []
    hidden: list[str] = []
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
            hidden.append(f"{node.name} ({len(methods)} methods)")
    return hidden


def test_fitness_modules_are_scanned_for_hidden_methods() -> None:
    """ci/fitness is exempt from testpaths, not from this check."""
    scanned = {str(p.relative_to(_REPO_ROOT)) for p in _test_files()}
    assert any(path.startswith("ci/fitness/") for path in scanned)


def test_a_hidden_method_is_found(tmp_path: pathlib.Path) -> None:
    """The scanner itself, against the shape it exists to catch, plus a control."""
    module = tmp_path / "test_invariants.py"
    module.write_text(
        "class InvariantChecks:\n    def test_a(self) -> None: ...\n\n\n"
        "class TestCollected:\n    def test_b(self) -> None: ...\n"
    )
    assert _hidden_methods(module) == ["InvariantChecks (1 methods)"]


def test_no_test_method_hides_in_a_non_test_class() -> None:
    """pytest only collects methods inside classes matching `Test*`.

    A `test_` method on a helper class - `InMemoryRepo`, `FakeProvider` - is
    silently ignored: no error, no skip, no count. It is the same failure as a
    file outside testpaths, one level down, and equally invisible to a gate
    that asks pytest what it selected.
    """
    hidden = [
        f"{path.relative_to(_REPO_ROOT)}::{entry}"
        for path in _test_files()
        for entry in _hidden_methods(path)
    ]

    assert not hidden, (
        "test methods live in classes pytest does not collect (must match "
        "`Test*`):\n  " + "\n  ".join(hidden)
    )
