"""Best-effort RECOGNITION of a delegated CLI invocation in a shell command.

A delegation-enabled phase (``agent.allow_delegation: true``) declares that its
primary agent will hand part of the work to the OTHER harness: a claude phase
shells out to ``codex exec``, a codex phase shells out to ``claude -p``. That
declaration is provisioned for (both auths staged, the matching delegation
skill installed) but nothing observes whether it HAPPENED.

What this module gives you is TELEMETRY: a count of how many commands looked
like a delegated invocation, and how many of those exited zero. It is useful
for dashboards, for spotting phases whose delegation never fires, and as raw
material for the real fix.

DO NOT GATE PHASE SUCCESS ON THESE COUNTS
-----------------------------------------

An earlier revision of this module did exactly that (a phase whose declared
delegation recorded zero successes was failed) and it was removed in review,
because pattern-matching shell text is not a sound basis for a verdict. Three
concrete defeats, all verified:

1. **False positives - the gate is satisfied without any delegate running.**
   ``echo "run codex exec later"``, ``grep -F "codex exec" notes.md``, and a
   heredoc writing a script that merely CONTAINS the delegate invocation all
   match, and all exit zero. A phase could satisfy the gate having delegated
   nothing.

2. **Wrong exit status - a failed delegate reads as a success.** The exit code
   observed belongs to the ENCLOSING shell, not to the delegate.
   ``codex exec "review" || true`` and ``claude -p "review" | tee log`` both
   report zero however the delegate itself fared.

3. **False negatives - a good run looks like a bad one.** A legitimate
   delegation through a wrapper script, a line-continuation
   (``claude \\`` newline ``-p ...``), or an unanticipated flag position
   (``codex --config "..." exec``) is invisible to any regex written against
   today's spellings. This is the dangerous direction: it FAILS working runs.

A gate that an ``echo`` satisfies and a ``|| true`` defeats manufactures false
confidence, which is the exact defect class the delegation work set out to
remove. A sound gate needs the delegate to report itself - a platform-owned
shim on PATH that emits a structured start/end record and propagates the
DELEGATE's own exit status, so delegation is a first-class platform operation
rather than something inferred from shell text. See the follow-up issue linked
from #894 / #895; wire nothing to a gate before that exists.
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
skill we install and the invocation we then count stay in step.
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


def looks_like_delegation_command(command: str, target: DelegationTarget) -> bool:
    """Return True when ``command`` LOOKS LIKE an invocation of ``target``'s CLI.

    Observational only - see the module docstring for why this must not decide
    whether a phase succeeded. "Looks like" is load-bearing in the name: the
    answer is a textual resemblance, not a fact about what ran.

    Examples:
        >>> looks_like_delegation_command("codex exec 'go'", DelegationTarget.CODEX)
        True
        >>> looks_like_delegation_command("grep -r codex .", DelegationTarget.CODEX)
        False
    """
    if not command:
        return False
    return _MATCHERS[target].search(command) is not None
