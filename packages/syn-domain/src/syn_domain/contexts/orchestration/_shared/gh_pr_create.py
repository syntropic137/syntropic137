"""Did this command create pull requests, and which? Parsed once, strictly.

A PR counts as created by a run only when all of these hold:

1. **``gh pr create`` is what ran, last.** The script (unwrapped from
   ``bash -lc '...'``) is tokenised like a shell does, split on operators
   outside quotes (``&&``, ``||``, ``;``, ``|``, ``&``, newlines, parens). The
   LAST simple command must be ``gh pr create`` (after ``VAR=value``/``env``
   prefixes), so the tool's exit status IS that invocation's: ``gh pr create
   || echo URL`` and ``false && gh pr create; echo URL`` end in ``echo`` and
   create nothing. ``echo 'gh pr create'`` has argv ``echo ...``. A trailing
   ``&`` (backgrounded) is rejected. Several creates count only as a trailing
   chain joined by ``&&``, where exit 0 proves every one of them succeeded.
2. **None is a dry run**: ``--dry-run`` in a create's argv rejects it.
3. **It succeeded**: the harness reported success (exit code 0).
4. **The URLs are what gh printed last**: each ``gh pr create`` prints its
   PR's URL as its final line, so the last non-empty line of the FULL output
   must be exactly ``https://github.com/<owner>/<repo>/pull/<n>``, and a chain
   of k creates takes the last k such lines. A URL from a body, a warning or an
   earlier command is never the created PR.

Anything that fails a check creates nothing; nothing is guessed. Known limit:
a create inside ``if``/``for`` is not last (``fi``/``done`` is) and is not
counted: an undercount, never an invention.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

_SEPARATORS = "();&|\n"
_AND = "&&"
_BACKGROUND = "&"
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


def _trailing_creates(command: str) -> int:
    """How many ``gh pr create`` end the script, chained by ``&&``; 0 if not last."""
    commands = _commands(_unwrap_shell(command))
    if not commands or not commands[-1].creates or commands[-1].then == _BACKGROUND:
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
    if count == 0 or not lines or _PR_URL.match(lines[-1]) is None:
        return []
    urls = [line for line in lines if _PR_URL.match(line)][-count:]
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
