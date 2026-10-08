"""The pushes a running phase's own workspace made, as the aggregate records them (PC-128).

Kept beside the aggregate, which is at its size limit, rather than in it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    PushedCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCommitPushedEvent import (
    PhaseCommitPushedEvent,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordPhasePushCommand,
    )


def push_event(
    command: RecordPhasePushCommand,
    *,
    status: ExecutionStatus | None,
    running_phase_id: str | None,
    workflow_id: str | None,
) -> PhaseCommitPushedEvent:
    """The event recording ``command``'s push, or ValueError.

    Refused for any phase but the running one: a push is only this run's when
    the workspace that made it was running this run's phase.
    """
    if status != ExecutionStatus.RUNNING or running_phase_id != command.phase_id:
        msg = f"Cannot record a push for {command.phase_id}: it is not the running phase"
        raise ValueError(msg)
    return PhaseCommitPushedEvent(
        workflow_id=workflow_id or "",
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        repository=command.repository,
        branch=command.branch,
        sha=command.sha,
        pushed_at=datetime.now(UTC),
    )


def read_pushed_commit(event: DomainEvent) -> PushedCommit:
    """The push a replayed `PhaseCommitPushed` records, typed or generic."""
    return PushedCommit(
        phase_id=evt(event, "phase_id"),
        repository=evt(event, "repository"),
        branch=evt(event, "branch"),
        sha=evt(event, "sha"),
    )
