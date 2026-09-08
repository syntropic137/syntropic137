"""Tests for the interpreter-agreement gate.

This gate's product is its FAILURE, and the reason it was rewritten is that the
previous one failed for only one of the places a Python version can be written
down. So there is one test per source of truth, and each builds a tree where
exactly that source disagrees and asserts the gate says so by name. A test that
only drives the happy path proves the check runs, not that it bites - which is
precisely the hole being closed.

The trees are real git repositories because discovery is `git ls-files`. Faking
that out would test a code path nobody runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import interpreter_agreement
import pytest
from interpreter_agreement import PythonVersion, disagreements, interpreter_problems

pytestmark = pytest.mark.unit


AGREED = "3.12"
OTHER = "3.13"

WORKFLOW = """
on:
  pull_request:
jobs:
  first:
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "{first}"
  second:
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "{second}"
"""

REUSABLE = """
on:
  workflow_call:
jobs:
  called:
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "{version}"
"""

COMPOSITE = """
name: setup
runs:
  using: composite
  steps:
    - uses: actions/setup-python@v5
      with:
        python-version: "{version}"
"""

PYPROJECT = """
[project]
requires-python = ">={floor}"

[tool.ruff]
target-version = "py{ruff}"

[tool.mypy]
python_version = "{mypy}"
"""

PRE_COMMIT = """
repos:
  - repo: local
    hooks:
      - id: debt
        entry: {entry}
        language: system
"""


def _write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tree where every source of truth exists and all of them say 3.12.

    Every test below breaks exactly one of these and nothing else, so a failure
    names the source it broke rather than leaving which one ambiguous.
    """
    _write(tmp_path, ".python-version", f"{AGREED}\n")
    _write(tmp_path, "uv.lock", "version = 1\n")
    _write(tmp_path, "pyproject.toml", PYPROJECT.format(floor=AGREED, ruff="312", mypy=AGREED))
    _write(tmp_path, "pyrightconfig.json", f'{{"pythonVersion": "{AGREED}"}}')
    _write(tmp_path, "Dockerfile", f"FROM python:{AGREED}-slim AS builder\n")
    _write(tmp_path, ".github/workflows/ci.yml", WORKFLOW.format(first=AGREED, second=AGREED))
    _write(tmp_path, ".github/workflows/_reusable.yml", REUSABLE.format(version=AGREED))
    _write(tmp_path, ".github/actions/setup/action.yml", COMPOSITE.format(version=AGREED))
    _write(tmp_path, "justfile", "check:\n    uv run python scripts/check_thing.py\n")
    _write(
        tmp_path, ".pre-commit-config.yaml", PRE_COMMIT.format(entry="uv run python scripts/x.py")
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)

    monkeypatch.setattr(
        interpreter_agreement, "running_python_version", lambda: tuple(map(int, AGREED.split(".")))
    )
    return tmp_path


def problems(root: Path) -> list[str]:
    """What the gate reports about `root`, with the tree staged so git sees it."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    return interpreter_problems(root)


def only(root: Path) -> str:
    reported = problems(root)
    assert len(reported) == 1, f"expected exactly one problem, got {reported}"
    return reported[0]


def test_a_tree_that_agrees_reports_nothing(repo: Path) -> None:
    """Otherwise every test below would pass for the wrong reason."""
    assert problems(repo) == []


# --- One test per source of truth. Each must BITE. --------------------------


def test_a_second_job_in_the_same_workflow_file_is_not_invisible(repo: Path) -> None:
    """The defect that blocked the previous fix, as a regression test.

    The old check was `re.search` over the file's raw text: one version per
    FILE, first match wins. ci.yml has four jobs with four setup-python steps,
    so three of them could say anything at all and the gate stayed green.
    """
    _write(repo, ".github/workflows/ci.yml", WORKFLOW.format(first=AGREED, second=OTHER))

    reported = only(repo)
    assert "jobs.second" in reported and "jobs.first" in reported
    assert OTHER in reported


def test_a_workflow_that_no_pull_request_triggers_is_still_read(repo: Path) -> None:
    """Reusable workflows are `workflow_call`, so job-parity never opens them.

    They still run Python. Coverage of PR-gating jobs and coverage of Python
    interpreters are different questions, and reading only the first file set
    answered the second one wrong.
    """
    _write(repo, ".github/workflows/_reusable.yml", REUSABLE.format(version=OTHER))

    assert "_reusable.yml" in only(repo)


def test_a_composite_action_is_still_read(repo: Path) -> None:
    """An action has `runs.steps`, not `jobs`; a schema-aware walk would skip it."""
    _write(repo, ".github/actions/setup/action.yml", COMPOSITE.format(version=OTHER))

    assert ".github/actions/setup/action.yml" in only(repo)


def test_a_matrix_entry_disagreeing_is_reported(repo: Path) -> None:
    """A matrix is a list under the same key, not a scalar somewhere special."""
    _write(
        repo,
        ".github/workflows/ci.yml",
        WORKFLOW.format(first=AGREED, second=AGREED)
        + f'    strategy:\n      matrix:\n        python-version: ["{AGREED}", "{OTHER}"]\n',
    )

    assert "matrix.python-version[1]" in only(repo)


def test_a_drifted_pin_file_is_reported(repo: Path) -> None:
    _write(repo, ".python-version", f"{OTHER}\n")

    assert ".python-version" in only(repo)


def test_a_requires_python_floor_above_the_agreed_version_is_reported(repo: Path) -> None:
    """A floor above the pin is not a preference; `uv sync` cannot satisfy both."""
    _write(repo, "pyproject.toml", PYPROJECT.format(floor=OTHER, ruff="312", mypy=AGREED))

    assert "requires-python" in only(repo)


def test_a_drifted_ruff_target_is_reported(repo: Path) -> None:
    _write(repo, "pyproject.toml", PYPROJECT.format(floor=AGREED, ruff="313", mypy=AGREED))

    assert "ruff target-version" in only(repo)


def test_a_drifted_mypy_version_is_reported(repo: Path) -> None:
    _write(repo, "pyproject.toml", PYPROJECT.format(floor=AGREED, ruff="312", mypy=OTHER))

    assert "mypy python_version" in only(repo)


def test_a_drifted_pyright_version_is_reported(repo: Path) -> None:
    _write(repo, "pyrightconfig.json", f'{{"pythonVersion": "{OTHER}"}}')

    assert "pyrightconfig.json" in only(repo)


def test_a_drifted_docker_base_image_is_reported(repo: Path) -> None:
    """The API and collector images run this repo's code on their own Python."""
    _write(repo, "Dockerfile", f"FROM python:{OTHER}-slim AS builder\n")

    assert "Dockerfile:1" in only(repo)


def test_the_running_interpreter_is_one_of_the_things_that_must_agree(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1018 itself: a green gate on the wrong Python is evidence about nothing."""
    monkeypatch.setattr(interpreter_agreement, "running_python_version", lambda: (3, 99))

    assert "the interpreter running this check" in only(repo)


def test_a_uv_project_with_no_pin_of_its_own_is_reported(repo: Path) -> None:
    """`uv` stops looking for a pin at the project root, so the root file misses it.

    Invisible to the agreement rule by construction - a project with no pin
    states no version to disagree with - which is why it is checked separately
    rather than assumed covered.
    """
    _write(repo, "nested/uv.lock", "version = 1\n")

    assert "nested/uv.lock" in only(repo)


def test_a_recipe_that_runs_a_script_outside_uv_is_reported(repo: Path) -> None:
    """The pin only binds through `uv`; `python3 scripts/x.py` takes PATH's."""
    _write(repo, "justfile", "check:\n    @python3 scripts/check_thing.py\n")

    assert "justfile line 2" in only(repo)


def test_a_pre_commit_hook_that_runs_a_script_outside_uv_is_reported(repo: Path) -> None:
    """`language: python` builds a venv from the ambient interpreter, silently."""
    _write(repo, ".pre-commit-config.yaml", PRE_COMMIT.format(entry="python scripts/x.py"))

    assert "hook 'debt'" in only(repo)


# --- Things that must NOT be reported, and the ways they were --------------


def test_a_container_path_is_not_mistaken_for_a_repo_script(repo: Path) -> None:
    """`docker compose exec ... python /app/scripts/seed.py` runs the image's Python.

    Which the Dockerfile declaration already covers. Reporting it would push
    someone to "fix" it by adding `uv run` inside a container that has no uv.
    """
    _write(repo, "justfile", "seed:\n    docker compose exec api python /app/scripts/seed.py\n")

    assert problems(repo) == []


def test_a_lower_floor_is_a_support_claim_not_drift(repo: Path) -> None:
    """`>=3.9` with a 3.12 pin says the code supports 3.9+, and it may."""
    _write(repo, "pyproject.toml", PYPROJECT.format(floor="3.9", ruff="312", mypy=AGREED))

    assert problems(repo) == []


def test_versions_are_compared_as_numbers_not_text(repo: Path) -> None:
    """The bug this shape invites: "3.9" > "3.12" is True for strings.

    A floor of 3.9 under a 3.12 pin is fine, and the previous check compared
    version strings for equality only - so the first ordering comparison added
    is where this would have landed.
    """
    assert (
        disagreements(
            [
                PythonVersion("pin", "3.12", (3, 12)),
                PythonVersion("floor", ">=3.9", (3, 9), minimum_only=True),
            ]
        )
        == []
    )


def test_a_version_this_gate_cannot_compare_is_reported_not_skipped(repo: Path) -> None:
    """`3.x` names no interpreter. Looking away is how the blind spot happened.

    An expression like `${{ env.PY }}` lands here too: the referent is not
    something this can follow, so it says so instead of guessing.
    """
    _write(repo, ".github/workflows/_reusable.yml", REUSABLE.format(version="3.x"))

    reported = only(repo)
    assert "'3.x'" in reported and "_reusable.yml" in reported


def test_a_submodules_own_pin_is_not_this_repos_to_set(repo: Path) -> None:
    """Submodules pin their own interpreters. `git ls-files` excludes them.

    Excluded by construction rather than by a prune list, which is the point:
    a list would have to be maintained and this cannot drift.
    """
    inner = repo / "lib" / "vendored"
    inner.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=inner, check=True)
    _write(inner, ".python-version", f"{OTHER}\n")
    subprocess.run(["git", "add", "-A"], cwd=inner, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=inner,
        check=True,
        capture_output=True,
    )

    assert problems(repo) == []


# --- The real tree ----------------------------------------------------------


def test_this_repo_agrees_with_itself() -> None:
    """The gate against the tree it guards, which is what CI actually runs."""
    root = Path(__file__).resolve().parent.parent.parent

    assert interpreter_problems(root) == []
