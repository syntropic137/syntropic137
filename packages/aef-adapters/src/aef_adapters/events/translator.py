"""Translator for hook events to AEF domain events.

Converts hook events (from agentic_hooks) to domain events that can
be stored in the AEF event store and processed by projections.

The translation maps hook event types to their domain equivalents:
- SESSION_STARTED -> SessionStarted
- SESSION_COMPLETED -> SessionCompleted
- TOOL_EXECUTION_STARTED -> ToolExecutionStarted
- TOOL_EXECUTION_COMPLETED -> ToolExecutionCompleted
- TOOL_BLOCKED -> ToolBlocked
- AGENT_REQUEST_STARTED -> AgentRequestStarted
- AGENT_REQUEST_COMPLETED -> AgentRequestCompleted
- USER_PROMPT_SUBMITTED -> UserPromptSubmitted
- HOOK_DECISION -> HookDecisionMade
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agentic_hooks import EventType, HookEvent


@dataclass
class DomainEvent:
    """A domain event ready for the event store.

    This is the canonical format for events in the AEF event store.
    Projections subscribe to these events for read model updates.

    Attributes:
        event_type: Domain event type name (e.g., "SessionStarted")
        aggregate_type: Type of aggregate this event belongs to
        aggregate_id: ID of the aggregate instance
        event_data: Event-specific payload
        metadata: Additional context (source hook event, timing, etc.)
        event_id: Unique event identifier
        version: Aggregate version for optimistic concurrency
        created_at: When the event was created
    """

    event_type: str
    aggregate_type: str
    aggregate_id: str
    event_data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_data": self.event_data,
            "metadata": self.metadata,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
        }


# Mapping from hook event types to domain event types
HOOK_TO_DOMAIN_EVENT_TYPE: dict[str, str] = {
    EventType.SESSION_STARTED.value: "SessionStarted",
    EventType.SESSION_COMPLETED.value: "SessionCompleted",
    EventType.TOOL_EXECUTION_STARTED.value: "ToolExecutionStarted",
    EventType.TOOL_EXECUTION_COMPLETED.value: "ToolExecutionCompleted",
    EventType.TOOL_BLOCKED.value: "ToolBlocked",
    EventType.AGENT_REQUEST_STARTED.value: "AgentRequestStarted",
    EventType.AGENT_REQUEST_COMPLETED.value: "AgentRequestCompleted",
    EventType.USER_PROMPT_SUBMITTED.value: "UserPromptSubmitted",
    EventType.HOOK_DECISION.value: "HookDecisionMade",
    EventType.CUSTOM.value: "CustomEvent",
}

# Hook events that create Session aggregates
SESSION_EVENTS = {
    "SessionStarted",
    "SessionCompleted",
    "ToolExecutionStarted",
    "ToolExecutionCompleted",
    "ToolBlocked",
    "AgentRequestStarted",
    "AgentRequestCompleted",
    "UserPromptSubmitted",
    "HookDecisionMade",
    "CustomEvent",
}


class HookToDomainTranslator:
    """Translates hook events to domain events.

    This translator converts hook events (from JSONL files) into
    domain events suitable for the AEF event store.

    The translation includes:
    1. Event type mapping (hook -> domain)
    2. Aggregate type/ID derivation
    3. Event data transformation
    4. Metadata preservation

    Example:
        translator = HookToDomainTranslator()

        hook_event = HookEvent(
            event_type=EventType.SESSION_STARTED,
            session_id="session-123",
        )

        domain_event = translator.translate(hook_event)
        # domain_event.event_type == "SessionStarted"
        # domain_event.aggregate_type == "Session"
        # domain_event.aggregate_id == "session-123"
    """

    def __init__(
        self,
        *,
        include_raw_event: bool = False,
    ) -> None:
        """Initialize the translator.

        Args:
            include_raw_event: Whether to include the raw hook event in metadata.
        """
        self._include_raw_event = include_raw_event

    def translate(self, hook_event: HookEvent) -> DomainEvent:
        """Translate a hook event to a domain event.

        Args:
            hook_event: The hook event to translate.

        Returns:
            The corresponding domain event.
        """
        # Get domain event type
        event_type_value = (
            hook_event.event_type.value
            if isinstance(hook_event.event_type, EventType)
            else hook_event.event_type
        )
        domain_event_type = HOOK_TO_DOMAIN_EVENT_TYPE.get(
            event_type_value, "CustomEvent"
        )

        # Determine aggregate type and ID
        aggregate_type, aggregate_id = self._derive_aggregate(
            hook_event, domain_event_type
        )

        # Build event data
        event_data = self._build_event_data(hook_event, domain_event_type)

        # Build metadata
        metadata = self._build_metadata(hook_event)

        return DomainEvent(
            event_type=domain_event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_data=event_data,
            metadata=metadata,
            event_id=hook_event.event_id,
            created_at=hook_event.timestamp,
        )

    def _derive_aggregate(
        self,
        hook_event: HookEvent,
        domain_event_type: str,
    ) -> tuple[str, str]:
        """Derive aggregate type and ID from hook event.

        Most hook events belong to a Session aggregate, identified by session_id.
        """
        # All session-related events use session_id as aggregate_id
        if domain_event_type in SESSION_EVENTS:
            return "Session", hook_event.session_id

        # Fallback
        return "Session", hook_event.session_id

    def _build_event_data(
        self,
        hook_event: HookEvent,
        domain_event_type: str,
    ) -> dict[str, Any]:
        """Build the domain event data payload.

        Transforms hook event data into domain-appropriate structure.
        """
        data: dict[str, Any] = {
            "session_id": hook_event.session_id,
        }

        # Add optional context
        if hook_event.workflow_id:
            data["workflow_id"] = hook_event.workflow_id
        if hook_event.phase_id:
            data["phase_id"] = hook_event.phase_id
        if hook_event.milestone_id:
            data["milestone_id"] = hook_event.milestone_id

        # Add event-specific data
        match domain_event_type:
            case "SessionStarted":
                data["started_at"] = hook_event.timestamp.isoformat()
                data.update(hook_event.data)

            case "SessionCompleted":
                data["completed_at"] = hook_event.timestamp.isoformat()
                data.update(hook_event.data)

            case "ToolExecutionStarted":
                data["tool_name"] = hook_event.data.get("tool_name", "unknown")
                data["tool_input"] = hook_event.data.get("tool_input", {})
                data["started_at"] = hook_event.timestamp.isoformat()

            case "ToolExecutionCompleted":
                data["tool_name"] = hook_event.data.get("tool_name", "unknown")
                data["tool_output"] = hook_event.data.get("tool_output")
                data["duration_ms"] = hook_event.data.get("duration_ms")
                data["success"] = hook_event.data.get("success", True)
                data["completed_at"] = hook_event.timestamp.isoformat()

            case "ToolBlocked":
                data["tool_name"] = hook_event.data.get("tool_name", "unknown")
                data["tool_input"] = hook_event.data.get("tool_input", {})
                data["reason"] = hook_event.data.get("reason", "unknown")
                data["validator"] = hook_event.data.get("validator")
                data["blocked_at"] = hook_event.timestamp.isoformat()

            case "AgentRequestStarted":
                data["model"] = hook_event.data.get("model")
                data["message_count"] = hook_event.data.get("message_count", 0)
                data["max_tokens"] = hook_event.data.get("max_tokens")
                data["temperature"] = hook_event.data.get("temperature")
                data["started_at"] = hook_event.timestamp.isoformat()

            case "AgentRequestCompleted":
                data["model"] = hook_event.data.get("model")
                data["input_tokens"] = hook_event.data.get("input_tokens", 0)
                data["output_tokens"] = hook_event.data.get("output_tokens", 0)
                data["total_tokens"] = hook_event.data.get("total_tokens", 0)
                data["duration_seconds"] = hook_event.data.get("duration_seconds")
                data["completed_at"] = hook_event.timestamp.isoformat()

            case "UserPromptSubmitted":
                data["prompt_length"] = hook_event.data.get("prompt_length", 0)
                # Don't include actual prompt content for privacy
                data["submitted_at"] = hook_event.timestamp.isoformat()

            case "HookDecisionMade":
                data["hook_type"] = hook_event.data.get("hook_type")
                data["decision"] = hook_event.data.get("decision")
                data["reason"] = hook_event.data.get("reason")
                data["decided_at"] = hook_event.timestamp.isoformat()

            case _:
                # CustomEvent or unknown - pass through all data
                data.update(hook_event.data)

        return data

    def _build_metadata(self, hook_event: HookEvent) -> dict[str, Any]:
        """Build metadata for the domain event."""
        metadata: dict[str, Any] = {
            "source": "hook_event",
            "original_event_id": hook_event.event_id,
            "original_event_type": (
                hook_event.event_type.value
                if isinstance(hook_event.event_type, EventType)
                else hook_event.event_type
            ),
        }

        if self._include_raw_event:
            metadata["raw_event"] = hook_event.to_dict()

        return metadata

    def translate_batch(
        self,
        hook_events: list[HookEvent],
    ) -> list[DomainEvent]:
        """Translate multiple hook events to domain events.

        Args:
            hook_events: List of hook events to translate.

        Returns:
            List of corresponding domain events.
        """
        return [self.translate(event) for event in hook_events]
