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


def _first_spelling(*candidates: object) -> str | None:
    """The first candidate that is a non-empty string, or None if none is.

    A legacy payload spells the same fact several ways and the reader takes
    whichever one arrived. Saying that once, as a call, keeps the choice in a
    single place instead of an ``or`` chain per field - and an ``or`` chain is
    a branch per spelling to everyone who later reads the function.
    """
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _branch_from_checkout(command: object) -> str | None:
    """The branch named by a legacy ``git_operation``'s command line, if any."""
    if not isinstance(command, str):
        return None
    match = _re.search(r"git\s+checkout\s+(?:-b\s+)?(\S+)", command)
    return match.group(1) if match else None


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
        """Read the git facts out of an observation payload, in either shape."""
        git = data.get("git")
        if isinstance(git, dict):
            return cls._from_v2(git)
        return cls._from_legacy(data, event_type)

    @classmethod
    def _from_v2(cls, git: dict[str, Any]) -> GitFacts:
        """Read the facts a v2 event nests under ``git``."""
        return cls(
            sha=_first_spelling(git.get("sha")),
            message=_first_spelling(git.get("message")),
            branch=_first_spelling(git.get("branch"), git.get("to_branch")),
            repo=_first_spelling(git.get("repo")),
            structured=git,
        )

    @classmethod
    def _from_legacy(cls, data: dict[str, Any], event_type: str) -> GitFacts:
        """Read the facts a legacy event spreads over the top level and ``context``."""
        ctx = data.get("context")
        ctx = ctx if isinstance(ctx, dict) else {}

        branch = _first_spelling(data.get("branch"), ctx.get("branch"), data.get("to_branch"))
        if branch is None and event_type == "git_operation":
            branch = _branch_from_checkout(data.get("command"))

        return cls(
            sha=_first_spelling(
                data.get("sha"),
                ctx.get("sha"),
                data.get("commit_hash"),
                data.get("merge_sha"),
            ),
            # The engine renames "message" to "commit_message" during ingestion
            # to avoid a RESERVED_OBSERVATION_KEYS collision, so both spellings
            # reach this point and both are read.
            message=_first_spelling(
                data.get("commit_message"),
                ctx.get("message"),
                data.get("message"),
                data.get("message_preview"),
            ),
            branch=branch,
            repo=_first_spelling(data.get("repo"), ctx.get("repo")),
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
