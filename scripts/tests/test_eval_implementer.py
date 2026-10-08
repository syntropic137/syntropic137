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
)
from eval_suite import DefinitionError


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
