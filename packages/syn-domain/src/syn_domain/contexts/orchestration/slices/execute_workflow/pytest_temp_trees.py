"""Porcelain lines that are pytest's temp root, not work (#2200).

A phase that ran pytest with TMPDIR inside its repository leaves an untracked
``pytest-of-<user>/`` at the top of it, and ``status --porcelain`` reports it
as ``?? pytest-of-agent/`` - the line an agent's new directory of source
produces. Reading it as work failed a phase that had pushed everything.

`split_pytest_temp_trees` is that one distinction. It asks the workspace what
is in the tree and judges it by `is_pytest_temp_root`, the rule the reclaimer
uses for the same trees on the host, so there is one rule and not a looser
second one. The verdict only ever WEAKENS the unpushed-work gate, so every
doubt resolves to keeping the line: a listing that fails, a name pytest would
not write, a child of any other shape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syn_shared.pytest_temp import (
    PYTEST_TEMP_PREFIX,
    EntryKind,
    TempTreeEntry,
    is_pytest_temp_root,
)

from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    run_bounded,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
        GitWorkspace,
    )

logger = logging.getLogger(__name__)

#: The porcelain v1 status of a path git does not track.
_UNTRACKED: Final = "?? "

#: ``find -printf`` type letters, without following links.
_KINDS: Final = {"d": EntryKind.DIRECTORY, "l": EntryKind.SYMLINK}


@dataclass(frozen=True)
class SplitTempTrees:
    """Porcelain v1 lines of one repository, with pytest's temp roots taken out."""

    #: Every line that is still somebody's work.
    authored: tuple[str, ...]
    #: The repository-relative paths of the pytest temp roots left out.
    ignored: tuple[str, ...] = ()


async def split_pytest_temp_trees(
    workspace: GitWorkspace, repo: str, files: tuple[str, ...]
) -> SplitTempTrees:
    """Separate ``files`` - porcelain v1 lines of ``repo`` - from pytest's temp roots.

    Only a collapsed untracked directory at the top of the repository is a
    candidate, ``?? pytest-of-<user>/``: that is how git reports a tree none
    of whose files it tracks. Any other spelling - a path git had to quote, a
    file listed inside one, a tracked change - stays work. Each tree left out
    is logged by name, because it is about to be destroyed with the workspace.
    """
    authored: list[str] = []
    ignored: list[str] = []
    for line in files:
        root = _candidate(line)
        if root is not None and await _made_by_pytest(workspace, f"{repo}/{root}"):
            ignored.append(root)
        else:
            authored.append(line)
    if ignored:
        logger.info(
            "Leaving %d pytest temp root(s) in %s to the workspace: untracked, and "
            "holding only what pytest writes there, so not work. Paths: %s",
            len(ignored),
            repo,
            ", ".join(ignored),
        )
    return SplitTempTrees(authored=tuple(authored), ignored=tuple(ignored))


def _candidate(line: str) -> str | None:
    """The top-level directory name an untracked line reports, if it could be pytest's."""
    if not line.startswith(_UNTRACKED) or not line.endswith("/"):
        return None
    name = line[len(_UNTRACKED) : -1]
    if not name.startswith(PYTEST_TEMP_PREFIX) or "/" in name:
        return None
    return name


async def _made_by_pytest(workspace: GitWorkspace, root: str) -> bool:
    """Whether ``root``, listed in the workspace, is a real directory of pytest's shape.

    NUL-separated so that no name can pass for two entries. Depth 0 is the
    root itself, and must be a real directory: ``find`` does not follow a
    symlink it is handed, so a linked root would otherwise list as empty.
    """
    result = await run_bounded(
        workspace, ["find", root, "-maxdepth", "1", "-printf", r"%d %y %f\0"]
    )
    complete = result.stdout.endswith("\0")
    if not result.success or result.exit_code != 0 or result.timed_out or not complete:
        logger.info(
            "Could not list %s (exit %d), so it is judged as work.", root, result.exit_code
        )
        return False
    root_is_dir = False
    children: list[TempTreeEntry] = []
    for record in result.stdout.split("\0")[:-1]:
        depth, _, rest = record.partition(" ")
        kind, _, name = rest.partition(" ")
        if depth == "0":
            root_is_dir = kind == "d"
        elif depth == "1":
            children.append(TempTreeEntry(name, _KINDS.get(kind, EntryKind.OTHER)))
        else:
            return False
    return root_is_dir and is_pytest_temp_root(root.rpartition("/")[2], children)
