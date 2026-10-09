"""Find the files in a workspace that match collection patterns.

The workspace is written by the agent, so finding candidates must stay cheap
however many entries the agent creates, and must never leave the workspace.
A bounded walk does both: each directory is opened relative to its parent
without following a symlink, listed one entry at a time, and abandoned once
it has shown max_directory_entries; the whole walk stops after max_entries.
Only directories some pattern can still match below are entered.

Patterns mean what `Path.glob` makes them mean, per path segment: `*`, `?`
and `[...]` never cross a `/`, and a `**` segment matches zero or more
directories. As with glob, a pattern whose last segment is `**` names
directories only, so it selects no files.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

logger = logging.getLogger(__name__)

_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
_RECURSIVE = "**"


class UnopenableDirectoryError(Exception):
    """A directory on the path is missing, not a directory, or a symlink."""


def open_directory(root: Path, parts: tuple[str, ...]) -> int:
    """Open root/parts as a directory without following a symlink anywhere.

    Every component is opened relative to the fd of its parent with
    O_NOFOLLOW, so a symlink swapped in at any point is refused rather than
    followed. Returns an fd; the caller closes it.
    """
    dir_fd = os.open(root, _DIR_OPEN_FLAGS)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, _DIR_OPEN_FLAGS, dir_fd=dir_fd)
            except OSError as e:
                raise UnopenableDirectoryError("a directory on its path is a symlink") from e
            os.close(dir_fd)
            dir_fd = next_fd
    except BaseException:
        os.close(dir_fd)
        raise
    return dir_fd


@dataclass(frozen=True)
class WalkLimits:
    """How far one walk may go before it stops looking."""

    max_matches: int
    max_entries: int
    max_directory_entries: int


# A position in one pattern: (pattern index, index of the next segment to match).
_State = tuple[int, int]


class _Patterns:
    """Collection patterns split into segments, matched one name at a time."""

    def __init__(self, patterns: list[str]) -> None:
        self._segments = [
            tuple(s for s in pattern.split("/") if s not in ("", ".")) for pattern in patterns
        ]

    def start(self) -> frozenset[_State]:
        return self._close((i, 0) for i in range(len(self._segments)))

    def enter(self, states: frozenset[_State], name: str) -> frozenset[_State]:
        """States after descending into directory `name`; empty means prune."""
        moved: list[_State] = []
        for p, i in states:
            segments = self._segments[p]
            if i == len(segments):
                continue
            if segments[i] == _RECURSIVE:
                moved.append((p, i))
            elif fnmatchcase(name, segments[i]):
                moved.append((p, i + 1))
        return frozenset(s for s in self._close(moved) if s[1] < len(self._segments[s[0]]))

    def selects_file(self, states: frozenset[_State], name: str) -> bool:
        """Whether a non-directory called `name` is selected by its last segment."""
        return any(
            i == len(self._segments[p]) - 1
            and self._segments[p][i] != _RECURSIVE
            and fnmatchcase(name, self._segments[p][i])
            for p, i in states
        )

    def _close(self, states: Iterable[_State]) -> frozenset[_State]:
        """Add the states reached by letting each `**` match no directories."""
        closed: set[_State] = set()
        for p, i in states:
            segments = self._segments[p]
            closed.add((p, i))
            while i < len(segments) and segments[i] == _RECURSIVE:
                i += 1
                closed.add((p, i))
        return frozenset(closed)


def _list_directory(
    root: Path, parts: tuple[str, ...], max_entries: int
) -> Iterator[os.DirEntry[str]]:
    """Yield up to max_entries entries of root/parts, streamed, never followed."""
    relative = "/".join(parts) or "."
    try:
        dir_fd = open_directory(root, parts)
    except (UnopenableDirectoryError, OSError) as e:
        logger.warning("copy_from: Did not list %s: %s", relative, e)
        return
    try:
        with os.scandir(dir_fd) as entries:
            for listed, entry in enumerate(entries):
                if listed == max_entries:
                    logger.warning(
                        "copy_from: Stopped listing %s after %d entries; the rest were not examined",
                        relative,
                        max_entries,
                    )
                    return
                yield entry
    finally:
        os.close(dir_fd)


def _is_real_directory(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def iter_matching_paths(root: Path, patterns: list[str], limits: WalkLimits) -> Iterator[str]:
    """Yield each distinct non-directory path under root that a pattern selects.

    Paths are relative to root, POSIX-style. A symlink is never entered,
    though a symlink whose name matches is yielded like any other
    non-directory: refusing to read it is the reader's job.
    """
    matcher = _Patterns(patterns)
    pending: list[tuple[tuple[str, ...], frozenset[_State]]] = [((), matcher.start())]
    examined = 0
    matched = 0
    while pending:
        parts, states = pending.pop()
        for entry in _list_directory(root, parts, limits.max_directory_entries):
            examined += 1
            if examined > limits.max_entries:
                logger.warning(
                    "copy_from: Stopped after examining %d entries; the rest were not collected",
                    limits.max_entries,
                )
                return
            if _is_real_directory(entry):
                below = matcher.enter(states, entry.name)
                if below:
                    pending.append(((*parts, entry.name), below))
            elif matcher.selects_file(states, entry.name):
                matched += 1
                if matched > limits.max_matches:
                    logger.warning(
                        "copy_from: Stopped after %d matches; the rest were not collected",
                        limits.max_matches,
                    )
                    return
                yield "/".join((*parts, entry.name))
