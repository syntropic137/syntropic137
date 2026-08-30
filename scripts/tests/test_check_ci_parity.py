"""Tests for the CI-parity gate.

The gate's whole value is that it notices a ci.yml job nobody mapped. So these
tests feed it workflows whose job list it could only get right by parsing the
`jobs:` block specifically -- a naive "every 2-space key" scan returns the
trigger names from `on:` instead, and would pass a test that only looked for
the real job names being present.
"""

from __future__ import annotations

import pytest
from scripts.check_ci_parity import ci_job_names, just_targets, qa_ci_dependencies

pytestmark = pytest.mark.unit


WORKFLOW = """\
name: CI

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 3 * * 1"

concurrency:
  group: ci
  cancel-in-progress: true

jobs:
  python-qa:
    name: Python QA
    runs-on: ubuntu-latest
    steps:
      - name: Lint
        run: uv run ruff check .

  cli-node:
    name: CLI Node
    runs-on: ubuntu-latest
    steps:
      - run: pnpm run test
"""


def test_trigger_names_are_not_mistaken_for_jobs() -> None:
    """`push`, `pull_request` and `schedule` sit at a job's indentation."""
    names = ci_job_names(WORKFLOW)

    assert names == ["python-qa", "cli-node"]
    assert "push" not in names
    assert "pull_request" not in names
    assert "group" not in names


def test_scanning_stops_at_the_next_top_level_key() -> None:
    """A block after `jobs:` must not contribute names."""
    workflow = WORKFLOW + "\npermissions:\n  contents: read\n"

    assert ci_job_names(workflow) == ["python-qa", "cli-node"]


def test_a_workflow_without_jobs_is_an_error_not_an_empty_list() -> None:
    """Silently returning [] would report perfect parity for an unread file."""
    with pytest.raises(SystemExit):
        ci_job_names("name: CI\non:\n  push:\n")


def test_dependencies_include_checks_nested_under_preflight() -> None:
    """A check moved one level down is still run, and must still count."""
    justfile = (
        "qa-ci: preflight test-unit-ci\n    @echo done\n\n"
        "preflight: lint check-test-debt\n    @echo ok\n\n"
        "lint:\n    ruff check .\n\n"
        "check-test-debt:\n    python scripts/check_test_debt.py\n"
    )

    deps = qa_ci_dependencies(justfile)

    assert "check-test-debt" in deps, "a transitive check reads as unrun"
    assert "lint" in deps
    assert "dashboard-ci" not in deps


def test_a_check_reachable_from_nothing_is_not_a_dependency() -> None:
    justfile = (
        "qa-ci: preflight\n    @echo done\n\n"
        "preflight: lint\n    @echo ok\n\n"
        "lint:\n    ruff check .\n\n"
        "check-orphan:\n    echo nobody runs me\n"
    )

    assert "check-orphan" not in qa_ci_dependencies(justfile)


def test_a_missing_qa_ci_target_is_an_error() -> None:
    """Renaming qa-ci must break the gate, not silently empty its dep list."""
    with pytest.raises(SystemExit):
        qa_ci_dependencies("preflight: lint\n    @echo hi\n")


def test_targets_come_from_recipe_definitions_not_dependency_mentions() -> None:
    """`docs-site-ci` appearing only as a dependency must not count as defined."""
    justfile = "qa-ci: docs-site-ci\n    @echo done\n\nlint:\n    ruff check .\n"

    targets = just_targets(justfile)

    assert "lint" in targets
    assert "qa-ci" in targets
    assert "docs-site-ci" not in targets
