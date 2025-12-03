"""RecordOperation command - records an operation in a session."""

from __future__ import annotations

from typing import Any

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from aef_domain.contexts.sessions._shared.value_objects import OperationType  # noqa: TC001


@command("RecordOperation", "Records an operation in an agent session")
class RecordOperationCommand(BaseModel):
    """Command to record an operation (agent request, tool execution, etc.).

    Operations track individual actions within a session.
    """

    model_config = ConfigDict(frozen=True)

    # Target session
    aggregate_id: str = Field(..., description="Session ID to record operation in")

    # Operation details
    operation_type: OperationType
    duration_seconds: float | None = None

    # Token metrics (for agent requests)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Tool execution details
    tool_name: str | None = None
    success: bool = True

    # Optional metadata
    metadata: dict[str, Any] | None = None
