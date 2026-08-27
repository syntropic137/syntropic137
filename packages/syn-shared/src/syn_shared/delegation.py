"""Recognising a DELEGATED CLI invocation inside a primary agent's tool call.

A delegation-enabled phase (``agent.allow_delegation: true``) declares that its
primary agent will hand part of the work to the OTHER harness: a claude phase
shells out to ``codex exec``, a codex phase shells out to ``claude -p``. That
declaration is provisioned for (both auths staged, the matching delegation
skill installed) but nothing ever checked that it HAPPENED.

It has to be checked from the stream rather than from the agent's own report.
The agent's ``TASK_RESULT`` block is self-reported: in the run that motivated
this module (issue #894) the delegated ``codex exec`` died on bubblewrap, the
primary agent noted that in prose, and still reported ``success: true``. The
tool call itself is not self-reported - the primary agent cannot run a command
without the harness emitting it - so the command text is the honest signal.

Matching is deliberately narrow. It looks for the delegate CLI's OWN
invocation shape (``codex exec`` / ``claude -p``), not merely the word
"codex" or "claude" appearing somewhere in a command, so that a ``grep codex
notes.md`` or a path containing "claude" is not mistaken for a handoff.
"""

from __future__ import annotations

import re
from enum import StrEnum

from syn_shared.agents import AgentProvider


class DelegationTarget(StrEnum):
    """The CLI a delegating phase is expected to invoke."""

    CLAUDE = "claude"
    """The delegate is headless ``claude -p`` (invoked BY a codex phase)."""

    CODEX = "codex"
    """The delegate is headless ``codex exec`` (invoked BY a claude phase)."""


DELEGATION_TARGET_BY_PRIMARY: dict[AgentProvider, DelegationTarget] = {
    AgentProvider.CLAUDE: DelegationTarget.CODEX,
    AgentProvider.CODEX: DelegationTarget.CLAUDE,
}
"""Which CLI each primary provider delegates TO.

Mirrors ``_DELEGATION_TARGET_SKILL`` in ``WorkspaceProvisionHandler``: the
skill we install teaches the primary agent to call exactly this CLI, so the
skill we install and the invocation we then assert on stay in step.
"""

# A command boundary: start of string, whitespace, or a shell operator/quote.
# Delegated commands routinely arrive wrapped, e.g. ``bash -lc 'codex exec ...'``.
_BOUNDARY = r"(?:^|[\s;&|(`'\"])"
# An optional absolute or relative path prefix on the executable.
_PATH_PREFIX = r"(?:[\w./-]*/)?"

_CODEX_EXEC_RE = re.compile(
    # ``codex`` followed by ``exec``, tolerating global flags in between
    # (``codex --cd /w exec ...``).
    _BOUNDARY + _PATH_PREFIX + r"codex(?:\s+-{1,2}[\w-]+(?:[= ][^\s]+)?)*\s+exec\b"
)

_CLAUDE_PRINT_RE = re.compile(
    # ``claude`` followed, before any command separator, by -p / --print.
    _BOUNDARY + _PATH_PREFIX + r"claude\b[^;&|\n]*?\s-{1,2}(?:p|print)\b"
)

_MATCHERS: dict[DelegationTarget, re.Pattern[str]] = {
    DelegationTarget.CODEX: _CODEX_EXEC_RE,
    DelegationTarget.CLAUDE: _CLAUDE_PRINT_RE,
}


def is_delegation_command(command: str, target: DelegationTarget) -> bool:
    """Return True when ``command`` invokes ``target``'s headless CLI.

    Examples:
        >>> is_delegation_command("codex exec --json 'do it'", DelegationTarget.CODEX)
        True
        >>> is_delegation_command("grep -r codex .", DelegationTarget.CODEX)
        False
        >>> is_delegation_command("claude -p 'review this'", DelegationTarget.CLAUDE)
        True
    """
    if not command:
        return False
    return _MATCHERS[target].search(command) is not None
