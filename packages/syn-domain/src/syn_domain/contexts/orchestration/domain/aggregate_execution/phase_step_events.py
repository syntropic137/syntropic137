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
        CompletePhaseCommand,
        ProvisionWorkspaceCompletedCommand,
        RecordPhaseCommandsCommand,
        StartPhaseCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        SideEffectStatus,
    )
    from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
        AgentExecutionCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
        ArtifactsCollectedForPhaseEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseCommandsCompletedEvent import (
        PhaseCommandsCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
        PhaseCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
        PhaseStartedEvent,
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
        image_manifest=command.image_manifest,
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
        reported_evidence=list(command.reported_evidence),
        agent_provider=command.agent_provider,
        agent_model=command.agent_model,
    )


def phase_commands_event(
    command: RecordPhaseCommandsCommand, workflow_id: str
) -> PhaseCommandsCompletedEvent:
    """The `PhaseCommandsCompleted` a command Phase's finished steps record."""
    from syn_domain.contexts.orchestration.domain.events.PhaseCommandsCompletedEvent import (
        PhaseCommandsCompletedEvent,
    )

    return PhaseCommandsCompletedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        workspace_id=command.workspace_id,
        completed_at=datetime.now(UTC),
        success=command.success,
        timed_out=command.timed_out,
        steps=list(command.steps),
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
        observed_heads=list(command.observed_heads),
        refused_files=list(command.refused_files),
    )


def phase_started_event(command: StartPhaseCommand) -> PhaseStartedEvent:
    """The `PhaseStarted` a phase's start records."""
    from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
        PhaseStartedEvent,
    )

    return PhaseStartedEvent(
        workflow_id=command.workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        phase_name=command.phase_name,
        phase_order=command.phase_order,
        started_at=datetime.now(UTC),
        session_id=command.session_id,
    )


def phase_completed_event(
    command: CompletePhaseCommand,
    *,
    deliverable_recovered: bool,
    reported_side_effects: SideEffectStatus | None,
) -> PhaseCompletedEvent:
    """The `PhaseCompleted` a phase's completion records.

    `deliverable_recovered` and `reported_side_effects` come from the
    aggregate's replayed state, never the command; see `complete_phase`.
    """
    from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
        PhaseCompletedEvent,
    )

    return PhaseCompletedEvent(
        workflow_id=command.workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        completed_at=datetime.now(UTC),
        success=True,
        artifact_id=command.artifact_id,
        session_id=command.session_id,
        # Read off replayed state rather than taken from the command: the
        # salvage is decided at COLLECT_ARTIFACTS and reported here, a
        # different to-do item and possibly a different process, so the
        # only honest source is the stream. It also keeps
        # CompletePhaseCommand - and every caller of it - unchanged.
        deliverable_recovered=deliverable_recovered,
        reported_side_effects=reported_side_effects,
        input_tokens=command.input_tokens,
        output_tokens=command.output_tokens,
        cache_creation_tokens=command.cache_creation_tokens,
        cache_read_tokens=command.cache_read_tokens,
        total_tokens=command.total_tokens,
        duration_seconds=command.duration_seconds,
    )
