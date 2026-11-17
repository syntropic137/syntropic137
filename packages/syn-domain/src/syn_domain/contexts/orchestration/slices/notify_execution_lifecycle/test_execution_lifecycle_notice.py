"""#1661: each terminal event owes exactly one notice, and says how it ended."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
    WorkflowInterruptedEvent,
)
from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle import (
    ExecutionLifecycleNotice,
    ExecutionOutcome,
    lifecycle_notice,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

pytestmark = pytest.mark.unit

_AT = datetime(2026, 11, 17, 21, 30, tzinfo=UTC)


def test_completed_event_owes_a_completed_notice() -> None:
    event = WorkflowCompletedEvent(
        workflow_id="wf-1",
        execution_id="exec-1",
        completed_at=_AT,
        total_phases=2,
        completed_phases=2,
        total_input_tokens=1,
        total_output_tokens=1,
        total_tokens=2,
        total_duration_seconds=3.0,
        artifact_ids=[],
    )

    assert lifecycle_notice(event) == ExecutionLifecycleNotice(
        execution_id="exec-1",
        workflow_id="wf-1",
        outcome=ExecutionOutcome.COMPLETED,
        occurred_at=_AT,
    )


def test_failed_event_owes_a_failed_notice_with_its_classification() -> None:
    # Not the default: UNCLASSIFIED is what a dropped field would also give.
    event = WorkflowFailedEvent(
        workflow_id="wf-1",
        execution_id="exec-2",
        failed_at=_AT,
        error_message="phase verify refused the change",
        failure_classification=FailureClassification.TASK,
        completed_phases=1,
        total_phases=3,
    )

    assert lifecycle_notice(event) == ExecutionLifecycleNotice(
        execution_id="exec-2",
        workflow_id="wf-1",
        outcome=ExecutionOutcome.FAILED,
        occurred_at=_AT,
        failure_classification=FailureClassification.TASK,
        error_message="phase verify refused the change",
    )


def test_cancelled_event_owes_a_cancelled_notice_with_its_reason() -> None:
    event = ExecutionCancelledEvent(
        workflow_id="wf-1",
        execution_id="exec-3",
        phase_id="implement",
        cancelled_at=_AT,
        reason="superseded by exec-4",
    )

    assert lifecycle_notice(event) == ExecutionLifecycleNotice(
        execution_id="exec-3",
        workflow_id="wf-1",
        outcome=ExecutionOutcome.CANCELLED,
        occurred_at=_AT,
        cancel_reason="superseded by exec-4",
    )


@pytest.mark.parametrize(
    "event",
    [
        PhaseCompletedEvent(
            workflow_id="wf-1",
            execution_id="exec-1",
            phase_id="implement",
            completed_at=_AT,
            success=True,
        ),
        # Terminal, but owes nothing until #1661 decides it should.
        WorkflowInterruptedEvent(
            workflow_id="wf-1", execution_id="exec-1", phase_id="implement", interrupted_at=_AT
        ),
    ],
    ids=["phase-completed", "interrupted"],
)
def test_other_events_owe_no_notice(event: DomainEvent) -> None:
    assert lifecycle_notice(event) is None


def _completed() -> ExecutionLifecycleNotice:
    return ExecutionLifecycleNotice(
        execution_id="exec-1",
        workflow_id="wf-1",
        outcome=ExecutionOutcome.COMPLETED,
        occurred_at=_AT,
    )


def test_notice_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _completed().outcome = ExecutionOutcome.FAILED  # type: ignore[misc] - asserting the refusal


def test_notice_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ExecutionLifecycleNotice.model_validate({**_completed().model_dump(), "verdict": "blocked"})


@pytest.mark.parametrize(
    ("outcome", "classification", "error_message", "cancel_reason"),
    [
        (ExecutionOutcome.FAILED, None, None, None),
        (ExecutionOutcome.FAILED, None, "boom", None),
        (ExecutionOutcome.COMPLETED, FailureClassification.PLATFORM, "boom", None),
        (ExecutionOutcome.COMPLETED, None, None, "no"),
    ],
    ids=["failed-bare", "failed-unclassified", "completed-classified", "completed-cancel-reason"],
)
def test_notice_fields_must_match_outcome(
    outcome: ExecutionOutcome,
    classification: FailureClassification | None,
    error_message: str | None,
    cancel_reason: str | None,
) -> None:
    with pytest.raises(ValidationError):
        ExecutionLifecycleNotice(
            execution_id="exec-1",
            workflow_id="wf-1",
            outcome=outcome,
            occurred_at=_AT,
            failure_classification=classification,
            error_message=error_message,
            cancel_reason=cancel_reason,
        )
