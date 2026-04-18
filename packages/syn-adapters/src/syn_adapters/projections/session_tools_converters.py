"""Row conversion helpers for session tools projection.

Extracted from session_tools.py to reduce module complexity.
row_to_operation and query_session_tools moved to session_tools_queries.py.
"""

from __future__ import annotations

import json
import logging
import re as _re
from typing import TYPE_CHECKING, Any

from syn_shared.events import (
    GIT_REWRITE,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.projections.session_tools import ToolOperation

_logger = logging.getLogger(__name__)


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


def row_to_subagent_operation(
    row: asyncpg.Record, data: dict[str, Any], event_type: str
) -> ToolOperation:
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


def _git_sub(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the structured ``git`` sub-object if present (v2 events)."""
    git = data.get("git")
    return git if isinstance(git, dict) else None


def _resolve_git_branch(data: dict[str, Any], event_type: str) -> str | None:
    """Extract the git branch from event data."""
    # v2 structured path
    git = _git_sub(data)
    if git is not None:
        return git.get("branch") or git.get("to_branch") or None

    # Legacy flat fallback
    ctx = _ctx(data)
    branch = data.get("branch") or ctx.get("branch") or data.get("to_branch") or None
    if branch or event_type != "git_operation":
        return branch
    cmd = data.get("command", "")
    _m = _re.search(r"git\s+checkout\s+(?:-b\s+)?(\S+)", cmd)
    return _m.group(1) if _m else None


def _ctx(data: dict[str, Any]) -> dict[str, Any]:
    """Return the context sub-dict if present (legacy flat events)."""
    ctx = data.get("context")
    return ctx if isinstance(ctx, dict) else {}


def _resolve_git_sha(data: dict[str, Any]) -> str | None:
    """Extract git SHA from event data."""
    # v2 structured path
    git = _git_sub(data)
    if git is not None:
        return git.get("sha") or None

    # Legacy flat fallback
    ctx = _ctx(data)
    return (
        data.get("sha")
        or ctx.get("sha")
        or data.get("commit_hash")
        or data.get("merge_sha")
        or None
    )


def _resolve_git_message(data: dict[str, Any]) -> str | None:
    """Extract git commit message from event data."""
    # v2 structured path
    git = _git_sub(data)
    if git is not None:
        return git.get("message") or None

    # Legacy flat fallback - engine renames "message" to "commit_message"
    # during ingestion to avoid RESERVED_OBSERVATION_KEYS collision.
    ctx = _ctx(data)
    return (
        data.get("commit_message")
        or ctx.get("message")
        or data.get("message")
        or data.get("message_preview")
        or None
    )


def _resolve_git_repo(data: dict[str, Any]) -> str | None:
    """Extract git repo from event data."""
    # v2 structured path
    git = _git_sub(data)
    if git is not None:
        return git.get("repo") or None

    # Legacy flat fallback
    return data.get("repo") or _ctx(data).get("repo") or None


def row_to_git_operation(
    row: asyncpg.Record, data: dict[str, Any], event_type: str
) -> ToolOperation:
    """Convert a git event row into a ToolOperation."""
    from syn_adapters.projections.session_tools import ToolOperation

    # Extract git subcommand (operation name)
    git = _git_sub(data)
    git_subcmd = git.get("operation", "") if git is not None else data.get("operation", "")
    if event_type == GIT_REWRITE and not git_subcmd:
        git_subcmd = "rebase"

    return ToolOperation(
        observation_id=f"git-{event_type}-{row['time'].isoformat()}",
        tool_name=git_subcmd,
        tool_use_id=None,
        operation_type=event_type,
        timestamp=row["time"],
        success=True,
        input_preview=None,
        output_preview=None,
        duration_ms=None,
        git_sha=_resolve_git_sha(data),
        git_message=_resolve_git_message(data),
        git_branch=_resolve_git_branch(data, event_type),
        git_repo=_resolve_git_repo(data),
        git_data=git,
    )
