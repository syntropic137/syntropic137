"""Event handler mapping, provenance, and dispatch for projection manager.

Extracted from manager.py to reduce module complexity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_BLOCKED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager

logger = logging.getLogger(__name__)


@runtime_checkable
class Projection(Protocol):
    """Protocol for projections that can handle events."""

    @property
    def name(self) -> str:
        """Get the projection name."""
        ...


@dataclass(frozen=True, slots=True)
class EventProvenance:
    """Provenance metadata for events from event store."""

    stream_id: str
    global_nonce: int | None
    event_type: str

    @classmethod
    def from_envelope(cls, envelope: Any) -> EventProvenance:
        """Extract provenance from an event store envelope."""
        metadata = getattr(envelope, "metadata", None)
        if metadata is None:
            raise ValueError("Event envelope missing metadata - not from event store")
        stream_id = getattr(metadata, "stream_id", None)
        global_nonce = getattr(metadata, "global_nonce", None)
        event = getattr(envelope, "event", None)
        if event is None:
            raise ValueError("Event envelope missing event")
        event_type = getattr(event, "event_type", None) or type(event).__name__
        return cls(
            stream_id=stream_id or "unknown",
            global_nonce=global_nonce,
            event_type=event_type,
        )


EVENT_HANDLERS: dict[str, list[tuple[str, str]]] = {
    "organization.OrganizationCreated": [("organization_list", "on_organization_created")],
    "organization.OrganizationUpdated": [("organization_list", "on_organization_updated")],
    "organization.OrganizationDeleted": [("organization_list", "on_organization_deleted")],
    "organization.SystemCreated": [
        ("system_list", "on_system_created"),
        ("organization_list", "on_system_created_increment"),
    ],
    "organization.SystemUpdated": [("system_list", "on_system_updated")],
    "organization.SystemDeleted": [
        ("system_list", "on_system_deleted"),
        ("organization_list", "on_system_deleted_decrement"),
    ],
    "organization.RepoRegistered": [
        ("repo_list", "on_repo_registered"),
        ("organization_list", "on_repo_registered_increment"),
        ("system_list", "on_repo_registered_increment"),
    ],
    "organization.RepoAssignedToSystem": [
        ("repo_list", "on_repo_assigned_to_system"),
        ("system_list", "on_repo_assigned_increment"),
    ],
    "organization.RepoUnassignedFromSystem": [
        ("repo_list", "on_repo_unassigned_from_system"),
        ("system_list", "on_repo_unassigned_decrement"),
    ],
    "github.TriggerFired": [("repo_correlation", "on_trigger_fired")],
    "WorkflowTemplateCreated": [
        ("workflow_list", "on_workflow_template_created"),
        ("workflow_detail", "on_workflow_template_created"),
        ("dashboard_metrics", "on_workflow_template_created"),
    ],
    "WorkflowCreated": [
        ("workflow_list", "on_workflow_template_created"),
        ("workflow_detail", "on_workflow_template_created"),
        ("dashboard_metrics", "on_workflow_template_created"),
    ],
    "WorkflowExecutionStarted": [
        ("workflow_list", "on_workflow_execution_started"),
        ("workflow_detail", "on_workflow_execution_started"),
        ("workflow_execution_list", "on_workflow_execution_started"),
        ("workflow_execution_detail", "on_workflow_execution_started"),
        ("dashboard_metrics", "on_workflow_execution_started"),
        ("repo_correlation", "on_workflow_execution_started"),
        ("realtime", "on_workflow_execution_started"),
        ("execution_todo", "on_workflow_execution_started"),
    ],
    "PhaseStarted": [
        ("workflow_execution_detail", "on_phase_started"),
        ("workflow_phase_metrics", "on_phase_started"),
        ("realtime", "on_phase_started"),
    ],
    "PhaseCompleted": [
        ("workflow_execution_list", "on_phase_completed"),
        ("workflow_execution_detail", "on_phase_completed"),
        ("workflow_phase_metrics", "on_phase_completed"),
        ("realtime", "on_phase_completed"),
        ("execution_todo", "on_phase_completed"),
    ],
    "WorkflowCompleted": [
        ("workflow_execution_list", "on_workflow_completed"),
        ("workflow_execution_detail", "on_workflow_completed"),
        ("dashboard_metrics", "on_workflow_completed"),
        ("repo_health", "on_workflow_completed"),
        ("repo_cost", "on_workflow_completed"),
        ("realtime", "on_workflow_completed"),
        ("execution_todo", "on_workflow_completed"),
    ],
    "WorkflowFailed": [
        ("workflow_execution_list", "on_workflow_failed"),
        ("workflow_execution_detail", "on_workflow_failed"),
        ("dashboard_metrics", "on_workflow_failed"),
        ("repo_health", "on_workflow_failed"),
        ("repo_cost", "on_workflow_failed"),
        ("realtime", "on_workflow_failed"),
        ("execution_todo", "on_workflow_failed"),
    ],
    "WorkspaceProvisionedForPhase": [("execution_todo", "on_workspace_provisioned_for_phase")],
    "AgentExecutionCompleted": [("execution_todo", "on_agent_execution_completed")],
    "ArtifactsCollectedForPhase": [("execution_todo", "on_artifacts_collected_for_phase")],
    "NextPhaseReady": [("execution_todo", "on_next_phase_ready")],
    "ExecutionPaused": [
        ("workflow_execution_list", "on_execution_paused"),
        ("workflow_execution_detail", "on_execution_paused"),
    ],
    "ExecutionResumed": [
        ("workflow_execution_list", "on_execution_resumed"),
        ("workflow_execution_detail", "on_execution_resumed"),
    ],
    "ExecutionCancelled": [
        ("workflow_execution_list", "on_execution_cancelled"),
        ("workflow_execution_detail", "on_execution_cancelled"),
        ("execution_todo", "on_execution_cancelled"),
    ],
    "SessionStarted": [
        ("session_list", "on_session_started"),
        ("dashboard_metrics", "on_session_started"),
        ("realtime", "on_session_started"),
    ],
    "OperationRecorded": [
        ("session_list", "on_operation_recorded"),
        ("realtime", "on_operation_recorded"),
    ],
    "SessionCompleted": [
        ("session_list", "on_session_completed"),
        ("dashboard_metrics", "on_session_completed"),
        ("realtime", "on_session_completed"),
    ],
    "SubagentStarted": [
        ("session_list", "on_subagent_started"),
        ("realtime", "on_subagent_started"),
    ],
    "SubagentStopped": [
        ("session_list", "on_subagent_stopped"),
        ("realtime", "on_subagent_stopped"),
    ],
    "ArtifactCreated": [
        ("artifact_list", "on_artifact_created"),
        ("dashboard_metrics", "on_artifact_created"),
        ("realtime", "on_artifact_created"),
    ],
    TOOL_EXECUTION_STARTED: [("tool_timeline", "on_tool_execution_started")],
    TOOL_EXECUTION_COMPLETED: [
        ("tool_timeline", "on_tool_execution_completed"),
        ("session_cost", "on_agent_observation"),
        ("execution_cost", "on_agent_observation"),
    ],
    TOOL_BLOCKED: [("tool_timeline", "on_tool_blocked")],
    TOKEN_USAGE: [
        ("session_cost", "on_agent_observation"),
        ("execution_cost", "on_agent_observation"),
    ],
    SESSION_SUMMARY: [
        ("session_cost", "on_session_summary"),
        ("execution_cost", "on_session_summary"),
    ],
    "CostRecorded": [("session_cost", "on_cost_recorded"), ("execution_cost", "on_cost_recorded")],
    "SessionCostFinalized": [
        ("session_cost", "on_session_cost_finalized"),
        ("execution_cost", "on_session_cost_finalized"),
    ],
}


async def dispatch_to_handlers(
    mgr: ProjectionManager, event_type: str, event_data: dict[str, Any]
) -> None:
    """Internal: Dispatch event data to projection handlers.

    DO NOT CALL DIRECTLY - use process_event_envelope() in manager_dispatch.py instead.
    """
    mgr._ensure_initialized()

    handlers = EVENT_HANDLERS.get(event_type, [])
    if not handlers:
        logger.debug("No handlers registered for event type: %s", event_type)

    for projection_name, method_name in handlers:
        projection = mgr._projections.get(projection_name)
        if projection:
            handler = getattr(projection, method_name, None)
            if handler:
                try:
                    await handler(event_data)
                except Exception as e:
                    logger.error(
                        "Error in projection handler",
                        extra={
                            "projection": projection_name,
                            "method": method_name,
                            "event_type": event_type,
                            "error": str(e),
                        },
                        exc_info=True,
                    )
