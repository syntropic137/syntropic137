"""Value objects for agent sessions in the workflows bounded context.

Defines immutable data structures for session metadata and conversation storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SessionContext:
    """Metadata context for conversation/agent session storage.

    Used by ConversationStoragePort.store_session() to provide
    context about what was executed and how it performed.

    This avoids domain layer depending on adapter implementations
    by defining the contract in the domain.
    """

    execution_id: str
    """Execution ID this session belongs to."""

    phase_id: str | None
    """Phase ID if this session was part of a phase, None for standalone sessions."""

    workflow_id: str | None
    """Workflow ID if this session was part of a workflow."""

    model: str
    """AI model used (e.g., 'claude-sonnet-4', 'gpt-4')."""

    event_count: int
    """Number of events in the conversation."""

    total_input_tokens: int
    """Total input tokens consumed."""

    total_output_tokens: int
    """Total output tokens generated."""

    started_at: datetime
    """When the session started."""

    completed_at: datetime
    """When the session completed."""

    success: bool
    """Whether the session completed successfully."""

    error_message: str | None = None
    """Error message if session failed."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the session."""
