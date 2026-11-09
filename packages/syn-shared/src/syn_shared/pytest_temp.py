"""What a temp tree pytest made looks like, and nothing else does (#2095, #2200).

Two callers ask "did pytest make this, and only pytest", from opposite sides
of the workspace. The reclaimer on the host walks a workspace directory's
TMPDIR (`syn_adapters.workspace_backends.stale_dirs`), and the unpushed-work
guard inside the workspace reads an untracked ``pytest-of-<user>/`` in a
repository (`execute_workflow.pytest_temp_trees`). One sees a filesystem, the
other only the output of a command, so the rule is stated here over plain
entries and each caller says how it listed them. Two copies of the rule would
drift, and the looser one would decide.

The rule only ever lets something be thrown away, so anything it does not
recognise - another name, an unexpected child, a child of an unknown kind - is
not pytest's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["PYTEST_TEMP_PREFIX", "EntryKind", "TempTreeEntry", "is_pytest_temp_root"]

#: pytest's per-user temp root under TMPDIR, ``<tmp>/pytest-of-<user>``
#: (``_pytest/tmpdir.py``, ``TempPathFactory.getbasetemp``).
PYTEST_TEMP_PREFIX: Final = "pytest-of-"

#: What pytest writes directly inside ``pytest-of-<user>`` and nothing else
#: (``_pytest/pathlib.py``): numbered run dirs ``pytest-<N>``
#: (``make_numbered_dir``), a ``pytest-current`` symlink to the newest
#: (``_force_symlink``), and ``garbage-<uuid4>`` dirs it is part way through
#: deleting (``maybe_delete_a_numbered_dir``).
_PYTEST_RUN_DIR: Final = re.compile(r"pytest-[0-9]+")
_PYTEST_GARBAGE_DIR: Final = re.compile(
    r"garbage-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_PYTEST_CURRENT_LINK: Final = "pytest-current"


class EntryKind(Enum):
    """What a directory entry is, as seen without following it."""

    DIRECTORY = "directory"
    SYMLINK = "symlink"
    #: A regular file, a socket, or anything the lister could not name.
    OTHER = "other"


@dataclass(frozen=True)
class TempTreeEntry:
    """One direct child of a candidate temp root."""

    name: str
    kind: EntryKind


def is_pytest_temp_root(name: str, children: Iterable[TempTreeEntry]) -> bool:
    """Whether a real directory called ``name``, holding ``children``, is pytest's.

    ``name`` must carry `PYTEST_TEMP_PREFIX`, and each child must be either the
    ``pytest-current`` symlink or a real directory pytest names a run or a
    deletion in progress. That the root itself is a real directory, and not a
    symlink to one, is the caller's to establish: how to know depends on what
    it can see. What is inside the run dirs is pytest's business and is not
    looked at.
    """
    if not name.startswith(PYTEST_TEMP_PREFIX):
        return False
    return all(_pytest_wrote(child) for child in children)


def _pytest_wrote(child: TempTreeEntry) -> bool:
    if child.kind is EntryKind.SYMLINK:
        return child.name == _PYTEST_CURRENT_LINK
    if child.kind is EntryKind.DIRECTORY:
        return bool(
            _PYTEST_RUN_DIR.fullmatch(child.name) or _PYTEST_GARBAGE_DIR.fullmatch(child.name)
        )
    return False
