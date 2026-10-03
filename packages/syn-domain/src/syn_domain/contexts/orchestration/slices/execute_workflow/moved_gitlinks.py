"""Porcelain lines that are a submodule gitlink git moved, not work (#1499).

``git checkout <sha>`` without ``--recurse-submodules`` moves the gitlink the
superproject records and leaves the submodule where it was, and
``status --porcelain`` then reports `` M <path>`` - byte for byte the line a
submodule an agent edited or committed in produces. Reading it as work failed
finished review phases and discarded what they wrote.

`split_moved_gitlinks` is that one distinction, and it asks the submodule
rather than the porcelain line, because the line for the two cases is
identical. The verdict only ever WEAKENS the unpushed-work gate, so every doubt
resolves to keeping the line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    GitWorkspace,
    git,
)

#: The escapes git's C-style path quoting writes besides octal bytes.
_C_ESCAPES: Final = {
    "a": 0x07,
    "b": 0x08,
    "t": 0x09,
    "n": 0x0A,
    "v": 0x0B,
    "f": 0x0C,
    "r": 0x0D,
    '"': 0x22,
    "\\": 0x5C,
}

#: Width of an escape git writes as a backslash and three octal digits.
_OCTAL_ESCAPE_WIDTH: Final[int] = 4


@dataclass(frozen=True)
class SplitStatus:
    """Porcelain v1 lines of one repository, with the moved gitlinks taken out."""

    #: Every line that is still somebody's work.
    authored: tuple[str, ...]
    #: The decoded paths of the submodules git moved, not anybody wrote in.
    moved: frozenset[str]


async def split_moved_gitlinks(
    workspace: GitWorkspace, repo: str, files: tuple[str, ...]
) -> SplitStatus:
    """Separate ``files`` - porcelain v1 lines of ``repo`` - from the gitlinks git moved.

    Compared as decoded paths, never as lines: v1 quotes a path with a space in
    it and v2 does not, so two spellings of one path never match.
    """
    if not files:
        return SplitStatus(authored=files, moved=frozenset())
    moved = await _moved_gitlinks(workspace, repo)
    authored = tuple(
        line for line in files if not (line[:3] == " M " and _unquote(line[3:]) in moved)
    )
    return SplitStatus(authored=authored, moved=moved)


async def _moved_gitlinks(workspace: GitWorkspace, repo: str) -> frozenset[str]:
    """The paths of submodules git moved, not anybody wrote in.

    The line is only exempted on evidence from both sides of the gitlink:

    - porcelain v2's submodule token is exactly ``SC..``, staged nothing: the
      checked-out commit differs from the recorded one, and the submodule has
      neither tracked changes nor untracked files. Any ``m`` or ``u`` is a
      file somebody wrote in there, and stays work.
    - no commit in the submodule - its HEAD or anything any ref of its own
      reaches, branch, tag or stash alike - is missing from every one of its
      remotes. A commit the phase made in the submodule is authored work whose
      objects nothing here quarantines, so it must keep failing the phase,
      whatever kind of ref it was left on.

    Paths come back DECODED (`_unquote`), because v1 and v2 do not quote the
    same paths the same way. Everything else - a staged gitlink, a rename - is
    left as the work it looks like.
    """
    status = await git(workspace, repo, "status", "--porcelain=v2")
    moved: set[str] = set()
    for entry in status.splitlines():
        # `1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>`: the path is the
        # ninth field and the only one that may itself contain spaces.
        fields = entry.split(" ", 8)
        if len(fields) != 9 or fields[:3] != ["1", ".M", "SC.."]:
            continue
        path = _unquote(fields[8])
        # --all, not --branches: a tag or a stash keeps a commit alive in the
        # submodule exactly as a branch does, and no remote has it either.
        stranded = await git(
            workspace, f"{repo}/{path}", "rev-list", "HEAD", "--all", "--not", "--remotes"
        )
        if not stranded.strip():
            moved.add(path)
    return frozenset(moved)


def _unquote(path: str) -> str:
    """A porcelain path as the filesystem spells it.

    Git wraps a path in double quotes, with C escapes and octal-escaped bytes,
    when it holds a character it will not print bare - and v1 and v2 disagree
    on which characters those are (a space quotes in v1, not in v2). A path not
    in quotes is already literal. Bytes that do not decode as UTF-8 survive as
    surrogates, so such a path matches nothing and stays work.
    """
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        if body[i] != "\\" or i + 1 == len(body):
            out += body[i].encode("utf-8", "surrogateescape")
            i += 1
            continue
        escape = _escape_at(body, i)
        if escape is None:
            # Not a spelling git writes: leave it undecoded, so it matches
            # nothing and the line stays work.
            return path
        byte, width = escape
        out.append(byte)
        i += width
    return out.decode("utf-8", "surrogateescape")


def _escape_at(body: str, i: int) -> tuple[int, int] | None:
    """The byte the escape at ``body[i]`` spells and its width, or None if git never writes it."""
    letter = body[i + 1]
    if letter in _C_ESCAPES:
        return _C_ESCAPES[letter], 2
    octal = body[i + 1 : i + _OCTAL_ESCAPE_WIDTH]
    if len(octal) != _OCTAL_ESCAPE_WIDTH - 1 or not all(c in "01234567" for c in octal):
        return None
    return int(octal, 8) & 0xFF, _OCTAL_ESCAPE_WIDTH
