"""Tests for the CI-parity gate.

The gate's product is its FAILURE: it exists to go red when a PR-gating CI job
has no local equivalent. So most of these drive `find_problems()` with mappings
that are wrong in one specific way, and assert it says so. Testing only the
parsing helpers left `def main(): return 0` as a surviving mutation, which is
the whole gate deleted with every test still green.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def workflow(*jobs: str) -> dict[str, Any]:
    return {"on": {"pull_request": None}, "jobs": {job: {} for job in jobs}}


@pytest.fixture
def mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """A known-good mapping, so each test can break exactly one thing."""
    monkeypatch.setattr(
        check_ci_parity,
        "LOCAL_EQUIVALENT",
        {"ci.yml:unit": "test-unit-ci", "ci.yml:ui": "dashboard-ci"},
    )
    monkeypatch.setattr(
        check_ci_parity, "NO_LOCAL_EQUIVALENT", {"ci.yml:scan": "queries a remote database"}
    )


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


def test_a_check_nested_under_preflight_still_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving a check one level down must not read as removing it."""
    monkeypatch.setattr(check_ci_parity, "LOCAL_EQUIVALENT", {"ci.yml:qa": "check-test-debt"})
    monkeypatch.setattr(check_ci_parity, "NO_LOCAL_EQUIVALENT", {})

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
