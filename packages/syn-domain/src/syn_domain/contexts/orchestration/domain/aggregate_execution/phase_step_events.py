"""The events a phase records as it is provisioned, run and collected.

Kept out of the aggregate for the same reason as `lifecycle_events`: they are
payload assembly, not decisions. The guard that decides whether the step may
be recorded stays on the handler, and what these build is only what that
decision records.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        AgentExecutionCompletedCommand,
        ArtifactsCollectedCommand,
        ProvisionWorkspaceCompletedCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
        AgentExecutionCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
        ArtifactsCollectedForPhaseEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
        WorkspaceProvisionedForPhaseEvent,
    )


def workspace_provisioned_event(
    command: ProvisionWorkspaceCompletedCommand, workflow_id: str
) -> WorkspaceProvisionedForPhaseEvent:
    """The `WorkspaceProvisionedForPhase` a phase's verified workspace records."""
    from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
        WorkspaceProvisionedForPhaseEvent,
    )

    return WorkspaceProvisionedForPhaseEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        workspace_id=command.workspace_id,
        session_id=command.session_id,
        provisioned_at=datetime.now(UTC),
        checked_out_commits=list(command.checked_out_commits) or None,
    )


def agent_completed_event(
    command: AgentExecutionCompletedCommand, workflow_id: str
) -> AgentExecutionCompletedEvent:
    """The `AgentExecutionCompleted` a phase's finished agent records."""
    from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
        AgentExecutionCompletedEvent,
    )

    return AgentExecutionCompletedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        session_id=command.session_id,
        completed_at=datetime.now(UTC),
        exit_code=command.exit_code,
        input_tokens=command.input_tokens,
        output_tokens=command.output_tokens,
        last_agent_message=command.last_agent_message,
        reported_side_effects=command.reported_side_effects,
        reported_review_verdict=command.reported_review_verdict,
        agent_provider=command.agent_provider,
        agent_model=command.agent_model,
    )


def artifacts_collected_event(
    command: ArtifactsCollectedCommand, workflow_id: str
) -> ArtifactsCollectedForPhaseEvent:
    """The `ArtifactsCollectedForPhase` a phase's collection records."""
    from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
        ArtifactsCollectedForPhaseEvent,
    )

    return ArtifactsCollectedForPhaseEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        artifact_ids=command.artifact_ids,
        collected_at=datetime.now(UTC),
        first_content_preview=command.first_content_preview,
        session_id=command.session_id,
        deliverable_recovered=command.deliverable_recovered,
    )
