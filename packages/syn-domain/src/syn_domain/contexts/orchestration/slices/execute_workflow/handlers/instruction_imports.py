"""Choose which of a cloned repo's instruction files to @-import (ADR-058).

Every byte the synthetic /workspace/CLAUDE.md imports is resent on every turn
of every phase, so a repo whose AGENTS.md duplicates its CLAUDE.md must not be
loaded twice. Dropping an import must never remove the agent's access to a
distinct instruction file, so anything uncertain is imported anyway.

A provider that does not expand ``@``-imports (codex, #1835) is handed the same
files' content instead: ``inline_instruction_files`` writes each one, in import
order, under a header naming its path.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

logger = logging.getLogger(__name__)


class _Unread(Enum):
    """Why an instruction file has no content to compare."""

    #: Confirmed not in the checkout: there is nothing to import.
    ABSENT = "absent"
    #: The read failed (transport, timeout, permission): the file may be there,
    #: so its import is kept rather than guessed away.
    UNREADABLE = "unreadable"


#: Exit status of ``_READ_INSTRUCTION_FILE`` when the path does not exist. Any
#: other failure is UNREADABLE, never ABSENT.
_ABSENT_EXIT: Final[int] = 3
_READ_INSTRUCTION_FILE: Final[str] = f'[ -e "$1" ] || exit {_ABSENT_EXIT}; exec cat -- "$1"'

#: The whole of a breadcrumb AGENTS.md: one line that only points at the
#: CLAUDE.md beside it, as an @-import or a Markdown link, optionally led by
#: "See"/"Read"/"Follow". Anything else in the file is an instruction of its own.
#: Only the lead word ignores case: paths are case-sensitive on Linux, so
#: ``claude.md`` is a different file from ``CLAUDE.md`` and must stay reachable.
_BREADCRUMB = re.compile(
    r"(?:(?i:see|read|follow)\s+)?"
    r"(?:@(?:\./)?CLAUDE\.md|\[`?(?:\./)?CLAUDE\.md`?\]\((?:\./)?CLAUDE\.md\))\.?"
)


def _instruction_imports(
    agents_path: str,
    agents_md: str | _Unread,
    claude_path: str,
    claude_md: str | _Unread,
) -> list[str]:
    """Return the repo instruction files worth importing, each distinct one once.

    AGENTS.md is dropped only when it says nothing CLAUDE.md does not: a
    byte-identical copy of a CLAUDE.md that was read, or a breadcrumb pointing at
    a CLAUDE.md that is not confirmed absent. CLAUDE.md is the one kept because
    it is the canonical file (AGENTS.md is the breadcrumb), and because Claude
    Code reads it natively. A file that could not be read is still imported.
    """
    if isinstance(agents_md, str) and claude_md is not _Unread.ABSENT:
        is_copy = agents_md == claude_md
        is_breadcrumb = _BREADCRUMB.fullmatch(agents_md.strip()) is not None
        if is_copy or is_breadcrumb:
            agents_md = _Unread.ABSENT
    return [
        path
        for path, content in ((agents_path, agents_md), (claude_path, claude_md))
        if content is not _Unread.ABSENT
    ]


async def _read_instruction_file(workspace: ManagedWorkspace, path: str) -> str | _Unread:
    """Read one instruction file, telling a confirmed absence from a failed read."""
    result = await workspace.execute(
        ["sh", "-c", _READ_INSTRUCTION_FILE, "sh", path], timeout_seconds=30
    )
    if result.exit_code == 0 and not result.timed_out:
        return result.stdout
    if result.exit_code == _ABSENT_EXIT and not result.timed_out:
        return _Unread.ABSENT
    logger.warning(
        "could not read %s (exit %d), importing it anyway: %s",
        path,
        result.exit_code,
        result.stderr,
    )
    return _Unread.UNREADABLE


async def repo_instruction_imports(workspace: ManagedWorkspace, name: str) -> list[str]:
    """Return the paths of a cloned repo's instruction files to @-import.

    See ``_instruction_imports`` for what is dropped. If the files cannot be
    read, both are imported, as before: a duplicate costs tokens, a missing file
    costs the agent its instructions.
    """
    agents_path = f"/workspace/repos/{name}/AGENTS.md"
    claude_path = f"/workspace/repos/{name}/CLAUDE.md"
    try:
        agents = await _read_instruction_file(workspace, agents_path)
        claude = await _read_instruction_file(workspace, claude_path)
    except Exception as exc:
        logger.warning("could not read instruction files of %s, importing both: %s", name, exc)
        return [agents_path, claude_path]
    return _instruction_imports(agents_path, agents, claude_path, claude)


def _inlined_section(path: str, content: str | _Unread) -> str:
    """One instruction file as it appears inlined: a header naming it, then its content."""
    if isinstance(content, str):
        return f"# Instructions from {path}\n\n{content.rstrip()}\n"
    # Never dropped silently: the agent is told the file exists and where.
    return (
        f"# Instructions from {path}\n\n"
        "This file could not be read when the workspace was prepared. Read it yourself.\n"
    )


def _render_inlined(
    files: Sequence[tuple[str, str | _Unread]], notice: str, max_bytes: int
) -> tuple[str, list[str]]:
    """Return the inlined document and the paths that lie wholly or partly past ``max_bytes``.

    ``notice`` leads, so the one line about the phase deadline is the last
    thing a byte limit could cut.
    """
    text = notice + "\n"
    cut: list[str] = []
    for path, content in files:
        text += "\n" + _inlined_section(path, content)
        if len(text.encode()) > max_bytes:
            cut.append(path)
    return text, cut


async def inline_instruction_files(
    workspace: ManagedWorkspace, paths: Sequence[str], *, notice: str, max_bytes: int
) -> str:
    """Return ``notice`` followed by the content of each file in ``paths``, in order.

    For an agent that reads its instruction file verbatim. A file confirmed
    absent is left out; one that cannot be read is named rather than left out. Content past ``max_bytes``, which the
    reading agent will not see, is logged as a WARNING naming the files it cuts.
    """
    files: list[tuple[str, str | _Unread]] = []
    for path in paths:
        try:
            content = await _read_instruction_file(workspace, path)
        except Exception as exc:
            logger.warning("could not read %s to inline it, naming it instead: %s", path, exc)
            content = _Unread.UNREADABLE
        if content is not _Unread.ABSENT:
            files.append((path, content))
    text, cut = _render_inlined(files, notice, max_bytes)
    if cut:
        logger.warning(
            "inlined instructions are %d bytes, over the %d an agent reads: "
            "it will not see all of %s",
            len(text.encode()),
            max_bytes,
            ", ".join(cut),
        )
    return text
