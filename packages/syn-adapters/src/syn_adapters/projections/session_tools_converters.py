"""Row conversion helpers for session tools projection.

Extracted from session_tools.py to reduce module complexity.
row_to_operation and query_session_tools moved to session_tools_queries.py.
"""

from __future__ import annotations

import json
import logging
import re as _re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from syn_adapters.projections.session_tools_verdict import observation_id, read_verdict
from syn_shared.events import (
    GIT_REWRITE,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from datetime import datetime

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


def to_subagent_operation(when: datetime, data: dict[str, Any], event_type: str) -> ToolOperation:
    """Convert an Agent/Task tool observation into a subagent operation."""
    from syn_adapters.projections.session_tools import ToolOperation

    tool_use_id = data.get("tool_use_id", "")
    is_started = event_type == TOOL_EXECUTION_STARTED
    subagent_op = SUBAGENT_STARTED if is_started else SUBAGENT_STOPPED
    agent_label = extract_agent_label(data)
    # The verdict is read against `subagent_op`, not `event_type`: this row has
    # already been relabelled from a tool event to a subagent one, and the
    # relabelled type is what every reader downstream sees.
    verdict = read_verdict(subagent_op, data)
    return ToolOperation(
        observation_id=observation_id("subagent", subagent_op, tool_use_id, when.isoformat()),
        tool_name=agent_label,
        tool_use_id=tool_use_id or None,
        operation_type=subagent_op,
        timestamp=when,
        success=verdict.success,
        error_message=verdict.error_message,
        input_preview=data.get("input_preview") or json.dumps(data),
        output_preview=data.get("output_preview") if not is_started else None,
        duration_ms=data.get("duration_ms") if not is_started else None,
    )


@dataclass(frozen=True)
class GitFacts:
    """The git facts one timeline observation carries, in either payload shape.

    v2 events nest them under ``git``; legacy events spread them across the top
    level and a ``context`` sub-object, under several spellings each. Both
    shapes answer the same four questions, so they are read once, here, rather
    than re-derived per field with the shape test repeated four times.
    """

    sha: str | None
    message: str | None
    branch: str | None
    repo: str | None
    structured: dict[str, Any] | None
    """The v2 ``git`` sub-object verbatim, or None for a legacy payload.

    Passed through to the read model untouched: the dashboard renders fields
    this class has no opinion about, and inventing one for a legacy payload
    would report a shape that was never recorded.
    """

    @classmethod
    def read(cls, data: dict[str, Any], event_type: str) -> GitFacts:
        """Read the git facts out of an observation payload."""
        git = data.get("git")
        if isinstance(git, dict):
            return cls(
                sha=git.get("sha") or None,
                message=git.get("message") or None,
                branch=git.get("branch") or git.get("to_branch") or None,
                repo=git.get("repo") or None,
                structured=git,
            )

        ctx = data.get("context")
        ctx = ctx if isinstance(ctx, dict) else {}
        branch = data.get("branch") or ctx.get("branch") or data.get("to_branch") or None
        if not branch and event_type == "git_operation":
            _m = _re.search(r"git\s+checkout\s+(?:-b\s+)?(\S+)", data.get("command", ""))
            branch = _m.group(1) if _m else None

        return cls(
            sha=(
                data.get("sha")
                or ctx.get("sha")
                or data.get("commit_hash")
                or data.get("merge_sha")
                or None
            ),
            # The engine renames "message" to "commit_message" during ingestion
            # to avoid a RESERVED_OBSERVATION_KEYS collision, so both spellings
            # reach this point and both are read.
            message=(
                data.get("commit_message")
                or ctx.get("message")
                or data.get("message")
                or data.get("message_preview")
                or None
            ),
            branch=branch,
            repo=data.get("repo") or ctx.get("repo") or None,
            structured=None,
        )


def to_git_operation(when: datetime, data: dict[str, Any], event_type: str) -> ToolOperation:
    """Convert a git observation into a ToolOperation."""
    from syn_adapters.projections.session_tools import ToolOperation

    # Extract git subcommand (operation name)
    facts = GitFacts.read(data, event_type)
    git = facts.structured
    git_subcmd = git.get("operation", "") if git is not None else data.get("operation", "")
    if event_type == GIT_REWRITE and not git_subcmd:
        git_subcmd = "rebase"

    # `unrecorded=True`: a git row exists because the commit, push or merge
    # happened, so the observation type settles the question that no payload
    # key answers. Every other converter leaves it None - "the row did not say,
    # so nobody knows" - rather than defaulting a silence to success.
    verdict = read_verdict(event_type, data, unrecorded=True)

    return ToolOperation(
        observation_id=observation_id("git", event_type, when.isoformat()),
        tool_name=git_subcmd,
        tool_use_id=None,
        operation_type=event_type,
        timestamp=when,
        success=verdict.success,
        error_message=verdict.error_message,
        input_preview=None,
        output_preview=None,
        duration_ms=None,
        git_sha=facts.sha,
        git_message=facts.message,
        git_branch=facts.branch,
        git_repo=facts.repo,
        git_data=facts.structured,
    )
