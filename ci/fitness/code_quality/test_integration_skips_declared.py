"""Fitness function: an integration test that can skip says so (PC-192, PC-193, #1984).

A skipped test reports neither pass nor fail. Three PRs in one week carried
integration tests that skipped on a clean runner - an image defaulted to
``:latest``, a store was not provisioned, an env var was unset - and only the
mutation-evidence runner noticed, because a skip voids its baseline.

**What counts.** A test marked ``integration`` that can reach a skip through a
marker, its body, a same-module helper or a fixture (conftests included), and
that does not carry ``@pytest.mark.may_skip(reason=..., issue="#N")``. The
analysis is in ``scripts/check_integration_skips.py``, pinned by
``scripts/tests/test_check_integration_skips.py``.

**Exceptions.** ``[integration_skips]`` in ``fitness_exceptions.toml`` holds
the count as of the gate's introduction. It is EXACT: a higher count fails, and
so does a lower one until the value is lowered to match, so the budget can only
shrink. A malformed ``may_skip`` (no reason, no ``#N`` issue) has no budget.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ci.fitness.conftest import load_exceptions, repo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from check_integration_skips import find_integration_skips

_EXCEPTIONS_SECTION = "integration_skips"


@pytest.mark.architecture
def test_integration_skips_are_declared() -> None:
    findings = find_integration_skips(repo_root())
    malformed = [f for f in findings if f.kind == "malformed"]
    undeclared = [f for f in findings if f.kind == "undeclared"]
    budget = load_exceptions().get(_EXCEPTIONS_SECTION, {})
    allowed = int(budget.get("undeclared", 0))

    assert not malformed, (
        f"{len(malformed)} may_skip marker(s) do not declare anything. Write"
        ' @pytest.mark.may_skip(reason="<why>", issue="#N"):\n'
        + "\n".join(f"  {f.render()}" for f in malformed)
    )
    assert len(undeclared) <= allowed, (
        f"{len(undeclared)} integration tests can skip undeclared (budget {allowed},"
        f" {budget.get('issue', '#1984')}). Make the test fail when its dependency is"
        ' missing, or mark it @pytest.mark.may_skip(reason="<why>", issue="#N"):\n'
        + "\n".join(f"  {f.render()}" for f in undeclared)
    )
    assert len(undeclared) == allowed, (
        f"Undeclared integration skips went down to {len(undeclared)}. Lower"
        f" [{_EXCEPTIONS_SECTION}] undeclared in ci/fitness/fitness_exceptions.toml"
        f" from {allowed} to {len(undeclared)} so it cannot climb back."
    )
