"""A phase that declared delegation does not complete without one (#894)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from syn_domain.contexts.orchestration.ports import (
    DelegationAttempt,
    DelegationEvidenceUnavailableError,
    DelegationOutcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegation import (
    DelegationFailureReason,
    delegation_failure,
)

_WORKSPACE = MagicMock()


class _Evidence:
    def __init__(self, attempts: tuple[DelegationAttempt, ...] | None) -> None:
        self._attempts = attempts

    async def attempts(self, workspace: object) -> tuple[DelegationAttempt, ...]:
        if self._attempts is None:
            raise DelegationEvidenceUnavailableError("journal unreadable")
        return self._attempts


def _attempt(outcome: DelegationOutcome | None, exit_code: int | None = None) -> DelegationAttempt:
    return DelegationAttempt(
        delegate_id="child-7", target_harness="codex", outcome=outcome, exit_code=exit_code
    )


async def _reason(evidence: _Evidence | None) -> DelegationFailureReason | None:
    failure = await delegation_failure(
        evidence, _WORKSPACE, phase_id="implement", allow_delegation=True
    )
    return None if failure is None else failure.reason


@pytest.mark.asyncio
async def test_the_issue_case_no_delegate_ran_fails_the_phase() -> None:
    assert await _reason(_Evidence(())) is DelegationFailureReason.NOT_ATTEMPTED


@pytest.mark.asyncio
async def test_a_delegate_that_failed_fails_the_phase_and_is_named() -> None:
    failure = await delegation_failure(
        _Evidence((_attempt(DelegationOutcome.FAILED, exit_code=1),)),
        _WORKSPACE,
        phase_id="implement",
        allow_delegation=True,
    )
    assert failure is not None
    assert failure.reason is DelegationFailureReason.FAILED
    assert "delegate child-7 -> codex: failed (exit_code=1)" in str(failure)


@pytest.mark.asyncio
async def test_a_delegate_that_never_reported_is_not_a_success() -> None:
    assert await _reason(_Evidence((_attempt(None),))) is DelegationFailureReason.FAILED


@pytest.mark.asyncio
async def test_an_unreadable_record_is_not_a_success() -> None:
    assert await _reason(_Evidence(None)) is DelegationFailureReason.UNVERIFIABLE
    assert await _reason(None) is DelegationFailureReason.UNVERIFIABLE


@pytest.mark.asyncio
async def test_one_successful_delegate_completes_the_phase() -> None:
    attempts = (_attempt(DelegationOutcome.FAILED, 1), _attempt(DelegationOutcome.SUCCEEDED, 0))
    assert await _reason(_Evidence(attempts)) is None


@pytest.mark.asyncio
async def test_a_phase_that_declared_no_delegation_is_never_asked() -> None:
    assert (
        await delegation_failure(None, None, phase_id="implement", allow_delegation=False) is None
    )
