"""What a provisioned workspace is actually checked out at, read back before the agent (#967).

THE SETUP SCRIPT IS ASKED, AND THEN THE WORKSPACE IS ASKED. `pinned_checkout`
writes the lines that check each pinned repository out at its commit, and the
script exiting 0 says those lines ran. It does not say where HEAD ended up: a
step that silently did nothing, an image whose entrypoint moved HEAD, or a
backend that ran a different script would all exit 0 too. So the answer is read
off the workspace itself, once, after setup and before the agent is given it,
and that reading - not the request - is what the run records as its starting
state.

A REPOSITORY CONTINUING A BRANCH IS HELD TO THAT BRANCH, NOT TO ITS PIN. The
phase a resume resumes is checked out on its parent's branch at origin's head
(#1513); HEAD there is legitimately later than the pin, so equality with the pin
would refuse every such resume. What it is held to instead is the state the
setup script was asked for: HEAD at the head of `origin/<branch>` as fetched,
and that head containing the pin. Both are read back rather than taken from the
script's exit, for the same reason a pinned repository's HEAD is.

AN UNANSWERED READ IS NOT A VERDICT. `git` raises
`WorkspaceInspectionFailedError` for a workspace that does not answer, and that
propagates: a starting state nobody could read is not one anybody verified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CheckoutMismatch,
    CheckoutMismatchError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import git
from syn_shared.workspace_paths import WORKSPACE_REPOS_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
        GitWorkspace,
    )


async def verify_checkout(
    workspace: GitWorkspace,
    pinned: Mapping[str, str],
    *,
    continued_branches: Mapping[str, str],
    phase_name: str,
) -> tuple[SourceCommit, ...]:
    """Each pinned repository's actual HEAD, or raise if one is not at its pin.

    ``pinned`` maps ``owner/name`` to the commit the run pinned it to, exactly
    as handed to the setup script; a repository with no pin has nothing to be
    held to and is neither read nor recorded. Every repository is read before
    anything is refused, so the error names all of them.

    ``continued_branches`` maps ``owner/name`` to the branch that repository
    continues; such a repository is held to that branch's fetched head, which
    must contain its pin, rather than to the pin itself.

    Raises:
        CheckoutMismatchError: a repository is not at its pin, or not at the
            head of the branch it continues, or that head lacks its pin.
        WorkspaceInspectionFailedError: the workspace did not answer.
    """
    checked_out: list[SourceCommit] = []
    mismatches: list[CheckoutMismatch] = []
    for repository, pinned_sha in sorted(pinned.items()):
        repo_dir = str(WORKSPACE_REPOS_DIR / repository.rsplit("/", 1)[-1])
        actual_sha = (await git(workspace, repo_dir, "rev-parse", "HEAD")).strip()
        checked_out.append(SourceCommit(repository=repository, sha=actual_sha))
        branch = continued_branches.get(repository)
        if branch is None:
            if actual_sha != pinned_sha:
                mismatches.append(CheckoutMismatch(repository, pinned_sha, actual_sha))
        elif not await _on_branch_head(workspace, repo_dir, branch, pinned_sha, actual_sha):
            mismatches.append(CheckoutMismatch(repository, pinned_sha, actual_sha, branch=branch))
    if mismatches:
        raise CheckoutMismatchError(phase_name=phase_name, mismatches=tuple(mismatches))
    return tuple(checked_out)


async def _on_branch_head(
    workspace: GitWorkspace, repo_dir: str, branch: str, pinned_sha: str, actual_sha: str
) -> bool:
    """Whether ``actual_sha`` is ``origin/<branch>``'s fetched head and contains the pin.

    The containment read lists the pin's history NOT reachable from HEAD, which
    is empty exactly when HEAD contains the pin. It is asked that way, not with
    `merge-base --is-ancestor`, because that answers "no" with a non-zero exit,
    which `git` would read as the workspace not answering.
    """
    branch_head = (
        await git(workspace, repo_dir, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
    ).strip()
    if actual_sha != branch_head:
        return False
    missing = await git(workspace, repo_dir, "rev-list", "-n", "1", pinned_sha, "--not", "HEAD")
    return not missing.strip()
