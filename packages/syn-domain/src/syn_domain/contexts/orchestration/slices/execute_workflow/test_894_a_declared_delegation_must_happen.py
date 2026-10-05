"""A phase that declared delegation does not complete without one (#894)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.ports import (
    DelegationAttempt,
    DelegationEvidenceUnavailableError,
    DelegationOutcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    failure_account,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegation import (
    DelegationFailedError,
    DelegationFailureReason,
    completion_failure,
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


def _run(exit_code: int) -> MagicMock:
    """An agent run as `phase_failure` reads it: exited `exit_code`, said nothing against itself."""
    result = MagicMock()
    result.command.exit_code = exit_code
    result.stream_result.error_reason = None
    result.stream_result.interrupt_requested = False
    result.stream_result.verdict.refuses_completion = False
    return result


@pytest.mark.asyncio
async def test_the_issue_case_end_to_end_a_clean_green_run_is_failed_as_platform() -> None:
    """What the processor calls, and what the failure is then counted as.

    Exit 0 and no refusal is a run `phase_failure` completes; that is the #894
    phase. The delegation gate must turn it into a failure that the phase's
    `error_message` names and `failure_account` counts as `platform` - the
    two things the execution API shows.
    """
    failure = await completion_failure(
        _run(0),
        phase_id="implement",
        evidence=_Evidence((_attempt(DelegationOutcome.FAILED, exit_code=3),)),
        workspace=_WORKSPACE,
        allow_delegation=True,
    )
    assert isinstance(failure, DelegationFailedError)
    assert "delegate child-7 -> codex: failed (exit_code=3)" in str(failure)
    assert failure_account(failure).classification is FailureClassification.PLATFORM


@pytest.mark.asyncio
async def test_a_run_that_already_failed_keeps_its_own_failure() -> None:
    failure = await completion_failure(
        _run(1),
        phase_id="implement",
        evidence=_Evidence(()),
        workspace=_WORKSPACE,
        allow_delegation=True,
    )
    assert isinstance(failure, NonZeroExitError)


@pytest.mark.asyncio
async def test_without_a_declaration_a_clean_run_completes_unasked() -> None:
    assert (
        await completion_failure(
            _run(0), phase_id="implement", evidence=None, workspace=None, allow_delegation=False
        )
        is None
    )
