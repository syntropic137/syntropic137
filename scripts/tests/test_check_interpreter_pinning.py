"""Tests for the interpreter-pinning gate.

The gate's product is its FAILURE, so most of these drive it with a command
file that is wrong in one specific way and assert it says so. The one that
carries the real weight is `test_the_repo_pins_every_interpreter_it_can`: it
runs the gate against the actual justfile and the actual `.github` tree, which
is the only assertion here that a future edit can break by accident.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import check_interpreter_pinning
from scripts.check_interpreter_pinning import (
    BLOCKED_ON_A_HUMAN,
    REPO_ROOT,
    Finding,
    main,
    problems,
    scan,
    unpinned_commands,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def commands(script: str) -> list[str]:
    return [command for _, command in unpinned_commands(script)]


# --------------------------------------------------------------------------
# The rule: which program is this machine being asked to run?
# --------------------------------------------------------------------------


def test_a_bare_interpreter_is_a_finding() -> None:
    assert commands("python3 scripts/check_untyped_dicts.py") == [
        "python3 scripts/check_untyped_dicts.py"
    ]


@pytest.mark.parametrize("program", ["python", "python3", "python3.12"])
def test_every_spelling_of_the_bare_interpreter_counts(program: str) -> None:
    """`python3.12 x.py` still asks PATH; it just asks for something narrower."""
    assert commands(f"{program} scripts/x.py") == [f"{program} scripts/x.py"]


def test_the_pinned_form_is_not_a_finding() -> None:
    assert commands("uv run python scripts/check_untyped_dicts.py") == []


def test_an_explicit_interpreter_path_is_not_a_finding() -> None:
    """`.venv/bin/python` names an interpreter. That is the whole requirement."""
    assert commands(".venv/bin/python scripts/x.py") == []


def test_a_container_is_not_this_machine() -> None:
    """`docker` is the program; the interpreter belongs to a pinned image."""
    assert commands("docker run --rm agentic-workspace:latest python3 --version") == []
    assert commands('docker compose $FILES exec -T api python -c "import syn_api"') == []


def test_a_continuation_is_joined_before_the_program_is_read() -> None:
    """Without joining, an argument on its own line reads as a command.

    This is `just selfhost-seed`: the interpreter is the last argument of a
    `docker compose run`, four lines below the word `docker`.
    """
    assert (
        commands(
            "{{compose_selfhost}} run --rm \\\n"
            "  -v $(pwd)/scripts:/app/scripts:ro \\\n"
            "  api \\\n"
            "  python /app/scripts/seed_workflows.py"
        )
        == []
    )


def test_a_command_boundary_starts_a_new_command() -> None:
    """A pipe, a substitution or an env prefix all re-enter command position."""
    assert commands('curl -sf "$URL" | python3 -m json.tool') == ["python3 -m json.tool"]
    assert commands('V=$(python3 -c "import tomllib")') == ['python3 -c "import tomllib")']
    assert commands("cargo metadata | python3 -c 'json.load(sys.stdin)'") == [
        "python3 -c 'json.load(sys.stdin)'"
    ]


def test_a_word_that_merely_contains_python_is_not_an_invocation() -> None:
    assert commands('requires-python = ">=3.12"') == []
    assert commands("echo rebuilding event-sourcing-python") == []


def test_a_commented_out_command_is_not_a_command() -> None:
    assert commands("# python3 scripts/x.py\n#!/usr/bin/env bash") == []


def test_a_just_recipe_prefix_does_not_hide_the_program() -> None:
    """`@` suppresses the echo, not the interpreter."""
    assert commands("    @python3 scripts/x.py") == ["python3 scripts/x.py"]


# --------------------------------------------------------------------------
# Reading the files: only `run:` bodies, at the right line
# --------------------------------------------------------------------------


WORKFLOW = """\
name: python3 is mentioned here but not run
on: [pull_request]
jobs:
  build:
    steps:
      - name: Inline
        run: python3 scripts/inline.py
      - name: Block
        run: |
          set -euo pipefail
          python3 scripts/block.py
"""


def test_only_run_bodies_are_scanned_and_lines_point_at_the_command(tmp_path: Path) -> None:
    """A `name:` that mentions python3 is prose. Grep cannot tell; this can."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(WORKFLOW)

    found = scan(tmp_path)

    assert [(f.line, f.command) for f in found] == [
        (7, "python3 scripts/inline.py"),
        (11, "python3 scripts/block.py"),
    ]
    assert {f.path for f in found} == {".github/workflows/ci.yml"}


def test_the_justfile_is_scanned_too(tmp_path: Path) -> None:
    """The half of the class that lives in a file this repo CAN edit."""
    (tmp_path / "justfile").write_text("check-x:\n    python3 scripts/x.py\n")
    (tmp_path / ".github").mkdir()

    assert [(f.path, f.line) for f in scan(tmp_path)] == [("justfile", 2)]


# --------------------------------------------------------------------------
# The allowlist, in both directions
# --------------------------------------------------------------------------


ALLOWLISTED = next(iter(BLOCKED_ON_A_HUMAN))
ALLOWLISTED_PATH, _, ALLOWLISTED_COMMAND = ALLOWLISTED.partition("::")


def every_allowlisted_finding() -> list[Finding]:
    """The findings the allowlist describes, as the scanner would report them."""
    return [
        Finding(key.partition("::")[0], 1, key.partition("::")[2]) for key in BLOCKED_ON_A_HUMAN
    ]


def test_an_allowlisted_finding_is_not_reported() -> None:
    assert problems(every_allowlisted_finding()) == []


def test_the_same_command_in_another_file_is_still_reported() -> None:
    """The allowlist exempts a known line, not a spelling."""
    reported = problems([*every_allowlisted_finding(), Finding("justfile", 1, ALLOWLISTED_COMMAND)])

    assert len(reported) == 1
    assert reported[0].startswith("justfile:1")


def test_an_allowlisted_entry_that_no_longer_exists_is_an_error() -> None:
    """The half that makes the #1242 handoff self-closing.

    Applying the workflow diff and deleting the entry are one change. If they
    were two, the list would outlive the fix and grant a permanent exemption
    that nothing would ever question.
    """
    reported = problems([])

    assert len(reported) == len(BLOCKED_ON_A_HUMAN)
    assert all("no longer exists" in problem for problem in reported)
    assert any(ALLOWLISTED in problem for problem in reported)


def test_an_unpinned_command_is_reported_with_the_fix() -> None:
    reported = problems(
        [*every_allowlisted_finding(), Finding("justfile", 42, "python3 scripts/x.py")]
    )

    assert len(reported) == 1
    assert "justfile:42" in reported[0]
    assert "uv run python" in reported[0]


# --------------------------------------------------------------------------
# The gate itself
# --------------------------------------------------------------------------


def test_the_repo_pins_every_interpreter_it_can() -> None:
    """The assertion a future edit can break.

    Fails on `main` before this gate landed: five justfile recipes ran repo
    scripts through a bare `python3`, including the `untyped-dicts` fitness
    function and `just check-version`.
    """
    assert problems(scan(REPO_ROOT)) == []


def test_the_gate_fails_when_there_is_a_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    """`main` must carry the exit code, not just print.

    Without this, replacing the body of `main` with `return 0` deletes the gate
    and leaves every other test in this file green.
    """
    monkeypatch.setattr(
        check_interpreter_pinning,
        "scan",
        lambda _root: [Finding("justfile", 1, "python3 scripts/x.py")],
    )

    assert main() == 1


def test_the_gate_passes_on_this_repo() -> None:
    assert main() == 0
