"""Did this command create a pull request, and which one? Parsed once, strictly.

A PR counts as created by a run only when all of these hold:

1. **The command runs ``gh pr create``** as a command, not as text: the
   script (unwrapped from ``bash -lc '...'``) is tokenised like a shell does,
   split on operators outside quotes (``&&``, ``||``, ``;``, ``|``, newlines),
   and one command's argv, after ``VAR=value``/``env`` prefixes, must begin
   ``gh pr create``. ``echo 'gh pr create'`` has argv ``echo ...`` and is not
   one. Known limit: a heredoc body line reading ``gh pr create`` is read as a
   command; its output would still have to end in a PR URL to count.
2. **It is not a dry run**: ``--dry-run`` anywhere in that argv rejects it.
3. **It succeeded**: the harness reported success (exit code 0).
4. **The URL is what gh printed last**: ``gh pr create`` prints the new PR's
   URL as its final line, so the last non-empty line of the FULL output must
   be exactly ``https://github.com/<owner>/<repo>/pull/<n>``. A URL anywhere
   else (a body, a warning, an earlier PR) is not the created PR.

Anything that fails a check is not a created PR; nothing is guessed.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

_SEPARATORS = "();&|\n"
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


def _commands(script: str) -> list[list[str]]:
    """Each simple command's argv, split on shell operators outside quotes.

    Quoted text stays one token, so ``echo 'gh pr create'`` is the argv
    ``["echo", "gh pr create"]``. A script the shell could not parse either
    (an unclosed quote) yields nothing.
    """
    lexer = shlex.shlex(script, posix=True, punctuation_chars=_SEPARATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = "#"
    commands: list[list[str]] = [[]]
    try:
        for token in lexer:
            if token and all(ch in _SEPARATORS for ch in token):
                commands.append([])
            else:
                commands[-1].append(token)
    except ValueError:
        return []
    return [_without_prefixes(argv) for argv in commands if argv]


def _without_prefixes(argv: list[str]) -> list[str]:
    """``argv`` without leading ``VAR=value`` assignments and ``env``/``exec``."""
    while argv and (_ASSIGNMENT.match(argv[0]) or argv[0] in _WRAPPERS):
        argv = argv[1:]
    return argv


def _unwrap_shell(command: str) -> str:
    """The script of ``bash -lc '<script>'`` (how codex reports commands), else as is."""
    commands = _commands(command)
    if len(commands) == 1:
        argv = commands[0]
        shell = argv[0].rsplit("/", 1)[-1] if argv else ""
        if len(argv) == 3 and shell in {"bash", "sh", "zsh"} and argv[1] in {"-c", "-lc"}:
            return argv[2]
    return command


def is_gh_pr_create(command: str) -> bool:
    """Whether ``command`` runs ``gh pr create`` (not as quoted text, not dry)."""
    return any(
        argv[:3] == ["gh", "pr", "create"] and _DRY_RUN not in argv
        for argv in _commands(_unwrap_shell(command))
    )


def created_pull_request(command: str, success: bool, output: str) -> CreatedPullRequest | None:
    """The PR ``command`` created, or None unless every check above holds."""
    if not success or not is_gh_pr_create(command):
        return None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    match = _PR_URL.match(lines[-1])
    if match is None:
        return None
    url = lines[-1].rstrip("/")
    return CreatedPullRequest(
        repository=match.group("repo"), number=int(match.group("number")), url=url
    )
