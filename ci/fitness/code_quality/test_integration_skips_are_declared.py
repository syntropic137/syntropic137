"""Fitness: an integration test that can skip says so (PC-192/PC-193).

A skipped integration test is reported as a pass. In one week three PRs went
green with their integration tests skipped on a clean runner: an image
defaulted to ``:latest``, a store was not provisioned, an env var was unset.
The mutation-evidence runner caught them by voiding its baselines; the build
did not, and could not, because ``python-integration-tests`` does not run on
feature-branch PRs. A static check runs on every PR.

The rule: an integration test that can skip carries
``@pytest.mark.may_skip(reason="...", issue="#N")`` on itself, its class or
its module. What "can skip" means, and its limits, is defined in
``scripts/check_integration_skips.py`` and pinned by
``scripts/tests/test_check_integration_skips.py``. It lives in ``scripts/`` so
mutation evidence can patch it; the runner refuses patches under ``ci/``.

**Ratchet.** ``[integration_skips] max_undeclared`` in
``fitness_exceptions.toml`` is the exact count of undeclared skips. Above it
fails: a new silent skip. Below it also fails, asking for the number to be
lowered, so a fix is banked and the budget can only shrink. A malformed
``may_skip`` (no reason, or no ``#N`` issue) always fails: a declaration with
no owner is not one.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ci.fitness.conftest import load_exceptions, repo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from check_integration_skips import Problem, scan_repo

_SECTION = "integration_skips"


@pytest.mark.architecture
def test_integration_skips_are_declared() -> None:
    findings = scan_repo(repo_root())
    malformed = [f for f in findings if f.problem is not Problem.UNDECLARED]
    undeclared = [f for f in findings if f.problem is Problem.UNDECLARED]
    budget = int(load_exceptions()[_SECTION]["max_undeclared"])

    assert not malformed, "Malformed may_skip markers (need reason=... and issue='#N'):\n" + "\n".join(
        str(f) for f in malformed
    )
    assert len(undeclared) <= budget, (
        f"{len(undeclared)} integration tests can skip undeclared, budget {budget}. "
        "A skipped integration test passes CI having checked nothing. Make the test "
        "fail instead of skipping, or declare it with "
        '@pytest.mark.may_skip(reason="...", issue="#N"):\n' + "\n".join(str(f) for f in undeclared)
    )
    assert len(undeclared) == budget, (
        f"Undeclared integration skips fell to {len(undeclared)}. Lower "
        f"[{_SECTION}] max_undeclared in ci/fitness/fitness_exceptions.toml from "
        f"{budget} to {len(undeclared)} so the ratchet keeps the gain."
    )
