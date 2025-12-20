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
TOOL_STARTED = "tool_started"
TOOL_COMPLETED = "tool_completed"

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
EventType = Literal[
    "tool_started",
    "tool_completed",
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
    # Constants
    "TOOL_STARTED",
    "TOOL_COMPLETED",
    "SESSION_STARTED",
    "SESSION_COMPLETED",
    "TOKEN_USAGE",
    "COST_RECORDED",
    "PHASE_STARTED",
    "PHASE_COMPLETED",
    "ERROR",
    # Type
    "EventType",
    # Validation
    "VALID_EVENT_TYPES",
    "is_valid_event_type",
]
