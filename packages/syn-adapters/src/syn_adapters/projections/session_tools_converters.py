"""Row conversion helpers for session tools projection.

Extracted from session_tools.py to reduce module complexity.
"""

from __future__ import annotations

import json
import re as _re
from typing import TYPE_CHECKING, Any

from syn_shared.events import (
    GIT_REWRITE,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from syn_adapters.projections.session_tools import ToolOperation


def extract_agent_label(data: dict[str, Any]) -> str:
    """Extract a display name for a subagent from tool input data."""
    tool_input = data.get("input_preview") or data.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = None
    if isinstance(tool_input, dict):
        return str(
            tool_input.get("description")
            or tool_input.get("subagent_type")
            or data.get("tool_name", "")
        )
    return str(data.get("tool_name", ""))


def row_to_subagent_operation(row: Any, data: dict[str, Any], event_type: str) -> ToolOperation:
    """Convert a tool event row for an Agent/Task tool into a subagent operation."""
    from syn_adapters.projections.session_tools import ToolOperation

    tool_use_id = data.get("tool_use_id", "")
    is_started = event_type == TOOL_EXECUTION_STARTED
    subagent_op = SUBAGENT_STARTED if is_started else SUBAGENT_STOPPED
    agent_label = extract_agent_label(data)
    obs_id = f"subagent-{subagent_op}-{tool_use_id}-{row['time'].isoformat()}"
    return ToolOperation(
        observation_id=obs_id,
        tool_name=agent_label,
        tool_use_id=tool_use_id or None,
        operation_type=subagent_op,
        timestamp=row["time"],
        success=data.get("success") if not is_started else None,
        input_preview=data.get("input_preview") or json.dumps(data),
        output_preview=data.get("output_preview") if not is_started else None,
        duration_ms=data.get("duration_ms") if not is_started else None,
    )


def row_to_git_operation(row: Any, data: dict[str, Any], event_type: str) -> ToolOperation:
    """Convert a git event row into a ToolOperation."""
    from syn_adapters.projections.session_tools import ToolOperation

    obs_id = f"git-{event_type}-{row['time'].isoformat()}"
    git_subcmd = data.get("operation", "")
    git_branch = data.get("branch") or data.get("to_branch") or None

    if not git_branch and event_type == "git_operation":
        cmd = data.get("command", "")
        _m = _re.search(r"git\s+checkout\s+(?:-b\s+)?(\S+)", cmd)
        if _m:
            git_branch = _m.group(1)

    if event_type == GIT_REWRITE and not git_subcmd:
        git_subcmd = data.get("operation", "rebase")

    return ToolOperation(
        observation_id=obs_id,
        tool_name=git_subcmd,
        tool_use_id=None,
        operation_type=event_type,
        timestamp=row["time"],
        success=True,
        input_preview=None,
        output_preview=None,
        duration_ms=None,
        git_sha=data.get("sha") or data.get("commit_hash") or data.get("merge_sha") or None,
        git_message=data.get("message")
        or data.get("message_preview")
        or data.get("commit_message")
        or None,
        git_branch=git_branch,
        git_repo=data.get("repo") or None,
    )
