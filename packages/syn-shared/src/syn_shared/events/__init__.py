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
# MUST match agentic_isolation.EventType (the producer)
TOOL_STARTED = "tool_execution_started"
TOOL_COMPLETED = "tool_execution_completed"
TOOL_BLOCKED = "tool_blocked"

# Session lifecycle events
SESSION_STARTED = "session_started"
SESSION_COMPLETED = "session_completed"
SESSION_ERROR = "session_error"
SESSION_SUMMARY = "session_summary"  # Aggregated summary with cumulative totals

# Subagent lifecycle events (Task tool spawns nested agents)
# See agentic_isolation.providers.claude_cli.EventParser for detection logic
SUBAGENT_STARTED = "subagent_started"
SUBAGENT_STOPPED = "subagent_stopped"

# Token/cost events
TOKEN_USAGE = "token_usage"
COST_RECORDED = "cost_recorded"

# Phase events
PHASE_STARTED = "phase_started"
PHASE_COMPLETED = "phase_completed"

# Error events
ERROR = "error"

# Git observability events (from agentic-primitives observability plugin)
# Emitted by post-commit, pre-push, post-merge, post-rewrite hooks and
# PreToolUse/PostToolUse git command detection (agentic-primitives PR #82)
GIT_COMMIT = "git_commit"
GIT_PUSH = "git_push"
GIT_BRANCH_CHANGED = "git_branch_changed"
GIT_OPERATION = "git_operation"

# Claude Code hook events (from observability plugin, all 14 lifecycle hooks)
TOOL_FAILED = "tool_execution_failed"
TEAMMATE_IDLE = "teammate_idle"
TASK_COMPLETED = "task_completed"

# Type-safe literal union (like TypeScript)
# MUST match the constants above and agentic_isolation.EventType
EventType = Literal[
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
    "tool_blocked",
    "session_started",
    "session_completed",
    "session_error",
    "session_summary",
    "subagent_started",
    "subagent_stopped",
    "token_usage",
    "cost_recorded",
    "phase_started",
    "phase_completed",
    "error",
    "git_commit",
    "git_push",
    "git_branch_changed",
    "git_operation",
    "teammate_idle",
    "task_completed",
]

# Runtime validation set (auto-generated from Literal)
VALID_EVENT_TYPES: set[str] = set(get_args(EventType))


def is_valid_event_type(event_type: str) -> bool:
    """Check if event type is valid."""
    return event_type in VALID_EVENT_TYPES


__all__ = [
    "COST_RECORDED",
    "ERROR",
    "GIT_BRANCH_CHANGED",
    "GIT_COMMIT",
    "GIT_OPERATION",
    "GIT_PUSH",
    "PHASE_COMPLETED",
    "PHASE_STARTED",
    "SESSION_COMPLETED",
    "SESSION_ERROR",
    "SESSION_STARTED",
    "SESSION_SUMMARY",
    "SUBAGENT_STARTED",
    "SUBAGENT_STOPPED",
    "TASK_COMPLETED",
    "TEAMMATE_IDLE",
    "TOKEN_USAGE",
    "TOOL_BLOCKED",
    "TOOL_COMPLETED",
    "TOOL_FAILED",
    "TOOL_STARTED",
    "VALID_EVENT_TYPES",
    "EventType",
    "is_valid_event_type",
]
