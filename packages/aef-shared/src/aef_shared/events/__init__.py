"""Shared event type definitions.

This is the SINGLE SOURCE OF TRUTH for event type names.
All producers and consumers MUST use these constants.

If you add a new event type:
1. Add the constant here
2. Add to VALID_EVENT_TYPES set
3. The type checker will catch any mismatches
"""

from typing import Literal, get_args

# Tool execution events
# MUST match agentic_events.EventType (the producer)
TOOL_STARTED = "tool_execution_started"
TOOL_COMPLETED = "tool_execution_completed"

# Session lifecycle events
SESSION_STARTED = "session_started"
SESSION_COMPLETED = "session_completed"

# Token/cost events
TOKEN_USAGE = "token_usage"
COST_RECORDED = "cost_recorded"

# Phase events
PHASE_STARTED = "phase_started"
PHASE_COMPLETED = "phase_completed"

# Error events
ERROR = "error"

# Type-safe literal union (like TypeScript)
# MUST match the constants above and agentic_events.EventType
EventType = Literal[
    "tool_execution_started",
    "tool_execution_completed",
    "session_started",
    "session_completed",
    "token_usage",
    "cost_recorded",
    "phase_started",
    "phase_completed",
    "error",
]

# Runtime validation set (auto-generated from Literal)
VALID_EVENT_TYPES: set[str] = set(get_args(EventType))


def is_valid_event_type(event_type: str) -> bool:
    """Check if event type is valid."""
    return event_type in VALID_EVENT_TYPES


__all__ = [
    "COST_RECORDED",
    "ERROR",
    "PHASE_COMPLETED",
    "PHASE_STARTED",
    "SESSION_COMPLETED",
    "SESSION_STARTED",
    "TOKEN_USAGE",
    "TOOL_COMPLETED",
    "TOOL_STARTED",
    "VALID_EVENT_TYPES",
    "EventType",
    "is_valid_event_type",
]
