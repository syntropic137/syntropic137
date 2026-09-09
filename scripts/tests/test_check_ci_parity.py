"""Tests for the CI-parity gate.

The gate's product is its FAILURE: it exists to go red when a PR-gating CI job
has no local equivalent. So most of these drive `find_problems()` with mappings
that are wrong in one specific way, and assert it says so. Testing only the
parsing helpers left `def main(): return 0` as a surviving mutation, which is
the whole gate deleted with every test still green.
"""

from __future__ import annotations

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


# --- gates inside jobs, which the job mapping structurally cannot see --------
#
# The job mapping compares job ids, so a gate added as a STEP inside an
# already-mapped job was invisible to it (#1124). These drive `gate_problems()`
# and `main()` with a gate in each form a workflow can express one, because the
# first fix for #1124 saw only one of those forms.


def _repo(tmp_path: object) -> Path:
    """A repo root with a justfile, so `uses: ./...` has something to resolve."""
    root = Path(str(tmp_path))
    (root / "justfile").write_text(JUSTFILE)
    (root / ".github" / "actions").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    return root


def _mapped_job_running(step: object) -> dict[str, object]:
    """`ci.yml:unit`, which IS mapped to a local target, plus one extra step.

    The mapped job is the point: the job-level check reports this workflow as
    fully covered, so anything the step adds is coverage CI has and local does
    not.
    """
    return {"on": {"pull_request": None}, "jobs": {"unit": {"steps": [step]}}}


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ({"run": "uv run python scripts/check_orphaned.py"}, "scripts/check_orphaned.py"),
        ({"run": "just check-orphan"}, "just check-orphan"),
    ],
    ids=["script", "recipe"],
)
def test_a_gate_added_as_a_step_in_a_mapped_job_is_reported(
    step: object, expected: str, mapping: None, tmp_path: object
) -> None:
    """The #1124 defect itself, in both spellings a `run:` block can use.

    `just check-orphan` is the spelling the first fix could not see: the
    justfile defines the recipe, `qa-ci` does not reach it, and CI runs it.
    """
    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running(step)}, JUSTFILE, _repo(tmp_path)
    )

    assert len(problems) == 1
    assert expected in problems[0]


def test_a_gate_inside_a_local_composite_action_is_reported(
    mapping: None, tmp_path: object
) -> None:
    """`uses: ./.github/actions/x` hides a gate one file away from the workflow."""
    root = _repo(tmp_path)
    action = root / ".github" / "actions" / "setup"
    action.mkdir()
    (action / "action.yml").write_text(
        yaml.safe_dump({"runs": {"using": "composite", "steps": [{"run": "just check-orphan"}]}})
    )

    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"uses": "./.github/actions/setup"})},
        JUSTFILE,
        root,
    )

    assert len(problems) == 1
    assert "just check-orphan" in problems[0]
    assert "./.github/actions/setup" in problems[0]


def test_a_gate_inside_a_local_reusable_workflow_is_reported(
    mapping: None, tmp_path: object
) -> None:
    """A job that is only `uses:` has no steps of its own; its callee has them."""
    root = _repo(tmp_path)
    (root / ".github" / "workflows" / "_check.yml").write_text(
        yaml.safe_dump({"jobs": {"check": {"steps": [{"run": "just check-orphan"}]}}})
    )
    workflow_document = {
        "on": {"pull_request": None},
        "jobs": {"unit": {"uses": "./.github/workflows/_check.yml"}},
    }

    problems = check_ci_parity.gate_problems({"ci.yml": workflow_document}, JUSTFILE, root)

    assert len(problems) == 1
    assert "just check-orphan" in problems[0]


def test_a_gate_reachable_from_qa_ci_is_not_reported(mapping: None, tmp_path: object) -> None:
    """The gate must stay quiet when local really does run the step's command."""
    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"run": "just check-test-debt"})},
        JUSTFILE,
        _repo(tmp_path),
    )

    assert problems == []


def test_a_gate_in_an_already_excluded_job_inherits_that_reason(
    monkeypatch: pytest.MonkeyPatch, mapping: None, tmp_path: object
) -> None:
    """A job excluded with a reason does not need that reason repeated per step.

    Without this, every step of every release-only job would demand its own
    entry in a second table saying what the first table already says.
    """
    monkeypatch.setattr(check_ci_parity, "NOT_RUN_ON_FEATURE_PR", {"ci.yml:unit": "release only"})
    monkeypatch.setattr(check_ci_parity, "LOCAL_EQUIVALENT", {})

    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"run": "just check-orphan"})},
        JUSTFILE,
        _repo(tmp_path),
    )

    assert problems == []


def test_an_explicit_exception_entry_silences_a_gate(
    monkeypatch: pytest.MonkeyPatch, mapping: None, tmp_path: object
) -> None:
    """The escape hatch is a written-down decision, keyed by the printed token."""
    monkeypatch.setattr(
        check_ci_parity, "STEPS_WITHOUT_A_LOCAL_TARGET", {"just check-orphan": "a reason"}
    )

    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"run": "just check-orphan"})},
        JUSTFILE,
        _repo(tmp_path),
    )

    assert problems == []


def _complete_workflow(*extra_steps: object) -> dict[str, object]:
    """Every job the `mapping` fixture accounts for, so the job check is clean.

    This matters more than it looks. Built with only the one job, the stale
    entries for `ui` and `scan` make find_problems() fail on their own, and a
    main() test then returns 1 whatever the steps do - it passes with the step
    check deleted. That is this issue's defect wearing the test's clothes.
    """
    return {
        "on": {"pull_request": None},
        "jobs": {"unit": {"steps": list(extra_steps)}, "ui": {}, "scan": {}},
    }


def test_main_is_green_for_a_complete_mapping_with_a_runnable_step(
    monkeypatch: pytest.MonkeyPatch, mapping: None, tmp_path: object
) -> None:
    """The control for the test below: everything green, so 1 means the step."""
    root = _repo(tmp_path)
    monkeypatch.setattr(
        check_ci_parity, "pr_triggered_workflows", lambda _: {"ci.yml": _complete_workflow()}
    )
    monkeypatch.setattr(check_ci_parity, "JUSTFILE", root / "justfile")
    monkeypatch.setattr(check_ci_parity, "REPO_ROOT", root)

    assert check_ci_parity.main() == 0


def test_main_exits_1_for_a_step_shaped_gate(
    monkeypatch: pytest.MonkeyPatch, mapping: None, tmp_path: object
) -> None:
    """The consumer test: an unrunnable step gate must change the exit code.

    Every other test here calls `gate_problems()` directly, so all of them
    would still pass if `main()` never called it - which is exactly how the
    first fix for #1124 shipped untested. The only difference from the green
    control above is the one step.
    """
    root = _repo(tmp_path)
    monkeypatch.setattr(
        check_ci_parity,
        "pr_triggered_workflows",
        lambda _: {"ci.yml": _complete_workflow({"run": "just check-orphan"})},
    )
    monkeypatch.setattr(check_ci_parity, "JUSTFILE", root / "justfile")
    monkeypatch.setattr(check_ci_parity, "REPO_ROOT", root)

    assert check_ci_parity.main() == 1


# --- what the walk deliberately does not see, pinned so it stays deliberate --


def test_a_third_party_action_is_a_stated_blind_spot(mapping: None, tmp_path: object) -> None:
    """Its implementation is not in this repo, so nothing here can read it."""
    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"uses": "some-owner/some-action@v4"})},
        JUSTFILE,
        _repo(tmp_path),
    )

    assert problems == []


def test_a_word_that_is_not_a_recipe_is_not_a_gate(mapping: None, tmp_path: object) -> None:
    """`just` in prose, and its arguments, must not read as recipes.

    Otherwise the gate invents failures for text, and the fix for those is to
    stop writing English in a run block.
    """
    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"run": 'echo "just do it"'})},
        JUSTFILE,
        _repo(tmp_path),
    )

    assert problems == []


def test_a_cycle_between_local_workflows_terminates(mapping: None, tmp_path: object) -> None:
    """A workflow calling itself must not hang the gate that guards every PR."""
    root = _repo(tmp_path)
    (root / ".github" / "workflows" / "_loop.yml").write_text(
        yaml.safe_dump(
            {
                "jobs": {
                    "a": {
                        "steps": [
                            {"uses": "./.github/workflows/_loop.yml"},
                            {"run": "just check-orphan"},
                        ]
                    }
                }
            }
        )
    )

    problems = check_ci_parity.gate_problems(
        {"ci.yml": _mapped_job_running({"uses": "./.github/workflows/_loop.yml"})},
        JUSTFILE,
        root,
    )

    assert len(problems) == 1


def test_the_repos_own_workflows_have_no_unrunnable_gate() -> None:
    """The gate, run against the real workflows and the real justfile."""
    workflows = check_ci_parity.pr_triggered_workflows(check_ci_parity.WORKFLOW_DIR)

    assert check_ci_parity.gate_problems(workflows, check_ci_parity.JUSTFILE.read_text()) == []


def test_the_walk_follows_a_real_reusable_workflow_call() -> None:
    """Following `uses:` must be exercised against the real tree, not only fixtures.

    release-gate.yml's codegen-sync job is nothing but a call to
    _check-codegen-sync.yml, and the `just codegen` it runs lives in the callee.
    A walk that stopped at the caller would find no gate at all and report
    exactly what full coverage reports.
    """
    document = check_ci_parity.pr_triggered_workflows(check_ci_parity.WORKFLOW_DIR)[
        "release-gate.yml"
    ]
    recipes = check_ci_parity.just_targets(check_ci_parity.JUSTFILE.read_text())

    gates = check_ci_parity.workflow_gates(
        document, "release-gate.yml", check_ci_parity.REPO_ROOT, recipes
    )

    through_callee = [g for g in gates if "_check-codegen-sync.yml" in g.source]
    assert [g.token for g in through_callee] == ["just codegen"]


def test_the_repos_real_composite_action_resolves_to_its_action_file() -> None:
    """setup-vsa runs no script and no recipe, so no assertion about problems can
    tell whether the walk entered it or silently skipped it - which is this
    issue's own defect. Assert the resolution step directly instead."""
    resolved = check_ci_parity._resolve_local_uses(
        "./.github/actions/setup-vsa", check_ci_parity.REPO_ROOT
    )

    assert resolved is not None
    assert resolved.name == "action.yml"
    assert resolved.is_file()
