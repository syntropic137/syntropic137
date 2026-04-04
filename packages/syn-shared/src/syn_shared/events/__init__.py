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
# Values are canonical Claude Code hook names (ADR-042)
TOOL_EXECUTION_STARTED = "tool_execution_started"
TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
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
GIT_MERGE = "git_merge"
GIT_REWRITE = "git_rewrite"
GIT_CHECKOUT = "git_checkout"

# Claude Code hook events (from observability plugin, all 14 lifecycle hooks)
TOOL_EXECUTION_FAILED = "tool_execution_failed"
TEAMMATE_IDLE = "teammate_idle"
TASK_COMPLETED = "task_completed"

# Security / permission events (from agentic_events.EventType)
SECURITY_DECISION = "security_decision"
PERMISSION_REQUESTED = "permission_requested"

# Agent control events (from agentic_events.EventType)
AGENT_STOPPED = "agent_stopped"

# Context management events (from agentic_events.EventType)
CONTEXT_COMPACTED = "context_compacted"

# System / notification events (from agentic_events.EventType)
SYSTEM_NOTIFICATION = "system_notification"

# User interaction events (from agentic_events.EventType)
USER_PROMPT_SUBMITTED = "user_prompt_submitted"

# OTLP observability events (from workspace OTel push — ADR-056)
OTLP_LOG = "otlp_log"

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
    "git_merge",
    "git_rewrite",
    "git_checkout",
    "teammate_idle",
    "task_completed",
    # Added to match agentic_events.types.EventType (producer)
    "security_decision",
    "permission_requested",
    "agent_stopped",
    "context_compacted",
    "system_notification",
    "user_prompt_submitted",
    "otlp_log",
]

# Runtime validation set (auto-generated from Literal)
VALID_EVENT_TYPES: set[str] = set(get_args(EventType))


def is_valid_event_type(event_type: str) -> bool:
    """Check if event type is valid."""
    return event_type in VALID_EVENT_TYPES


__all__ = [
    "AGENT_STOPPED",
    "CONTEXT_COMPACTED",
    "COST_RECORDED",
    "ERROR",
    "GIT_BRANCH_CHANGED",
    "GIT_CHECKOUT",
    "GIT_COMMIT",
    "GIT_MERGE",
    "GIT_OPERATION",
    "GIT_PUSH",
    "GIT_REWRITE",
    "OTLP_LOG",
    "PERMISSION_REQUESTED",
    "PHASE_COMPLETED",
    "PHASE_STARTED",
    "SECURITY_DECISION",
    "SESSION_COMPLETED",
    "SESSION_ERROR",
    "SESSION_STARTED",
    "SESSION_SUMMARY",
    "SUBAGENT_STARTED",
    "SUBAGENT_STOPPED",
    "SYSTEM_NOTIFICATION",
    "TASK_COMPLETED",
    "TEAMMATE_IDLE",
    "TOKEN_USAGE",
    "TOOL_BLOCKED",
    "TOOL_EXECUTION_COMPLETED",
    "TOOL_EXECUTION_FAILED",
    "TOOL_EXECUTION_STARTED",
    "USER_PROMPT_SUBMITTED",
    "VALID_EVENT_TYPES",
    "EventType",
    "is_valid_event_type",
]
