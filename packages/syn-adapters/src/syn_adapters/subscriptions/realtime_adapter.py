"""Adapter classes for wrapping projections as CheckpointedProjections.

Extracted from coordinator_service.py to reduce module complexity.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from agentic_logging import get_logger
from event_sourcing import (
    CheckpointedProjection,
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from event_sourcing.core.checkpoint import DispatchContext

    from syn_adapters.projections.realtime import RealTimeProjection
    from syn_domain.contexts.github.slices.trigger_history.projection import (
        TriggerHistoryProjection,
    )

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
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        event_type = envelope.metadata.event_type or "Unknown"
        event_data = envelope.event.model_dump(mode="json")
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

    def __init__(self, projection: object) -> None:
        self._projection = projection

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return self._SUBSCRIBED

    async def clear_all_data(self) -> None:
        clear_fn = getattr(self._projection, "clear_all_data", None)
        if clear_fn is not None:
            await clear_fn()

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        event_type = envelope.metadata.event_type
        if not event_type:
            logger.error(
                "Event missing event_type in metadata for %s",
                self.PROJECTION_NAME,
            )
            return ProjectionResult.FAILURE
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


class _ExecutionTerminal(BaseModel):
    """The one field this adapter reads off a finished workflow execution.

    ``WorkflowCompleted`` and ``WorkflowFailed`` are orchestration events read
    here, in the github context, for one purpose: clearing the concurrency
    guard's running-execution set. Naming that dependency as a model states
    exactly what the cross-context read costs - one field - instead of
    re-deriving it from a ``dict[str, Any]`` by string key, where
    ``event_data.get("executon_id")`` would typecheck (#1268).

    ``extra="ignore"`` rather than the ``extra="forbid"`` a domain event
    carries (AGENTS.md): this is a consumer-side projection of two larger
    events, and it must keep working when either of them grows a field.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    execution_id: str = ""


class TriggerHistoryAdapter(_NamespacedProjectionAdapter):
    """Adapter for TriggerHistoryProjection.

    Maps github.TriggerFired → handle_trigger_fired and
    github.TriggerBlocked → handle_trigger_blocked.
    Also subscribes to WorkflowCompleted/WorkflowFailed to clear
    the concurrency guard's running-execution tracking.
    Projection uses ``handle_`` prefix instead of ``on_``.
    """

    PROJECTION_NAME: ClassVar[str] = "trigger_history"
    VERSION: ClassVar[int] = 3
    _SUBSCRIBED: ClassVar[set[str]] = {
        "github.TriggerFired",
        "github.TriggerBlocked",
        "WorkflowCompleted",
        "WorkflowFailed",
    }

    _projection: TriggerHistoryProjection  # narrow from base class

    def __init__(self, projection: TriggerHistoryProjection) -> None:
        super().__init__(projection)

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        event_type = envelope.metadata.event_type or "Unknown"
        global_nonce = envelope.metadata.global_nonce or 0
        try:
            await self._dispatch(envelope.event, event_type, global_nonce)
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
                "TriggerHistoryAdapter handler failed for event %s in %s",
                event_type,
                self.PROJECTION_NAME,
            )
            return ProjectionResult.FAILURE

    async def _dispatch(
        self,
        event: DomainEvent,
        event_type: str,
        global_nonce: int,
    ) -> None:
        """Route events to the appropriate handler.

        Takes the envelope's event rather than its ``model_dump()``: every
        branch below narrows straight back to a typed model, so the flattened
        dict only ever existed as the thing in between (#1268).
        """
        if event_type in ("WorkflowCompleted", "WorkflowFailed"):
            await self._handle_execution_terminal(
                _ExecutionTerminal.model_validate(event.model_dump()), event_type
            )
            return
        from syn_domain.contexts.github import TriggerBlockedEvent, TriggerFiredEvent

        if event_type == "github.TriggerBlocked":
            blocked = TriggerBlockedEvent.model_validate(event.model_dump())
            await self._projection.handle_trigger_blocked(blocked, global_nonce=global_nonce)
        else:
            fired = TriggerFiredEvent.model_validate(event.model_dump())
            await self._projection.handle_trigger_fired(fired)

    @staticmethod
    async def _handle_execution_terminal(
        terminal: _ExecutionTerminal,
        event_type: str,
    ) -> None:
        """Clear concurrency guard tracking when a workflow execution finishes.

        Cross-context subscription: this adapter (github context) listens to
        WorkflowCompleted/WorkflowFailed (orchestration context) to clear the
        in-memory running-execution set used by the concurrency guard (Guard 6).

        Fail-open: if the store is unavailable, we log and move on rather than
        blocking the projection. Worst case: one (trigger, PR) pair stays blocked
        until the next process restart (which clears the in-memory set anyway).
        """
        execution_id = terminal.execution_id
        if not execution_id:
            return
        try:
            from syn_domain.contexts.github import get_trigger_query_store

            store = get_trigger_query_store()
            await store.complete_execution(execution_id)
            logger.debug(
                "Cleared running execution %s on %s",
                execution_id,
                event_type,
            )
        except Exception:
            # Fail-open: don't block the projection checkpoint over a cleanup
            # failure. The running-execution set is in-memory and resets on
            # restart, so a missed clear is self-healing.
            logger.warning(
                "Failed to clear running execution %s on %s — "
                "concurrency guard may block until restart",
                execution_id,
                event_type,
                exc_info=True,
            )
