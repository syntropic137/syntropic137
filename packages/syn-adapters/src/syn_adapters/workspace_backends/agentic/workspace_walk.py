"""Find the files in a workspace that match collection patterns.

The workspace is written by the agent, so finding candidates must stay cheap
however many entries the agent creates, and must never leave the workspace.
A bounded walk does both: each directory is opened once, relative to the
fd of its parent and without following a symlink, listed one entry at a time,
and abandoned once it has shown max_directory_entries; the whole walk stops
after max_entries, and goes no deeper than max_depth. Only directories some
pattern can still match below are entered.

Relative paths are built by joining the names already listed, never by
turning an fd back into a path, so the walk needs only `os.scandir(fd)` and
`os.open(..., dir_fd=...)`: both available on Linux and macOS.

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
    max_depth: int


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


def _is_real_directory(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


class _EntryBudget:
    """Entries examined so far across the whole walk."""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self.examined = 0
        self.spent = False

    def take(self) -> bool:
        """Count one entry; False once the walk must stop."""
        self.examined += 1
        if self.examined > self.max_entries:
            if not self.spent:
                logger.warning(
                    "copy_from: Stopped after examining %d entries; the rest were not collected",
                    self.max_entries,
                )
            self.spent = True
        return not self.spent


def _listing(dir_fd: int, parts: tuple[str, ...], max_entries: int) -> Iterator[os.DirEntry[str]]:
    """Yield up to max_entries entries of the open directory dir_fd, streamed."""
    with os.scandir(dir_fd) as entries:
        for listed, entry in enumerate(entries):
            if listed == max_entries:
                logger.warning(
                    "copy_from: Stopped listing %s after %d entries; the rest were not examined",
                    "/".join(parts) or ".",
                    max_entries,
                )
                return
            yield entry


def _open_child(dir_fd: int, child: tuple[str, ...], max_depth: int) -> int | None:
    """Open child (named by its last part) relative to dir_fd, never following a symlink.

    Returns None, after a warning, when it is too deep or cannot be opened
    as a directory; the caller closes a returned fd.
    """
    relative = "/".join(child)
    if len(child) > max_depth:
        logger.warning(
            "copy_from: Did not enter %s: deeper than %d directories", relative, max_depth
        )
        return None
    try:
        return os.open(child[-1], _DIR_OPEN_FLAGS, dir_fd=dir_fd)
    except OSError as e:
        logger.warning("copy_from: Did not list %s: %s", relative, e)
        return None


def _walk_directory(
    dir_fd: int,
    parts: tuple[str, ...],
    states: frozenset[_State],
    matcher: _Patterns,
    limits: WalkLimits,
    budget: _EntryBudget,
) -> Iterator[tuple[tuple[str, ...], frozenset[_State], os.DirEntry[str]]]:
    """Yield the non-directories below the open directory dir_fd (root/parts).

    Each subdirectory is opened once, relative to dir_fd, with O_NOFOLLOW, and
    held open only while it is being walked: at most max_depth directories
    are open at a time, and no directory is reopened from the root.
    """
    for entry in _listing(dir_fd, parts, limits.max_directory_entries):
        if not budget.take():
            return
        if not _is_real_directory(entry):
            yield parts, states, entry
            continue
        below = matcher.enter(states, entry.name)
        child = (*parts, entry.name)
        child_fd = _open_child(dir_fd, child, limits.max_depth) if below else None
        if child_fd is None:
            continue
        try:
            yield from _walk_directory(child_fd, child, below, matcher, limits, budget)
        finally:
            os.close(child_fd)
        if budget.spent:
            return


def _reachable_files(
    root: Path, matcher: _Patterns, limits: WalkLimits
) -> Iterator[tuple[tuple[str, ...], frozenset[_State], os.DirEntry[str]]]:
    """Yield (directory parts, states there, entry) for each non-directory.

    Enters only real directories that a pattern can still match below, and
    stops after limits.max_entries entries in all.
    """
    try:
        root_fd = open_directory(root, ())
    except OSError as e:
        logger.warning("copy_from: Did not list .: %s", e)
        return
    try:
        yield from _walk_directory(
            root_fd, (), matcher.start(), matcher, limits, _EntryBudget(limits.max_entries)
        )
    finally:
        os.close(root_fd)


def iter_matching_paths(root: Path, patterns: list[str], limits: WalkLimits) -> Iterator[str]:
    """Yield each distinct non-directory path under root that a pattern selects.

    Paths are relative to root, POSIX-style. A symlink is never entered,
    though a symlink whose name matches is yielded like any other
    non-directory: refusing to read it is the reader's job.
    """
    matcher = _Patterns(patterns)
    matched = 0
    for parts, states, entry in _reachable_files(root, matcher, limits):
        if not matcher.selects_file(states, entry.name):
            continue
        matched += 1
        if matched > limits.max_matches:
            logger.warning(
                "copy_from: Stopped after %d matches; the rest were not collected",
                limits.max_matches,
            )
            return
        yield "/".join((*parts, entry.name))
