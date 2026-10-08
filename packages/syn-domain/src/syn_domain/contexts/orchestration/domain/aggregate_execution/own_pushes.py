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
from syn_domain.contexts.orchestration.domain.events.PhaseCommitPushedEvent import (
    PhaseCommitPushedEvent,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordPhasePushCommand,
    )


def push_event(command: RecordPhasePushCommand, workflow_id: str) -> PhaseCommitPushedEvent:
    """The `PhaseCommitPushed` recording ``command``'s push.

    Payload only: whether the push is this run's to record is the handler's guard.
    """
    return PhaseCommitPushedEvent(
        workflow_id=workflow_id,
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
