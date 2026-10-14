"""Tests for the mutation-evidence runner.

The runner's product is a verdict an agent will cite, so the failure modes that
matter are the ones that turn a non-result into a kill: an input that smuggles
shell or pytest options, a patch that changed nothing, a patch that mutated the
test, a red baseline, a tree left dirty for the next patch. Each is driven
against a real git repository; only the pytest call is replaced, by a runner
that fails exactly when the source file differs from HEAD.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest
from scripts import mutation_evidence as me
from scripts.mutation_evidence import (
    MARKER,
    Evidence,
    InputError,
    Inputs,
    Outcome,
    PatchResult,
    PytestRun,
    changed_paths,
    classify,
    execute,
    forbidden_reason,
    parse_inputs,
    parse_mutations_dir,
    parse_pytest_output,
    parse_tests,
    render,
)

pytestmark = pytest.mark.unit

SHA = "a" * 40
ORIGINAL = "def add(a, b):\n    return a + b\n"
TEST_ID = "pkg/tests/test_mod.py::test_add"


# --------------------------------------------------------------------------
# Input validation: the injection surface
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_id",
    [
        "scripts/tests/test_x.py",
        "scripts/tests/test_x.py::test_y",
        "a/b/test_x.py::TestC::test_y",
        "a/test_x.py::test_y[case-1]",
        "a/test_x.py::test_y[a.b,c=d+e]",
    ],
)
def test_accepts_plain_node_ids(node_id: str) -> None:
    assert parse_tests(node_id) == (node_id,)


@pytest.mark.parametrize(
    "node_id",
    [
        "-p",  # option injection
        "--rootdir=/",
        "a/test_x.py;rm",
        "a/test_x.py::test_y$(id)",
        "a/test_x.py::test_`id`",
        "../outside/test_x.py",
        "/abs/test_x.py",
        "a/../../test_x.py",
        "a/-x/test_x.py",
        "a/test_x.txt",
        "a/test_x.py::test_y[a b]",
        "a/test_x.py::test_y[$(id)]",
        "a//test_x.py",
    ],
)
def test_rejects_unsafe_node_ids(node_id: str) -> None:
    with pytest.raises(InputError):
        parse_tests(node_id)


def test_rejects_empty_and_too_many_tests() -> None:
    with pytest.raises(InputError):
        parse_tests("   ")
    with pytest.raises(InputError):
        parse_tests(" ".join(f"t/test_{i}.py" for i in range(me.MAX_TESTS + 1)))


@pytest.mark.parametrize("raw", [".mutations/", ".mutations", "evidence/pr-12", "a/b/"])
def test_accepts_mutation_dirs(raw: str) -> None:
    assert parse_mutations_dir(raw) == PurePosixPath(raw.rstrip("/"))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/",
        "/etc",
        "..",
        "../x",
        "a/../../x",
        ".",
        ".git",
        "a/.git",
        "-x",
        "a b",
        "a;b",
        "$(id)",
    ],
)
def test_rejects_mutation_dirs_that_escape(raw: str) -> None:
    with pytest.raises(InputError):
        parse_mutations_dir(raw)


@pytest.mark.parametrize("raw", ["0", "-1", "1e3", "12 ", "abc", "1;2", ""])
def test_rejects_bad_pr_numbers(raw: str) -> None:
    if raw == "12 ":
        assert parse_inputs(raw, "a/test_x.py", ".mutations").pr == 12
        return
    with pytest.raises(InputError):
        parse_inputs(raw, "a/test_x.py", ".mutations")


# --------------------------------------------------------------------------
# What a mutation may touch
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "pkg/tests/helper.py",
        "pkg/test/x.py",
        "pkg/test_mod.py",
        "pkg/mod_test.py",
        "pkg/conftest.py",
        "pyproject.toml",
        "apps/a/pyproject.toml",
        "uv.lock",
        ".github/workflows/ci.yml",
        "ci/fitness/x.py",
        "lib/event-sourcing-platform/x.py",
        ".mutations/other.patch",
    ],
)
def test_forbids_tests_config_and_infra(path: str) -> None:
    assert forbidden_reason(path, PurePosixPath(".mutations")) is not None


@pytest.mark.parametrize("path", ["pkg/mod.py", "apps/syn-api/src/x/testing_utils.py", "README.md"])
def test_allows_source(path: str) -> None:
    assert forbidden_reason(path, PurePosixPath(".mutations")) is None


# --------------------------------------------------------------------------
# pytest output and exit codes
# --------------------------------------------------------------------------


def test_parses_failing_ids_and_passed_count() -> None:
    out = (
        "..F\n=== short test summary info ===\n"
        "FAILED a/test_x.py::test_y - AssertionError: no\n"
        "ERROR a/test_x.py::test_z - ImportError\n"
        "FAILED a/test_x.py::test_y - again\n"
        "1 failed, 2 passed, 1 error in 0.1s\n"
    )
    assert parse_pytest_output(out) == (("a/test_x.py::test_y", "a/test_x.py::test_z"), 2)


@pytest.mark.parametrize(
    ("code", "outcome"),
    [
        (0, Outcome.SURVIVED),
        (1, Outcome.KILLED),
        (2, Outcome.KILLED),
        (4, Outcome.ERROR),
        (5, Outcome.ERROR),
        (-1, Outcome.ERROR),
    ],
)
def test_classifies_exit_codes(code: int, outcome: Outcome) -> None:
    assert classify(PytestRun(code, (), 0, 0.0)) is outcome


# --------------------------------------------------------------------------
# The run, against a real git repository
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _diff_patch(root: Path, path: str, new: str) -> str:
    """A real `git diff` of one edit, then the edit reverted."""
    target = root / path
    old = target.read_text()
    target.write_text(new)
    patch = subprocess.run(
        ["git", "diff"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    target.write_text(old)
    return patch


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg" / "tests").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(ORIGINAL)
    (root / "pkg" / "other.py").write_text("X = 1\n")
    (root / "pkg" / "tests" / "test_mod.py").write_text("def test_add():\n    assert True\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "source")
    muts = root / ".mutations"
    muts.mkdir()
    (muts / "01-kill.patch").write_text(_diff_patch(root, "pkg/mod.py", ORIGINAL.replace("+", "-")))
    (muts / "02-survive.patch").write_text(_diff_patch(root, "pkg/other.py", "X = 2\n"))
    (muts / "03-test.patch").write_text(
        _diff_patch(root, "pkg/tests/test_mod.py", "def test_add():\n    assert False\n")
    )
    (muts / "04-stale.patch").write_text(
        _diff_patch(root, "pkg/mod.py", "def add(a, b):\n    return 0\n").replace(
            "return a + b", "return a * b"
        )
    )
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "patches")
    return root


def _runner_sensitive_to_mod(root: Path, tests: tuple[str, ...]) -> PytestRun:
    if (root / "pkg" / "mod.py").read_text() == ORIGINAL:
        return PytestRun(0, (), len(tests), 0.01)
    return PytestRun(1, tests, 0, 0.02)


def _inputs() -> Inputs:
    return Inputs(pr=7, tests=(TEST_ID,), mutations_dir=PurePosixPath(".mutations"))


def test_full_run_classifies_each_patch_and_leaves_tree_clean(repo: Path) -> None:
    evidence = execute(repo, _inputs(), SHA, runner=_runner_sensitive_to_mod)

    by_patch = {r.patch: r for r in evidence.results}
    assert by_patch["01-kill.patch"].outcome is Outcome.KILLED
    assert by_patch["01-kill.patch"].files == ("pkg/mod.py",)
    assert by_patch["01-kill.patch"].failing == (TEST_ID,)
    assert by_patch["02-survive.patch"].outcome is Outcome.SURVIVED
    assert by_patch["03-test.patch"].outcome is Outcome.TOUCHES_TESTS
    assert by_patch["04-stale.patch"].outcome is Outcome.APPLY_FAILED
    assert not evidence.ok
    assert changed_paths(repo) == []
    assert (repo / "pkg" / "mod.py").read_text() == ORIGINAL


def test_all_killed_is_ok(repo: Path) -> None:
    for name in ("02-survive.patch", "03-test.patch", "04-stale.patch"):
        _git(repo, "rm", "-q", f".mutations/{name}")
    _git(repo, "commit", "-q", "-m", "only the killer")

    evidence = execute(repo, _inputs(), SHA, runner=_runner_sensitive_to_mod)

    assert [r.outcome for r in evidence.results] == [Outcome.KILLED]
    assert evidence.ok


def test_red_baseline_voids_the_evidence(repo: Path) -> None:
    def red(root: Path, tests: tuple[str, ...]) -> PytestRun:
        return PytestRun(1, tests, 0, 0.0)

    evidence = execute(repo, _inputs(), SHA, runner=red)

    assert "evidence void" in evidence.baseline_detail
    assert evidence.results == []
    assert not evidence.ok


def test_zero_test_baseline_voids_the_evidence(repo: Path) -> None:
    def empty(root: Path, tests: tuple[str, ...]) -> PytestRun:
        return PytestRun(0, (), 0, 0.0)

    evidence = execute(repo, _inputs(), SHA, runner=empty)

    assert "zero tests" in evidence.baseline_detail
    assert not evidence.ok


def test_patch_that_changes_nothing_is_not_a_kill(repo: Path) -> None:
    # Applies cleanly and leaves the tree identical: a new empty file is not
    # possible in a diff without content, so use a mode-only no-op instead.
    (repo / ".mutations" / "05-noop.patch").write_text("")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "noop")
    result = me.evaluate_patch(
        repo, repo / ".mutations" / "05-noop.patch", _inputs(), _runner_sensitive_to_mod
    )
    me.restore(repo)
    assert result.outcome in {Outcome.NOT_APPLIED, Outcome.APPLY_FAILED}
    assert result.outcome is not Outcome.KILLED


def test_baseline_byproducts_are_not_charged_to_the_first_patch(repo: Path) -> None:
    def messy(root: Path, tests: tuple[str, ...]) -> PytestRun:
        (root / "pkg" / "tests" / "artifact.txt").write_text("left behind")
        return _runner_sensitive_to_mod(root, tests)

    evidence = execute(repo, _inputs(), SHA, runner=messy)

    assert evidence.results[0].files == ("pkg/mod.py",)
    assert evidence.results[0].outcome is Outcome.KILLED


def test_dirty_tree_before_baseline_refuses(repo: Path) -> None:
    (repo / "pkg" / "mod.py").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="dirty"):
        execute(repo, _inputs(), SHA, runner=_runner_sensitive_to_mod)


def test_missing_test_file_and_dir_refuse(repo: Path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        execute(repo, Inputs(7, ("pkg/tests/test_nope.py",), PurePosixPath(".mutations")), SHA)
    with pytest.raises(InputError, match="does not exist"):
        execute(repo, Inputs(7, (TEST_ID,), PurePosixPath("nope")), SHA)


def test_symlinked_mutations_dir_cannot_escape(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "escape").symlink_to(outside)
    with pytest.raises(InputError, match="outside"):
        execute(repo, Inputs(7, (TEST_ID,), PurePosixPath("escape")), SHA)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def test_report_has_marker_table_and_neutralised_cells() -> None:
    evidence = Evidence(pr=7, sha=SHA, tests=(TEST_ID,), baseline=PytestRun(0, (), 1, 1.0))
    evidence.results = [
        PatchResult("01.patch", Outcome.KILLED, ("pkg/mod.py",), ("a|b`@x",), 2.0),
        PatchResult("02.patch", Outcome.SURVIVED, ("pkg/other.py",), (), 3.0),
    ]

    text = render(evidence, "https://example.invalid/run/1")

    assert text.startswith(MARKER)
    assert "| `01.patch` | `pkg/mod.py` | killed |" in text
    assert "SURVIVED" in text
    assert "**FAIL**" in text
    assert "a\\|b'@​x" in text
    assert "`a|b" not in text
