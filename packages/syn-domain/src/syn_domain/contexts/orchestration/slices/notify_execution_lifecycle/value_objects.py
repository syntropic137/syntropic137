"""What an execution's end tells the outside world, and which events say it (#1661).

One notice per terminal event, derived here and nowhere else, so every sink
reports the same outcome for the same execution. Delivering it is not this
module's business: see `ExecutionLifecycleSinkPort`.
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - runtime for Pydantic
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (  # noqa: TC001 - runtime for Pydantic
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

logger = logging.getLogger(__name__)


class ExecutionOutcome(StrEnum):
    """How an execution ended, as far as a notice is concerned."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionLifecycleNotice(BaseModel):
    """One execution's end, as told to a sink.

    The failure fields are present exactly when the outcome is `failed`, and
    `cancel_reason` can only be set when it is `cancelled`: a notice cannot
    claim a classification for a run that did not fail.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    workflow_id: str
    outcome: ExecutionOutcome
    #: When the terminal event says the execution ended.
    occurred_at: datetime
    failure_classification: FailureClassification | None = None
    error_message: str | None = None
    #: Optional even when cancelled: a cancel need not give a reason.
    cancel_reason: str | None = None

    @property
    def key(self) -> tuple[str, ExecutionOutcome]:
        """What a sink deduplicates on: one delivery per execution and outcome."""
        return (self.execution_id, self.outcome)

    @model_validator(mode="after")
    def _fields_match_outcome(self) -> Self:
        failed = self.outcome is ExecutionOutcome.FAILED
        if failed != (self.failure_classification is not None) or failed != (
            self.error_message is not None
        ):
            raise ValueError(
                "failure_classification and error_message are set exactly when "
                f"outcome is failed, not when it is {self.outcome}"
            )
        if self.cancel_reason is not None and self.outcome is not ExecutionOutcome.CANCELLED:
            raise ValueError(f"cancel_reason is only set when cancelled, not {self.outcome}")
        return self


def lifecycle_notice(event: DomainEvent) -> ExecutionLifecycleNotice | None:
    """The notice a terminal event owes, or None for any other event.

    `WorkflowInterrupted` is terminal too and deliberately owes nothing yet:
    an interrupted execution is resumable, and whether that is worth telling
    anyone is decided in #1661, not here.
    """
    if isinstance(event, WorkflowCompletedEvent):
        return ExecutionLifecycleNotice(
            execution_id=event.execution_id,
            workflow_id=event.workflow_id,
            outcome=ExecutionOutcome.COMPLETED,
            occurred_at=event.completed_at,
        )
    if isinstance(event, WorkflowFailedEvent):
        return ExecutionLifecycleNotice(
            execution_id=event.execution_id,
            workflow_id=event.workflow_id,
            outcome=ExecutionOutcome.FAILED,
            occurred_at=event.failed_at,
            failure_classification=event.failure_classification,
            error_message=event.error_message,
        )
    if isinstance(event, ExecutionCancelledEvent):
        return ExecutionLifecycleNotice(
            execution_id=event.execution_id,
            workflow_id=event.workflow_id,
            outcome=ExecutionOutcome.CANCELLED,
            occurred_at=event.cancelled_at,
            cancel_reason=event.reason,
        )
    return None


class NoticeDelivery(StrEnum):
    """Whether a sink has been told yet. `delivered` is final: nothing reopens it."""

    OWED = "owed"
    DELIVERED = "delivered"


class LifecycleNoticeRecord(BaseModel):
    """One notice on the to-do list, and whether it has been delivered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notice: ExecutionLifecycleNotice
    delivery: NoticeDelivery = NoticeDelivery.OWED

    @property
    def key(self) -> str:
        """The store key: one record per (execution_id, outcome), as the sink dedups."""
        return f"{self.notice.execution_id}:{self.notice.outcome}"


def read_record(row: object) -> LifecycleNoticeRecord | None:
    """A stored row as a record, or None - logged - when it cannot be read."""
    try:
        return LifecycleNoticeRecord.model_validate(row)
    except ValidationError:
        logger.warning("Unreadable execution lifecycle notice skipped: %r", row)
        return None
