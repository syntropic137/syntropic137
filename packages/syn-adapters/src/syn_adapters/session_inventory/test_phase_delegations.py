"""The child journal's normalised intent reaches the #894 gate intact."""

from __future__ import annotations

import pytest
from agentic_isolation.child_journal import ChildCall, ChildIntent

from syn_adapters.session_inventory.phase_delegations import delegation_attempt
from syn_domain.contexts.orchestration.ports import DelegationOutcome

pytestmark = pytest.mark.unit


def _intent(target: str | None, status: str | None, exit_code: int | None = None, **kw: object):
    return ChildIntent(
        sequence=3,
        child_invocation_id="child-3",
        call=ChildCall(
            invocation_id="inv",
            attempt_id="att",
            harness="claude",
            parent_native_id="parent",
            tool_call_id="tool",
            target_harness=target,
        ),
        child_native_id=None,
        status=status,
        exit_code=exit_code,
        **kw,
    )


def test_a_failed_codex_delegate_is_a_failed_attempt_with_its_exit_code() -> None:
    attempt = delegation_attempt(_intent("codex", "failed", 2))
    assert attempt is not None
    assert (attempt.target_harness, attempt.outcome, attempt.exit_code) == (
        "codex",
        DelegationOutcome.FAILED,
        2,
    )


def test_a_launch_failure_keeps_its_reason() -> None:
    attempt = delegation_attempt(
        _intent("codex", "launch_failed", reason="codex_sandbox_unavailable")
    )
    assert attempt is not None
    assert attempt.outcome is DelegationOutcome.FAILED
    assert attempt.reason == "codex_sandbox_unavailable"


def test_a_completed_delegate_succeeded() -> None:
    attempt = delegation_attempt(_intent("codex", "completed", 0))
    assert attempt is not None and attempt.outcome is DelegationOutcome.SUCCEEDED


def test_a_launched_delegate_with_no_end_has_no_outcome() -> None:
    attempt = delegation_attempt(_intent("codex", "launched"))
    assert attempt is not None and attempt.outcome is None


def test_a_native_subagent_is_not_a_declared_delegation() -> None:
    assert delegation_attempt(_intent(None, None)) is None
