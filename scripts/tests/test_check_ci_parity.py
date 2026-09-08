"""Tests for the CI-parity gate.

The gate's product is its FAILURE: it exists to go red when a PR-gating CI job
has no local equivalent. So most of these drive `find_problems()` with mappings
that are wrong in one specific way, and assert it says so. Testing only the
parsing helpers left `def main(): return 0` as a surviving mutation, which is
the whole gate deleted with every test still green.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from scripts import check_ci_parity
from scripts.check_ci_parity import (
    ci_python_version,
    find_problems,
    job_ids,
    just_targets,
    local_python_version,
    pr_triggered_workflows,
    qa_ci_dependencies,
)

pytestmark = pytest.mark.unit


JUSTFILE = (
    "qa-ci: preflight test-unit-ci dashboard-ci\n    @echo done\n\n"
    "preflight: lint check-test-debt\n    @echo ok\n\n"
    "lint:\n    ruff check .\n\n"
    "check-test-debt:\n    python scripts/check_test_debt.py\n\n"
    "test-unit-ci:\n    pytest -m unit\n\n"
    "dashboard-ci:\n    pnpm build\n\n"
    "check-orphan:\n    echo nobody runs me\n"
)


def _justfile_at(tmp_path: object) -> Path:
    """The fixture justfile on disk, so main() reads it the way it really does."""
    path = Path(str(tmp_path)) / "justfile"
    path.write_text(JUSTFILE)
    return path


def workflow(*jobs: str) -> dict[str, object]:
    return {"on": {"pull_request": None}, "jobs": {job: {} for job in jobs}}


@pytest.fixture
def mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """A known-good mapping, so each test can break exactly one thing."""
    monkeypatch.setattr(
        check_ci_parity,
        "LOCAL_EQUIVALENT",
        {"ci.yml:unit": "test-unit-ci", "ci.yml:ui": "dashboard-ci"},
    )
    monkeypatch.setattr(check_ci_parity, "IMPOSSIBLE_LOCALLY", {"ci.yml:scan": "remote database"})
    monkeypatch.setattr(check_ci_parity, "AGGREGATOR_ONLY", frozenset())
    monkeypatch.setattr(check_ci_parity, "NOT_RUN_ON_FEATURE_PR", {})
    monkeypatch.setattr(check_ci_parity, "RUNNABLE_BUT_EXCLUDED", {})


# --- the gate's failures -----------------------------------------------------


def test_a_complete_mapping_reports_no_problems(mapping: None) -> None:
    problems, covered, total = find_problems({"ci.yml": workflow("unit", "ui", "scan")}, JUSTFILE)

    assert problems == []
    assert (covered, total) == (2, 3)


def test_a_new_unmapped_job_is_a_problem(mapping: None) -> None:
    """The failure the gate exists for: CI gained coverage, local did not."""
    problems, _, _ = find_problems(
        {"ci.yml": workflow("unit", "ui", "scan", "brand-new")}, JUSTFILE
    )

    assert len(problems) == 1
    assert "ci.yml:brand-new" in problems[0]


def test_a_job_in_another_pr_workflow_is_a_problem(mapping: None) -> None:
    """ci.yml is not the only workflow that gates a PR."""
    problems, _, _ = find_problems(
        {"ci.yml": workflow("unit", "ui", "scan"), "docs-lint.yml": workflow("lint-content")},
        JUSTFILE,
    )

    assert len(problems) == 1
    assert "docs-lint.yml:lint-content" in problems[0]


def test_a_mapping_to_a_nonexistent_target_is_a_problem(
    monkeypatch: pytest.MonkeyPatch, mapping: None
) -> None:
    monkeypatch.setattr(check_ci_parity, "LOCAL_EQUIVALENT", {"ci.yml:unit": "no-such-target"})

    problems, covered, _ = find_problems({"ci.yml": workflow("unit")}, JUSTFILE)

    assert covered == 0
    assert "does not exist" in problems[0]


def test_a_target_qa_ci_does_not_reach_is_a_problem(
    monkeypatch: pytest.MonkeyPatch, mapping: None
) -> None:
    """Defined but unreachable is the subtlest way coverage disappears."""
    monkeypatch.setattr(check_ci_parity, "LOCAL_EQUIVALENT", {"ci.yml:unit": "check-orphan"})

    problems, covered, _ = find_problems({"ci.yml": workflow("unit")}, JUSTFILE)

    assert covered == 0
    assert "does not run" in problems[0]


def test_a_mapping_for_a_job_that_no_longer_exists_is_a_problem(mapping: None) -> None:
    """A rename leaves a stale entry that would otherwise mask its replacement."""
    problems, _, _ = find_problems({"ci.yml": workflow("unit", "scan")}, JUSTFILE)

    assert len(problems) == 1
    assert "ci.yml:ui" in problems[0]
    assert "no longer" in problems[0]


def test_a_stale_unmapped_entry_is_a_problem_too(mapping: None) -> None:
    """Both mapping tables must be checked for staleness, not just the first.

    Comparing only LOCAL_EQUIVALENT against the live jobs was a surviving
    mutation: every test made a LOCAL_EQUIVALENT entry stale and none made an
    unmapped one stale, so half the staleness check was never exercised.
    """
    problems, _, _ = find_problems({"ci.yml": workflow("unit", "ui")}, JUSTFILE)

    assert len(problems) == 1
    assert "ci.yml:scan" in problems[0]
    assert "no longer" in problems[0]


def test_every_unmapped_category_suppresses_the_unmapped_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job in any of the four buckets counts as accounted for."""
    monkeypatch.setattr(check_ci_parity, "LOCAL_EQUIVALENT", {})
    monkeypatch.setattr(check_ci_parity, "IMPOSSIBLE_LOCALLY", {"ci.yml:a": "github only"})
    monkeypatch.setattr(check_ci_parity, "AGGREGATOR_ONLY", frozenset({"ci.yml:b"}))
    monkeypatch.setattr(check_ci_parity, "NOT_RUN_ON_FEATURE_PR", {"ci.yml:c": "release only"})
    monkeypatch.setattr(check_ci_parity, "RUNNABLE_BUT_EXCLUDED", {"ci.yml:d": "too slow"})

    problems, covered, total = find_problems({"ci.yml": workflow("a", "b", "c", "d")}, JUSTFILE)

    assert problems == []
    assert (covered, total) == (0, 4)


def test_each_unmapped_reason_says_which_category_it_came_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The categories only help if the printed reason distinguishes them."""
    monkeypatch.setattr(check_ci_parity, "IMPOSSIBLE_LOCALLY", {"w:a": "github only"})
    monkeypatch.setattr(check_ci_parity, "AGGREGATOR_ONLY", frozenset({"w:b"}))
    monkeypatch.setattr(check_ci_parity, "NOT_RUN_ON_FEATURE_PR", {"w:c": "release only"})
    monkeypatch.setattr(check_ci_parity, "RUNNABLE_BUT_EXCLUDED", {"w:d": "too slow"})

    reasons = check_ci_parity.unmapped_reasons()

    assert reasons["w:a"].startswith("impossible locally")
    assert reasons["w:b"].startswith("aggregator")
    assert reasons["w:c"].startswith("not run on a feature PR")
    assert reasons["w:d"].startswith("runnable locally, excluded")


def test_a_check_nested_under_preflight_still_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving a check one level down must not read as removing it."""
    monkeypatch.setattr(check_ci_parity, "LOCAL_EQUIVALENT", {"ci.yml:qa": "check-test-debt"})
    monkeypatch.setattr(check_ci_parity, "IMPOSSIBLE_LOCALLY", {})
    monkeypatch.setattr(check_ci_parity, "AGGREGATOR_ONLY", frozenset())
    monkeypatch.setattr(check_ci_parity, "NOT_RUN_ON_FEATURE_PR", {})
    monkeypatch.setattr(check_ci_parity, "RUNNABLE_BUT_EXCLUDED", {})

    problems, covered, _ = find_problems({"ci.yml": workflow("qa")}, JUSTFILE)

    assert problems == []
    assert covered == 1


# --- main(), the exit code callers actually see ------------------------------


def test_main_exits_1_on_drift(
    monkeypatch: pytest.MonkeyPatch, mapping: None, tmp_path: object
) -> None:
    monkeypatch.setattr(
        check_ci_parity, "pr_triggered_workflows", lambda _: {"ci.yml": workflow("unmapped")}
    )
    monkeypatch.setattr(check_ci_parity, "JUSTFILE", _justfile_at(tmp_path))

    assert check_ci_parity.main() == 1


def test_main_exits_0_when_the_mapping_is_complete(
    monkeypatch: pytest.MonkeyPatch, mapping: None, tmp_path: object
) -> None:
    monkeypatch.setattr(
        check_ci_parity,
        "pr_triggered_workflows",
        lambda _: {"ci.yml": workflow("unit", "ui", "scan")},
    )
    monkeypatch.setattr(check_ci_parity, "JUSTFILE", _justfile_at(tmp_path))

    assert check_ci_parity.main() == 0


def test_main_refuses_to_report_parity_when_it_found_no_workflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading nothing must fail closed; zero jobs would otherwise be zero drift."""
    monkeypatch.setattr(check_ci_parity, "pr_triggered_workflows", lambda _: {})

    assert check_ci_parity.main() == 1


def test_the_repos_own_mapping_is_current() -> None:
    """The gate, run against the real workflows and the real justfile."""
    workflows = check_ci_parity.pr_triggered_workflows(check_ci_parity.WORKFLOW_DIR)
    problems, _, _ = find_problems(workflows, check_ci_parity.JUSTFILE.read_text())

    assert problems == []


# --- workflow discovery and parsing ------------------------------------------


def test_only_pull_request_triggered_workflows_are_collected(tmp_path: object) -> None:
    """A push-only workflow does not gate a PR and must not demand a mapping."""
    directory = Path(str(tmp_path))
    (directory / "pr.yml").write_text(yaml.safe_dump(workflow("a")))
    (directory / "push-only.yml").write_text(
        yaml.safe_dump({"on": {"push": {"branches": ["main"]}}, "jobs": {"b": {}}})
    )

    assert set(pr_triggered_workflows(directory)) == {"pr.yml"}


@pytest.mark.parametrize(
    "text",
    [
        "on: pull_request\njobs:\n  build: {}\n",
        "on: [push, pull_request]\njobs:\n  build: {}\n",
        "on:\n  pull_request:\n    branches: [main]\njobs:\n  build: {}\n",
    ],
    ids=["scalar", "list", "mapping"],
)
def test_every_trigger_spelling_github_accepts_is_recognised(text: str, tmp_path: object) -> None:
    """GitHub accepts a scalar, a list and a mapping; missing one hides a workflow."""
    directory = Path(str(tmp_path))
    (directory / "w.yml").write_text(text)

    assert set(pr_triggered_workflows(directory)) == {"w.yml"}


def test_the_bare_on_key_is_found_despite_yaml_resolving_it_to_true(
    tmp_path: object,
) -> None:
    """PyYAML turns the key `on` into the boolean True; unhandled, nothing matches."""
    directory = Path(str(tmp_path))
    (directory / "ci.yml").write_text("on:\n  pull_request:\njobs:\n  build: {}\n")

    assert set(pr_triggered_workflows(directory)) == {"ci.yml"}


@pytest.mark.parametrize(
    "text",
    [
        "jobs: # a trailing comment\n  build: {}\n",
        'jobs:\n  "build-job": {}\n',
        "jobs:\n  Build_Job: {}\n",
        "jobs:\n  _build: {}\n",
        "jobs: &anchor\n  build: {}\n",
    ],
    ids=["comment", "quoted", "uppercase", "underscore", "anchor"],
)
def test_valid_workflow_yaml_that_a_line_regex_misreads(text: str) -> None:
    """Each of these made the previous line-based parser report zero jobs.

    Reporting zero jobs is the dangerous direction: it reads as perfect parity.
    """
    assert len(job_ids(yaml.safe_load(text))) == 1


def test_a_workflow_without_jobs_is_an_error_not_an_empty_list() -> None:
    with pytest.raises(SystemExit):
        job_ids({"on": {"pull_request": None}})


def test_a_missing_qa_ci_target_is_an_error() -> None:
    """Renaming qa-ci must break the gate, not silently empty its dep list."""
    with pytest.raises(SystemExit):
        qa_ci_dependencies("preflight: lint\n    @echo hi\n")


def test_targets_come_from_recipe_definitions_not_dependency_mentions() -> None:
    targets = just_targets(JUSTFILE)

    assert {"lint", "qa-ci", "check-orphan"} <= targets
    assert "ruff" not in targets


def test_the_pinned_python_version_is_read_from_the_workflow() -> None:
    assert ci_python_version('    python-version: "3.12"\n') == "3.12"
    assert ci_python_version("    python-version: 3.13\n") == "3.13"
    assert ci_python_version("no pin here\n") is None


def test_the_local_python_version_is_a_minor_version() -> None:
    assert local_python_version().count(".") == 1


# --- The interpreter itself (#1018) -----------------------------------------
#
# `qa-ci` claims "CI will pass". It cannot mean that if the tests ran on an
# interpreter CI never uses, so the version is part of the parity contract and
# these drive it the same way the rest of this file drives the job mapping:
# through the gate's failure.


def test_the_repo_pins_the_interpreter_ci_uses() -> None:
    """A committed pin is what makes the mismatch impossible rather than noticed.

    `uv` reads `.python-version` before falling back to the newest interpreter
    on the machine, so this file is the mechanism; everything below is only the
    check that it has not drifted.
    """
    pin = check_ci_parity.PYTHON_PIN

    assert pin.is_file(), f"{pin.name} is missing: nothing makes a local venv match CI"
    assert pin.read_text().strip() == ci_python_version(
        (check_ci_parity.WORKFLOW_DIR / "ci.yml").read_text()
    )


def test_main_fails_when_the_gate_runs_on_an_interpreter_ci_does_not_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dropped hop this guards: a checker that exists but nothing calls.

    Driven through `main()` against the real repo, because a mismatch that only
    `python_version_problems()` knows about still reports "CI will pass".
    """
    monkeypatch.setattr(check_ci_parity, "local_python_version", lambda: "3.99")

    assert check_ci_parity.main() == 1


def test_main_passes_on_the_pinned_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction: the pinned interpreter must not be reported as drift.

    Pinned rather than ambient so this asserts the same thing on a machine that
    is currently running the wrong Python - which is exactly when it is read.
    """
    monkeypatch.setattr(
        check_ci_parity,
        "local_python_version",
        lambda: check_ci_parity.PYTHON_PIN.read_text().strip(),
    )

    assert check_ci_parity.main() == 0


def test_an_unpinned_repo_is_a_problem() -> None:
    """#1018 itself: `requires-python = ">=3.12"` alone resolves to 3.14."""
    problems = check_ci_parity.python_version_problems({"ci.yml": "3.12"}, None, "3.12")

    assert len(problems) == 1
    assert ".python-version" in problems[0]


def test_a_pin_that_drifted_from_ci_is_a_problem() -> None:
    """Bumping ci.yml and forgetting the pin recreates the bug, silently."""
    problems = check_ci_parity.python_version_problems({"ci.yml": "3.13"}, "3.12", "3.13")

    assert len(problems) == 1
    assert "3.12" in problems[0] and "3.13" in problems[0]


def test_ci_disagreeing_with_itself_is_reported_not_guessed() -> None:
    """With two pins there is no version a local venv could match; say so."""
    problems = check_ci_parity.python_version_problems(
        {"ci.yml": "3.12", "e2e-container.yml": "3.13", "docs-lint.yml": None}, "3.12", "3.12"
    )

    assert len(problems) == 1
    assert "e2e-container.yml" in problems[0]


def test_ci_pinning_nothing_leaves_nothing_to_match() -> None:
    """No pin anywhere means CI takes the runner default; there is no contract."""
    assert check_ci_parity.python_version_problems({"docs-lint.yml": None}, None, "3.14") == []


def test_every_uv_project_this_repo_owns_pins_the_same_interpreter() -> None:
    """`just feedback-install` is a second `uv sync`, with the same defect.

    A lockfile marks a project whose interpreter resolves on its own: `uv` stops
    looking for a pin at the project root, so the root file does not reach one.
    Discovered from the tracked lockfiles rather than listed, because a list
    here would drift the moment someone adds a third project - the same bug one
    level up. Submodules pin their own interpreters and are not this repo's to
    set; `git ls-files` excludes them by construction.
    """
    root = check_ci_parity.REPO_ROOT
    locks = subprocess.run(
        ["git", "ls-files", "*uv.lock"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    expected = check_ci_parity.PYTHON_PIN.read_text().strip()

    assert "uv.lock" in locks, "no root project found: discovery is broken, not the repo"
    for lock in locks:
        pin = root / lock.replace("uv.lock", ".python-version")
        assert pin.is_file(), f"{lock} is a uv project with no pinned interpreter"
        assert pin.read_text().strip() == expected
