"""Record operation vertical slice.

Provides commands and events for recording operations in agent sessions.
Use the convenience factory functions for type-safe command creation:

    from aef_domain.contexts.sessions.slices.record_operation import (
        record_tool_started,
        record_tool_completed,
        record_message_response,
    )

    cmd = record_tool_started(session_id, "Read", tool_use_id, {"path": "/foo"})
"""

from aef_domain.contexts.sessions.slices.record_operation.commands import (
    record_error,
    record_message_request,
    record_message_response,
    record_thinking,
    record_tool_blocked,
    record_tool_completed,
    record_tool_started,
)
from aef_domain.contexts.sessions.events.OperationRecordedEvent import (
    OperationRecordedEvent,
)
from aef_domain.contexts.sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)

__all__ = [
    "OperationRecordedEvent",
    "RecordOperationCommand",
    "record_error",
    "record_message_request",
    "record_message_response",
    "record_thinking",
    "record_tool_blocked",
    "record_tool_completed",
    "record_tool_started",
]
