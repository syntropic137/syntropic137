"""Tests for scripts/eval_implementer.py and the implementer seed suite (#1725).

The checked-in suite is validated for real: it must parse, agree with the
workflow it names, and (on a full clone) pin each case at its fix's first
parent with every hidden test present at the fix and absent from what the
reference patch carries. Running the hidden tests is `admit`'s job, not this
file's: it builds a uv environment per case and takes minutes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eval_implementer
import yaml
from eval_implementer import (
    DEFAULT_SUITE,
    ROOT,
    ImplementerCase,
    _outcome_of,
    check_commits,
    fix_patch,
    load_suite,
    main,
    score_patch,
)
from eval_suite import DefinitionError

pytestmark = pytest.mark.unit


def _full_clone() -> bool:
    shallow = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
    )
    return shallow.returncode == 0 and shallow.stdout.strip() == "false"


needs_history = pytest.mark.skipif(not _full_clone(), reason="needs the full git history")


def _copy_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    shutil.copytree(DEFAULT_SUITE, suite)
    return suite


def test_the_seed_suite_loads_against_its_workflow() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    assert loaded.suite.workflows[0].id == "eval-implement-pinned-v1"
    assert loaded.suite.workflows[0].models == {"implement": "opus"}
    assert len(loaded.cases) == 5


def test_the_workflow_writes_a_patch_and_delivers_no_repo_change() -> None:
    workflow = yaml.safe_load((ROOT / "workflows/evals/implement-pinned/workflow.yaml").read_text())
    (phase,) = workflow["phases"]
    assert phase["output_artifacts"] == ["patch"]
    assert phase["delivers_repo_changes"] is False


def test_a_model_change_without_the_suite_is_refused(tmp_path: Path) -> None:
    suite = _copy_suite(tmp_path)
    text = (suite / "suite.yaml").read_text().replace("implement: opus", "implement: sonnet")
    (suite / "suite.yaml").write_text(text)
    with pytest.raises(DefinitionError, match="the workflow declares"):
        load_suite(suite)


def test_a_task_that_names_the_fix_pr_is_refused(tmp_path: Path) -> None:
    suite = _copy_suite(tmp_path)
    case = suite / "cases" / "exec-status-lost.yaml"
    data = yaml.safe_load(case.read_text())
    data["task"] += f"\nSee #{data['source_pr']}."
    case.write_text(yaml.safe_dump(data))
    with pytest.raises(DefinitionError, match="could fetch the fix"):
        load_suite(suite)


def test_a_case_without_hidden_tests_is_refused(tmp_path: Path) -> None:
    suite = _copy_suite(tmp_path)
    case = suite / "cases" / "exec-status-lost.yaml"
    data = yaml.safe_load(case.read_text())
    data["hidden_tests"] = []
    case.write_text(yaml.safe_dump(data))
    with pytest.raises(DefinitionError, match="hidden_tests"):
        load_suite(suite)


@pytest.mark.parametrize(
    ("pytest_exit", "outcome"),
    [(0, "PASS"), (1, "FAIL"), (2, "FAIL"), (3, "ERROR"), (4, "ERROR"), (5, "ERROR")],
)
def test_pytest_exit_codes_map_to_a_verdict_on_the_change(pytest_exit: int, outcome: str) -> None:
    # 2 is a collection error: the environment was built at the pin before the
    # patch, so a hidden test that cannot import is the change's failure. 5 is
    # nothing collected, which says nothing about the change.
    assert _outcome_of(pytest_exit) == outcome


@needs_history
def test_every_case_is_pinned_at_its_fix_s_first_parent_with_its_hidden_tests() -> None:
    assert check_commits(load_suite(DEFAULT_SUITE), ROOT) == []


@needs_history
def test_a_pin_that_is_not_the_first_parent_is_reported() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.cases[0]
    wrong = loaded.model_copy(
        update={"cases": (case.model_copy(update={"commit": case.fix_commit}),)}
    )
    assert any("first parent" in p for p in check_commits(wrong, ROOT))


@needs_history
@pytest.mark.parametrize("case", load_suite(DEFAULT_SUITE).cases, ids=lambda c: c.id)
def test_the_reference_patch_leaves_the_hidden_tests_out(case: ImplementerCase) -> None:
    patch = fix_patch(case, ROOT)
    touched = {
        line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")
    }
    assert touched, f"{case.id}: the fix changed nothing but its hidden tests"
    assert touched.isdisjoint(case.hidden_tests)


@needs_history
def test_check_passes_on_the_checked_in_suite(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    assert "5 case(s) OK" in capsys.readouterr().out


def _new_file(path: str, *lines: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
        + "".join(f"+{line}\n" for line in lines)
    )


def _addopts(opts: str) -> str:
    """A patch adding `addopts` to the tiny repository's pytest configuration."""
    return (
        "diff --git a/pyproject.toml b/pyproject.toml\n--- a/pyproject.toml\n"
        "+++ b/pyproject.toml\n@@ -1,2 +1,3 @@\n [tool.pytest.ini_options]\n"
        f' pythonpath = ["."]\n+addopts = "{opts}"\n'
    )


def _plugin(*body: str) -> str:
    """The bug left in place, and a pytest plugin outside any conftest loaded by config."""
    return _new_file("hooks.py", "import pytest", *body) + _addopts("-p hooks")


def _conftest(*body: str) -> str:
    return _new_file("tests/conftest.py", "import pytest", *body)


def _mark_second(mark: str) -> tuple[str, ...]:
    return (
        "def pytest_collection_modifyitems(items):",
        "    for item in items:",
        "        if item.name == 'test_second':",
        f"            item.add_marker(pytest.mark.{mark}(reason='bug untouched'))",
    )


_SKIP_ALL = (
    "def pytest_collection_modifyitems(items):",
    "    for item in items:",
    "        item.add_marker(pytest.mark.skip(reason='bug untouched'))",
)
_REPORT_PASSED = (
    "@pytest.hookimpl(hookwrapper=True)",
    "def pytest_runtest_makereport(item, call):",
    "    outcome = yield",
    "    outcome.get_result().outcome = 'passed'",
)


@pytest.fixture
def two_hidden_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ImplementerCase, Path]:
    """A repository whose fix adds two hidden files: one passes at the pin, one catches the bug.

    The real worktree, `git apply` and pytest subprocess run; only the uv
    environment is this interpreter's, so the test needs no lockfile or network.
    """
    monkeypatch.setattr(eval_implementer, "SYNC", ("true",))
    monkeypatch.setattr(eval_implementer, "PYTEST", (sys.executable, "-m", "pytest"))
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "eval test")
    git("config", "user.email", "eval@example.invalid")
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (repo / "bug.py").write_text("value = 0\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "pin")
    pin = git("rev-parse", "HEAD")
    (repo / "tests").mkdir()
    (repo / "tests/test_first.py").write_text("def test_first():\n    assert True\n")
    (repo / "tests/test_second.py").write_text(
        "from bug import value\n\ndef test_second():\n    assert value == 1\n"
    )
    (repo / "bug.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "fix")
    case = ImplementerCase(
        id="two-hidden-files",
        source_pr=1,
        commit=pin,
        fix_commit=git("rev-parse", "HEAD"),
        task="value must be one",
        hidden_tests=("tests/test_first.py", "tests/test_second.py"),
    )
    return case, repo


def test_the_bug_left_in_place_fails_and_the_fix_passes(
    two_hidden_files: tuple[ImplementerCase, Path],
) -> None:
    case, repo = two_hidden_files
    assert score_patch(case, "", repo).outcome == "FAIL"
    fixed = score_patch(case, fix_patch(case, repo), repo)
    assert fixed.outcome == "PASS", fixed.detail


@pytest.mark.parametrize(
    "patch",
    [
        _plugin(*_SKIP_ALL),
        _plugin(*_mark_second("skip")),
        _plugin(*_mark_second("xfail")),
        _addopts("--deselect tests/test_second.py::test_second"),
        _conftest(*_SKIP_ALL),
        _conftest(*_mark_second("skip")),
        _conftest(*_REPORT_PASSED),
    ],
    ids=[
        "plugin-skip-all",
        "plugin-skip-second",
        "plugin-xfail-second",
        "addopts-deselect-second",
        "conftest-skip-all",
        "conftest-skip-second",
        "conftest-report-passed",
    ],
)
def test_a_change_that_hides_the_bug_from_pytest_is_not_a_pass(
    two_hidden_files: tuple[ImplementerCase, Path], patch: str
) -> None:
    # Every one of these leaves the bug in place and, unchecked, exits pytest 0.
    case, repo = two_hidden_files
    run = score_patch(case, patch, repo)
    assert run.outcome == "FAIL", run.detail
    assert "test_second" in run.detail


def test_a_fix_plus_a_harmless_conftest_still_passes(
    two_hidden_files: tuple[ImplementerCase, Path],
) -> None:
    case, repo = two_hidden_files
    run = score_patch(case, fix_patch(case, repo) + _conftest("FIXTURE = 1"), repo)
    assert run.outcome == "PASS", run.detail
