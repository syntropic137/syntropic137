"""CheckpointedProjection adapters for plain-class projections.

Wraps ToolTimelineProjection, ExecutionCostProjection, and SessionCostProjection
(which are plain classes with on_* handler methods) as CheckpointedProjection
instances for use with the SubscriptionCoordinator.

These projections handle observation-lane events (token_usage, tool_execution_*,
session_summary, CostRecorded, SessionCostFinalized) that use a mix of snake_case
and CamelCase event type names.
"""

from __future__ import annotations

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

from syn_adapters.subscriptions.realtime_adapter import _camel_to_snake
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_BLOCKED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from event_sourcing.core.checkpoint import DispatchContext

    from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
        SessionCostProjection,
    )
    from syn_domain.contexts.agent_sessions.slices.tool_timeline.projection import (
        ToolTimelineProjection,
    )
    from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
        ExecutionCostProjection,
    )

logger = get_logger(__name__)


class _ObservationProjectionAdapter(CheckpointedProjection):
    """Base adapter for plain-class projections that handle observation events.

    Delegates event handling to the wrapped projection's on_* methods.
    Subclasses may override ``_resolve_handler_name`` to customize the
    event-type-to-method mapping (e.g. when multiple event types route
    to the same handler like ``on_agent_observation``).
    """

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

    def _resolve_handler_name(self, event_type: str) -> str:
        """Map event_type to handler method name.

        Default: ``on_{snake_case(event_type)}``.
        Override in subclasses for non-standard mappings.
        """
        return f"on_{_camel_to_snake(event_type)}"

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
        _context: DispatchContext | None = None,
    ) -> ProjectionResult:
        event_type = envelope.metadata.event_type or "Unknown"
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0
        try:
            handler_name = self._resolve_handler_name(event_type)
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
                "ObservationProjectionAdapter handler failed for event %s in %s",
                event_type,
                self.PROJECTION_NAME,
            )
            return ProjectionResult.FAILURE


class ToolTimelineAdapter(_ObservationProjectionAdapter):
    """Adapter for ToolTimelineProjection.

    All events map directly: tool_execution_started -> on_tool_execution_started, etc.
    """

    PROJECTION_NAME: ClassVar[str] = "tool_timeline"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = {
        TOOL_EXECUTION_STARTED,
        TOOL_EXECUTION_COMPLETED,
        TOOL_BLOCKED,
    }

    def __init__(self, projection: ToolTimelineProjection) -> None:
        super().__init__(projection)


# Event-type-to-handler mapping for cost projections.
# tool_execution_completed and token_usage route to on_agent_observation
# (matching manager_event_map.py), not on_tool_execution_completed/on_token_usage.
_COST_HANDLER_MAP: dict[str, str] = {
    TOOL_EXECUTION_COMPLETED: "on_agent_observation",
    TOKEN_USAGE: "on_agent_observation",
    SESSION_SUMMARY: "on_session_summary",
    "SessionCostFinalized": "on_session_cost_finalized",
}


class ExecutionCostAdapter(_ObservationProjectionAdapter):
    """Adapter for ExecutionCostProjection.

    Uses explicit handler mapping because tool_execution_completed and
    token_usage both route to on_agent_observation, not the default
    on_{event_type} convention.
    """

    PROJECTION_NAME: ClassVar[str] = "execution_cost"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = set(_COST_HANDLER_MAP.keys())

    def __init__(self, projection: ExecutionCostProjection) -> None:
        super().__init__(projection)

    def _resolve_handler_name(self, event_type: str) -> str:
        return _COST_HANDLER_MAP.get(event_type, f"on_{_camel_to_snake(event_type)}")


class SessionCostAdapter(_ObservationProjectionAdapter):
    """Adapter for SessionCostProjection.

    Same handler mapping as ExecutionCostAdapter — both cost projections
    share the same event-to-handler routing.
    """

    PROJECTION_NAME: ClassVar[str] = "session_cost"
    VERSION: ClassVar[int] = 1
    _SUBSCRIBED: ClassVar[set[str]] = set(_COST_HANDLER_MAP.keys())

    def __init__(self, projection: SessionCostProjection) -> None:
        super().__init__(projection)

    def _resolve_handler_name(self, event_type: str) -> str:
        return _COST_HANDLER_MAP.get(event_type, f"on_{_camel_to_snake(event_type)}")
