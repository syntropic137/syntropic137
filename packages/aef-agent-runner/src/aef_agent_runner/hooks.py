"""SDK Hooks for observability and safety.

This module provides hook callbacks for the claude-agent-sdk that:
1. Emit observability events (non-blocking) to stdout as JSONL
2. Validate tool usage for safety (blocking, can deny dangerous operations)

Design: These hooks can later be extracted to agentic-primitives
as the standardized interface for both SDK and CLI agents.

Available SDK Hooks (Python):
- PreToolUse: Called before tool execution
- PostToolUse: Called after tool execution
- UserPromptSubmit: Called when user submits a prompt
- Stop: Called when stopping execution
- SubagentStop: Called when a subagent stops
- PreCompact: Called before message compaction

NOT available in Python SDK (setup limitation):
- SessionStart
- SessionEnd
- Notification
"""

from __future__ import annotations

import logging
from typing import Any

from aef_agent_runner.events import (
    emit_context_compacting,
    emit_execution_stopped,
    emit_prompt_submitted,
    emit_subagent_stopped,
    emit_tool_result,
    emit_tool_use,
)

logger = logging.getLogger(__name__)

# =============================================================================
# DANGEROUS COMMAND PATTERNS (for safety validation)
# =============================================================================

DANGEROUS_BASH_PATTERNS: list[str] = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    ":(){ :|:& };:",  # Fork bomb
    "> /dev/sda",
    "> /dev/nvme",
    "mkfs.",
    "dd if=/dev/zero of=/dev/",
    "dd if=/dev/random of=/dev/",
    "chmod -R 777 /",
    "chown -R",
    "wget http",  # Potentially dangerous downloads without https
    "curl http",  # Potentially dangerous downloads without https
]


# =============================================================================
# OBSERVABILITY HOOKS (Non-blocking)
# =============================================================================


async def on_pre_tool_use(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Emit tool_started event before tool execution. Non-blocking.

    Args:
        input_data: Contains tool_name, tool_input
        tool_use_id: Unique ID for this tool invocation
        _context: Hook context (unused for observability)

    Returns:
        Empty dict (non-blocking, allows execution to continue)
    """
    tool_name = input_data.get("tool_name", "unknown")
    tool_input = input_data.get("tool_input", {})

    emit_tool_use(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_use_id=tool_use_id,
    )

    logger.debug("PreToolUse: %s (id=%s)", tool_name, tool_use_id)
    return {}  # Non-blocking


async def on_post_tool_use(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Emit tool_completed event after tool execution. Non-blocking.

    Args:
        input_data: Contains tool_name, tool_result
        tool_use_id: Unique ID for this tool invocation
        _context: Hook context (unused for observability)

    Returns:
        Empty dict (non-blocking)
    """
    tool_name = input_data.get("tool_name", "unknown")
    tool_result = input_data.get("tool_result", {})

    # Determine success from result
    is_error = False
    if isinstance(tool_result, dict):
        is_error = tool_result.get("is_error", False)

    emit_tool_result(
        tool_name=tool_name,
        success=not is_error,
        tool_use_id=tool_use_id,
    )

    logger.debug("PostToolUse: %s (id=%s, success=%s)", tool_name, tool_use_id, not is_error)
    return {}  # Non-blocking


async def on_user_prompt_submit(
    input_data: dict[str, Any],
    _tool_use_id: str | None,  # Not used for this hook
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Emit prompt_submitted event when user submits a prompt. Non-blocking.

    Args:
        input_data: Contains prompt
        _tool_use_id: Not used for this hook
        _context: Hook context (unused)

    Returns:
        Empty dict (non-blocking)
    """
    prompt = input_data.get("prompt", "")

    # Truncate long prompts for the event
    prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt

    emit_prompt_submitted(prompt_preview)

    logger.debug("UserPromptSubmit: %d chars", len(prompt))
    return {}  # Non-blocking


async def on_stop(
    input_data: dict[str, Any],
    _tool_use_id: str | None,  # Not used for this hook
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Emit execution_stopped event when execution stops. Non-blocking.

    Args:
        input_data: Contains reason for stop
        _tool_use_id: Not used for this hook
        _context: Hook context (unused)

    Returns:
        Empty dict (non-blocking)
    """
    reason = input_data.get("reason", "unknown")

    emit_execution_stopped(reason)

    logger.debug("Stop: reason=%s", reason)
    return {}  # Non-blocking


async def on_subagent_stop(
    input_data: dict[str, Any],
    _tool_use_id: str | None,  # Not used for this hook
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Emit subagent_stopped event when a subagent stops. Non-blocking.

    Args:
        input_data: Contains subagent info
        _tool_use_id: Not used for this hook
        _context: Hook context (unused)

    Returns:
        Empty dict (non-blocking)
    """
    subagent = input_data.get("subagent", "unknown")

    emit_subagent_stopped(subagent)

    logger.debug("SubagentStop: subagent=%s", subagent)
    return {}  # Non-blocking


async def on_pre_compact(
    input_data: dict[str, Any],
    _tool_use_id: str | None,  # Not used for this hook
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Emit context_compacting event before message compaction. Non-blocking.

    Args:
        input_data: Contains message_count or similar compaction info
        _tool_use_id: Not used for this hook
        _context: Hook context (unused)

    Returns:
        Empty dict (non-blocking)
    """
    message_count = input_data.get("message_count", 0)

    emit_context_compacting(message_count)

    logger.debug("PreCompact: message_count=%d", message_count)
    return {}  # Non-blocking


# =============================================================================
# SAFETY HOOKS (Blocking)
# =============================================================================


def _is_dangerous_command(command: str) -> tuple[bool, str]:
    """Check if a bash command matches dangerous patterns.

    Args:
        command: The bash command to check

    Returns:
        Tuple of (is_dangerous, matched_pattern)
    """
    command_lower = command.lower()
    for pattern in DANGEROUS_BASH_PATTERNS:
        if pattern.lower() in command_lower:
            return True, pattern
    return False, ""


async def validate_tool_use(
    input_data: dict[str, Any],
    _tool_use_id: str | None,  # Not used for validation
    _context: Any,  # HookContext - required by SDK signature
) -> dict[str, Any]:
    """Safety validation for tool calls. BLOCKING - can deny dangerous operations.

    This hook runs BEFORE observability hooks to prevent dangerous
    operations from being executed.

    Args:
        input_data: Contains tool_name, tool_input
        _tool_use_id: Not used for validation
        _context: Hook context (unused)

    Returns:
        Empty dict to allow, or deny decision dict to block
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Validate Bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        is_dangerous, pattern = _is_dangerous_command(command)

        if is_dangerous:
            logger.warning(
                "BLOCKED dangerous Bash command: %s (pattern: %s)",
                command[:100],
                pattern,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Dangerous command blocked (matched: {pattern})",
                }
            }

    # Validate Write operations to sensitive paths
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        sensitive_paths = ["/etc/", "/usr/", "/bin/", "/sbin/", "/boot/"]
        for sensitive in sensitive_paths:
            if file_path.startswith(sensitive):
                logger.warning("BLOCKED write to sensitive path: %s", file_path)
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"Write to sensitive path blocked: {sensitive}",
                    }
                }

    return {}  # Allow


# =============================================================================
# HOOK CONFIGURATION BUILDER
# =============================================================================


def create_hooks_config(
    enable_observability: bool = True,
    enable_safety: bool = True,
) -> dict[str, list[Any]]:
    """Create complete hooks configuration for ClaudeAgentOptions.

    This function builds the hooks dict that can be passed directly
    to ClaudeAgentOptions(hooks=...).

    Args:
        enable_observability: Whether to enable observability hooks (emit events)
        enable_safety: Whether to enable safety hooks (block dangerous operations)

    Returns:
        Dict mapping hook event names to lists of HookMatcher objects

    Example:
        from aef_agent_runner.hooks import create_hooks_config

        options = ClaudeAgentOptions(
            hooks=create_hooks_config(),
            # ... other options
        )
    """
    # Import HookMatcher here to avoid import errors if SDK not installed
    try:
        from claude_agent_sdk import HookMatcher
    except ImportError:
        logger.warning("claude_agent_sdk not available, returning empty hooks config")
        return {}

    hooks: dict[str, list[Any]] = {}

    # PreToolUse hooks (safety FIRST, then observability)
    # Note: type: ignore needed because SDK expects specific typed inputs,
    # but we use generic dict[str, Any] for flexibility across hook types.
    # Runtime behavior is correct.
    pre_tool_hooks: list[Any] = []
    if enable_safety:
        pre_tool_hooks.append(HookMatcher(hooks=[validate_tool_use]))  # type: ignore[list-item]
    if enable_observability:
        pre_tool_hooks.append(HookMatcher(hooks=[on_pre_tool_use]))  # type: ignore[list-item]
    if pre_tool_hooks:
        hooks["PreToolUse"] = pre_tool_hooks

    # PostToolUse hooks (observability only)
    if enable_observability:
        hooks["PostToolUse"] = [HookMatcher(hooks=[on_post_tool_use])]  # type: ignore[list-item]

    # UserPromptSubmit hooks (observability only)
    if enable_observability:
        hooks["UserPromptSubmit"] = [HookMatcher(hooks=[on_user_prompt_submit])]  # type: ignore[list-item]

    # Stop hooks (observability only)
    if enable_observability:
        hooks["Stop"] = [HookMatcher(hooks=[on_stop])]  # type: ignore[list-item]

    # SubagentStop hooks (observability only)
    if enable_observability:
        hooks["SubagentStop"] = [HookMatcher(hooks=[on_subagent_stop])]  # type: ignore[list-item]

    # PreCompact hooks (observability only)
    if enable_observability:
        hooks["PreCompact"] = [HookMatcher(hooks=[on_pre_compact])]  # type: ignore[list-item]

    logger.debug(
        "Created hooks config: observability=%s, safety=%s, hooks=%s",
        enable_observability,
        enable_safety,
        list(hooks.keys()),
    )

    return hooks
