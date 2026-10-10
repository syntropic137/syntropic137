"""The file-change summary a quarantine notice shows, and the base it is taken against (#1547).

THE BASE IS THE BRANCH THE WORK TRACKS. Unpushed history can have several
remote ancestors - a merge of another remote branch gives it two - and
``rev-list --boundary`` lists them in an order that says nothing about which
one is the PR's. Diffing against whichever came first listed files the PR
branch already had and dropped the work merged into it. So the contract is
explicit, in this order:

1. the branch's configured upstream, ``<branch>@{upstream}``;
2. ``refs/remotes/origin/<branch>``, for a branch pushed without ``-u``;
3. the single remote ancestor, when there is exactly one;
4. the empty tree, when no remote holds any ancestor at all.

Anything else - several remote ancestors and no tracked branch to choose
between them - is ambiguous, and the summary is left out rather than guessed.

Local only - no remote is asked. Never raises: a summary that cannot be read is
left out of the notice, never a lost ref.
"""

from __future__ import annotations

import logging
from typing import Final

from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    GitWorkspace,
    git,
)

logger = logging.getLogger(__name__)

#: The diffstat's line width and how many files it names before summarising.
_DIFFSTAT_WIDTH: Final[int] = 100
_DIFFSTAT_FILES: Final[int] = 20
#: git's well-known empty tree: the base when no remote holds any ancestor.
_EMPTY_TREE: Final[str] = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


async def diffstat(workspace: GitWorkspace, repo: str, commit: str, *, branch: str) -> str | None:
    """``git diff --stat`` of ``commit`` against the base `branch` tracks, or None."""
    try:
        base = await _base(workspace, repo, commit, branch=branch)
        if base is None:
            logger.info(
                "Leaving the diffstat out of %s's notice: %s tracks no remote branch and "
                "the work has several remote ancestors to choose between",
                repo,
                branch,
            )
            return None
        # Three dots: from where the work left the branch, so a branch a
        # teammate moved since is not read as this work deleting theirs. The
        # empty tree is no commit and has no merge base, so it takes two.
        span = [base, commit] if base == _EMPTY_TREE else [f"{base}...{commit}"]
        stat = await git(
            workspace,
            repo,
            "diff",
            f"--stat={_DIFFSTAT_WIDTH}",
            f"--stat-count={_DIFFSTAT_FILES}",
            *span,
        )
    except Exception:
        logger.warning("Could not summarise the quarantined work in %s", repo, exc_info=True)
        return None
    return stat.rstrip() or None


async def _base(workspace: GitWorkspace, repo: str, commit: str, *, branch: str) -> str | None:
    """The commit to diff against, by the contract in the module docstring."""
    for tracked in (f"{branch}@{{upstream}}", f"refs/remotes/origin/{branch}"):
        found = await _resolve(workspace, repo, tracked)
        if found is not None:
            return found
    boundary = await git(workspace, repo, "rev-list", "--boundary", commit, "--not", "--remotes")
    bases = {line[1:] for line in boundary.split() if line.startswith("-")}
    if not bases:
        return _EMPTY_TREE
    return bases.pop() if len(bases) == 1 else None


async def _resolve(workspace: GitWorkspace, repo: str, rev: str) -> str | None:
    """``rev`` as a commit, or None when it names nothing (a branch with no upstream)."""
    try:
        sha = await git(workspace, repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except Exception:
        return None
    return sha.strip() or None
