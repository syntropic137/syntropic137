"""OperationRecorded event - represents the fact that an operation was recorded."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event

from aef_domain.contexts.sessions._shared.value_objects import OperationType  # noqa: TC001


@event("OperationRecorded", "v1")
class OperationRecordedEvent(DomainEvent):
    """Event emitted when an operation is recorded in a session."""

    # Context
    session_id: str
    operation_id: str

    # Operation details
    operation_type: OperationType
    timestamp: datetime
    duration_seconds: float | None = None

    # Token metrics
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Tool execution details
    tool_name: str | None = None
    success: bool = True

    # Metadata
    metadata: dict[str, Any] = {}  # noqa: RUF012
