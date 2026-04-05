"""Adapter classes for wrapping projections as CheckpointedProjections.

Extracted from coordinator_service.py to reduce module complexity.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from agentic_logging import get_logger
from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

if TYPE_CHECKING:
    from syn_adapters.projections.realtime import RealTimeProjection

logger = get_logger(__name__)


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase event type to snake_case handler suffix."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class RealTimeProjectionAdapter(CheckpointedProjection):
    """Adapter to make RealTimeProjection work with SubscriptionCoordinator."""

    PROJECTION_NAME = "realtime_sse"
    VERSION = 1

    def __init__(self, realtime_projection: RealTimeProjection) -> None:
        self._realtime = realtime_projection

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return {
            "WorkflowExecutionStarted",
            "PhaseStarted",
            "PhaseCompleted",
            "WorkflowCompleted",
            "WorkflowFailed",
            "SessionStarted",
            "OperationRecorded",
            "SessionCompleted",
            "ArtifactCreated",
        }

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        event_type = envelope.event.event_type
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0
        try:
            handler_name = f"on_{_camel_to_snake(event_type)}"
            handler = getattr(self._realtime, handler_name, None)
            if handler:
                await handler(event_data)
                logger.debug(
                    "Broadcasted event to SSE clients",
                    extra={"event_type": event_type, "handler": handler_name},
                )
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception as e:
            logger.error(
                "Error broadcasting to SSE clients",
                extra={"event_type": event_type, "error": str(e)},
                exc_info=True,
            )
            return ProjectionResult.SKIP


class _NamespacedProjectionAdapter(CheckpointedProjection):
    """Base adapter for namespace-qualified event types."""

    PROJECTION_NAME: ClassVar[str]
    VERSION: ClassVar[int]
    _SUBSCRIBED: ClassVar[set[str]]

    def __init__(self, projection: Any) -> None:
        self._projection = projection

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return self._SUBSCRIBED

    async def clear_all_data(self) -> None:
        await self._projection.clear_all_data()

    async def handle_event(
        self,
        envelope: Any,
        checkpoint_store: Any,
    ) -> ProjectionResult:
        event_type = envelope.event.event_type
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0
        try:
            bare = event_type.split(".")[-1]
            handler_name = f"on_{_camel_to_snake(bare)}"
            handler = getattr(self._projection, handler_name, None)
            if handler:
                await handler(event_data)
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception(
                "OrgProjectionAdapter handler failed for event %s in %s",
                event_type,
                self.PROJECTION_NAME,
            )
            return ProjectionResult.FAILURE


class OrganizationListAdapter(_NamespacedProjectionAdapter):
    PROJECTION_NAME: ClassVar[str] = "organization_list"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = {
        "organization.OrganizationCreated",
        "organization.OrganizationUpdated",
        "organization.OrganizationDeleted",
        "organization.SystemCreated",
        "organization.SystemDeleted",
        "organization.RepoRegistered",
    }


class SystemListAdapter(_NamespacedProjectionAdapter):
    PROJECTION_NAME: ClassVar[str] = "system_list"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = {
        "organization.SystemCreated",
        "organization.SystemUpdated",
        "organization.SystemDeleted",
        "organization.RepoRegistered",
        "organization.RepoAssignedToSystem",
        "organization.RepoUnassignedFromSystem",
    }


class RepoListAdapter(_NamespacedProjectionAdapter):
    PROJECTION_NAME: ClassVar[str] = "repo_list"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = {
        "organization.RepoRegistered",
        "organization.RepoAssignedToSystem",
        "organization.RepoUnassignedFromSystem",
    }


class RepoCorrelationAdapter(_NamespacedProjectionAdapter):
    """Adapter for RepoCorrelationProjection — handles mixed-namespace events.

    Subscribes to both namespaced (github.TriggerFired) and unnamespaced
    (WorkflowExecutionStarted) events. The base class split(".")[-1] logic
    handles both cases correctly:
    - "github.TriggerFired" → "TriggerFired" → on_trigger_fired
    - "WorkflowExecutionStarted" → "WorkflowExecutionStarted" → on_workflow_execution_started
    """

    PROJECTION_NAME: ClassVar[str] = "repo_correlation"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = {
        "github.TriggerFired",
        "WorkflowExecutionStarted",
    }


class TriggerHistoryAdapter(_NamespacedProjectionAdapter):
    """Adapter for TriggerHistoryProjection.

    Maps github.TriggerFired → handle_trigger_fired (projection uses
    ``handle_`` prefix instead of ``on_``).
    """

    PROJECTION_NAME: ClassVar[str] = "trigger_history"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = {"github.TriggerFired"}

    async def handle_event(
        self,
        envelope: Any,
        checkpoint_store: Any,
    ) -> ProjectionResult:
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0
        try:
            # handle_trigger_fired uses attribute access (event.trigger_id),
            # so wrap the dict in a SimpleNamespace for duck-typed access.
            from types import SimpleNamespace

            await self._projection.handle_trigger_fired(SimpleNamespace(**event_data))
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception(
                "TriggerHistoryAdapter handler failed for event in %s",
                self.PROJECTION_NAME,
            )
            return ProjectionResult.FAILURE
