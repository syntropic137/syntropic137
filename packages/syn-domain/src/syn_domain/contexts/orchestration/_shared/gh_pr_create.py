"""Did this command create pull requests, and which? Parsed once, strictly.

A PR counts as created by a run only when all of these hold:

1. **``gh pr create`` is what ran, last, unconditionally.** The script
   (unwrapped from ``bash -lc '...'``) is tokenised like a shell does, split
   on operators outside quotes. The LAST simple command must be ``gh pr
   create`` (after ``VAR=value``/``env`` prefixes), nothing may follow it (not
   even ``;``), and every operator in the call must be ``&&``, ``;`` or a
   newline: no ``||`` anywhere, no pipe, no ``&``, no subshell. Then exit 0
   is the create's own success. ``echo 'gh pr create'`` has argv ``echo ...``.
   Several creates count only as a trailing chain joined by ``&&``.
2. **None is a dry run**: ``--dry-run`` in a create's argv rejects it.
3. **It succeeded**: the harness reported success (exit code 0).
4. **The URLs are what gh printed last**: each ``gh pr create`` prints its
   PR's URL as its final line, so a chain of N creates must end the FULL
   output with exactly N lines that are each exactly
   ``https://github.com/<owner>/<repo>/pull/<n>``, matched in order. One more
   URL line before them (an earlier command's) refuses the whole call.

Anything that fails a check creates nothing; nothing is guessed. Known false
negatives, accepted: ``cmd || true && gh pr create``, a piped body
(``printf x | gh pr create -F -``), a create in ``if``/``for`` or a subshell,
and gh warnings interleaved between the URLs of a chain. Each is an
undercount, never an invented PR.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

_SEPARATORS = "();&|\n"
_AND = "&&"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PR_URL = re.compile(
    r"^https://github\.com/(?P<repo>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)/pull/(?P<number>[0-9]+)/?$"
)
_DRY_RUN = "--dry-run"
_WRAPPERS = frozenset({"env", "command", "exec"})


@dataclass(frozen=True)
class CreatedPullRequest:
    repository: str
    number: int
    url: str


@dataclass(frozen=True)
class _Command:
    argv: list[str]
    then: str | None
    """The operator after this command, or None at the end of the script."""

    @property
    def creates(self) -> bool:
        return self.argv[:3] == ["gh", "pr", "create"] and _DRY_RUN not in self.argv


def _tokens(script: str) -> list[str] | None:
    """Shell tokens with operators as their own tokens; None if unparseable."""
    lexer = shlex.shlex(script, posix=True, punctuation_chars=_SEPARATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        return list(lexer)
    except ValueError:
        return None


def _is_operator(token: str) -> bool:
    return bool(token) and all(ch in _SEPARATORS for ch in token)


def _commands(script: str) -> list[_Command]:
    """Each simple command and the operator after it, split outside quotes.

    Quoted text stays one token, so ``echo 'gh pr create'`` is the argv
    ``["echo", "gh pr create"]``. A script the shell could not parse either
    (an unclosed quote) yields nothing. An operator after a closing paren or a
    newline replaces it (``(x) &`` is backgrounded).
    """
    commands: list[_Command] = []
    argv: list[str] = []
    for token in _tokens(script) or []:
        if not _is_operator(token):
            argv.append(token)
        elif argv:
            commands.append(_Command(_without_prefixes(argv), token))
            argv = []
        elif commands and token.strip() and commands[-1].then in (None, "\n", ")"):
            commands[-1] = _Command(commands[-1].argv, token)
    if argv:
        commands.append(_Command(_without_prefixes(argv), None))
    return [c for c in commands if c.argv]


def _without_prefixes(argv: list[str]) -> list[str]:
    """``argv`` without leading ``VAR=value`` assignments and ``env``/``exec``."""
    while argv and (_ASSIGNMENT.match(argv[0]) or argv[0] in _WRAPPERS):
        argv = argv[1:]
    return argv


def _unwrap_shell(command: str) -> str:
    """The script of ``bash -lc '<script>'`` (how codex reports commands), else as is."""
    commands = _commands(command)
    if len(commands) == 1:
        argv = commands[0].argv
        shell = argv[0].rsplit("/", 1)[-1] if argv else ""
        if len(argv) == 3 and shell in {"bash", "sh", "zsh"} and argv[1] in {"-c", "-lc"}:
            return argv[2]
    return command


def is_gh_pr_create(command: str) -> bool:
    """Whether ``command`` runs ``gh pr create`` anywhere (not as text, not dry)."""
    return any(c.creates for c in _commands(_unwrap_shell(command)))


_SEQUENCE = frozenset({_AND, ";", "\n"})
"""The only operators a counted call may contain: each runs the next only in order."""


def _trailing_creates(command: str) -> int:
    """How many ``gh pr create`` end the call, chained by ``&&``; 0 unless the call is strict.

    Strict means every operator in the whole call is ``&&``, ``;`` or a
    newline, and nothing (not even ``;``) follows the last command. So no
    ``||`` anywhere (a create after one may not have run, one before it is not
    last), no pipe, no background, no subshell. The cost is known false
    negatives such as ``cmd || true && gh pr create``: an undercount, never an
    invented PR.
    """
    commands = _commands(_unwrap_shell(command.strip()))
    if not commands or not commands[-1].creates or commands[-1].then is not None:
        return 0
    if any(c.then not in _SEQUENCE for c in commands[:-1]):
        return 0
    count = 1
    for previous in reversed(commands[:-1]):
        if not (previous.creates and previous.then == _AND):
            break
        count += 1
    return count


def created_pull_requests(command: str, success: bool, output: str) -> list[CreatedPullRequest]:
    """Every PR ``command`` created, oldest first; empty unless every check holds."""
    count = _trailing_creates(command) if success else 0
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    trailing = 0
    for line in reversed(lines):
        if _PR_URL.match(line) is None:
            break
        trailing += 1
    # Exactly one URL line per create, at the very end, in order: a URL any
    # earlier command printed would make the run longer and is refused.
    if count == 0 or trailing != count:
        return []
    urls = lines[-count:]
    created: list[CreatedPullRequest] = []
    for url in urls:
        match = _PR_URL.match(url)
        if match is not None:
            created.append(
                CreatedPullRequest(
                    repository=match.group("repo"),
                    number=int(match.group("number")),
                    url=url.rstrip("/"),
                )
            )
    return created
