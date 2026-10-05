"""The workflow-safe rescue of quarantined work (#1437).

When the quarantine push is refused because the phase's work touches
``.github/workflows/`` - which this App may not push (#1024) - the work is
retried once without that directory. The changes left out are kept twice: as
a patch inside the rescue commit and on the record, so they survive even when
the second push fails too. The first push, its deadline and the record of what
became of both live in `unpushed_work_guard`; this module builds the second.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    RESCUE_BUNDLE_NAME,
    RESCUE_PATCH_NAME,
    DroppedWorkflows,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    UNPUSHABLE_WORKFLOW_DIR,
    GitWorkspace,
    git,
    push,
)
from syn_shared.process_exit import describe_process_failure

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

#: The quarantine commit is written through a scratch index so the doomed
#: worktree's own index is never touched. Starting from an empty file also
#: means the tree is the WORKTREE as it stands rather than whatever happened to
#: be staged - at the cost of re-hashing every tracked file, which is
#: acceptable on a path that only runs when a phase is already failing.
SCRATCH_INDEX: Final[str] = "/tmp/syn-quarantine.index"

#: Where a workflow-safe rescue (#1437) writes its patch and bundle before
#: hashing them into the commit. Suffixes of the scratch index, so one `rm`
#: clears all three and anything that relocates the index relocates these.
SCRATCH_PATCH: Final[str] = f"{SCRATCH_INDEX}.patch"
SCRATCH_BUNDLE: Final[str] = f"{SCRATCH_INDEX}.bundle"

#: The directory a workflow-safe rescue puts its own files in, and how many
#: numbered variants it tries when the phase's tree already holds that name.
#: Checked against the tree rather than assumed free, so a phase's own files
#: can never be overwritten by the rescue of them.
_RESCUE_DIR: Final[str] = ".syn-quarantine"
_RESCUE_DIR_CANDIDATES: Final[int] = 100

#: How GitHub says a push was refused for touching workflows, and nothing
#: else in a refusal does. Read from stderr because nothing else differs: git
#: exits the same code for every refusal (see `workspace_git.answered`).
#:
#: - a GitHub App, the credential every workspace holds (#1024, #1437):
#:   ``refusing to allow a GitHub App to create or update workflow
#:   `.github/workflows/test.yml` without `workflows` permission``
#: - a classic OAuth or personal token without the scope:
#:   ``refusing to allow an OAuth App to create or update workflow
#:   `.github/workflows/test.yml` without `workflow` scope``
_WORKFLOW_REFUSALS: Final[tuple[str, ...]] = (
    "without `workflows` permission",
    "`workflow` scope",
)


@dataclass(slots=True)
class RescueAttempt:
    """How far a workflow-safe rescue got (#1437), written as it goes.

    MUTABLE ON PURPOSE: the rescue runs under a deadline that may abandon it
    part-way, and whatever it had produced by then - above all the patch - must
    still reach the record. A return value would be lost with the task.
    """

    #: Why the first push was refused, already described for a reader.
    refusal: str
    #: Set as soon as the patch exists, before anything that can still fail.
    dropped: DroppedWorkflows | None = None
    #: Why the rescue commit could not be built, if it could not.
    failure: str | None = None
    #: The second push's result; None when it was never made.
    second: ExecutionResult | None = None
    #: The workflow-safe commit the second push sent, set before it is pushed,
    #: so a ref the rescue landed is reported at the SHA it holds (#1547).
    commit: str | None = None


@dataclass(frozen=True, slots=True)
class _History:
    """The phase's unpushed commits, and the pushed commit the rescue builds on."""

    #: ``["HEAD"]``, or empty in a repository with no commits yet.
    tips: list[str]
    #: Every commit reachable from a local tip that origin does not have.
    local: frozenset[str]
    #: The newest first-parent commit origin was last known to have, if any.
    base: str | None
    #: What the tree is compared against: ``base``, or the empty tree.
    since: str


def refused_for_workflows(result: ExecutionResult) -> bool:
    """Whether this push was refused for touching ``.github/workflows/`` (#1437).

    THE ONLY PLACE GitHub's wording is known. A miss here costs nothing new: the
    refusal is then reported exactly as it was before this existed.
    """
    return result.exit_code != 0 and any(said in result.stderr for said in _WORKFLOW_REFUSALS)


def push_failure(what: str, result: ExecutionResult) -> str:
    return describe_process_failure(
        what,
        exit_code=result.exit_code,
        output=result.stderr or result.stdout,
        timed_out=result.timed_out,
    )


async def push_without_workflows(
    workspace: GitWorkspace, repo: str, *, tree: str, ref: str, attempt: RescueAttempt
) -> ExecutionResult | None:
    """Build the workflow-safe commit and push it; None when no push was made."""
    try:
        commit = await _prepare_rescue(workspace, repo, tree=tree, ref=ref, attempt=attempt)
    except WorkspaceInspectionFailedError as unbuildable:
        attempt.failure = unbuildable.summary
        return None
    if commit is None:
        return None
    attempt.commit = commit
    # The SAME ref, still without force: the refused push never created it.
    return await push(workspace, repo, commit=commit, ref=ref)


async def _prepare_rescue(
    workspace: GitWorkspace, repo: str, *, tree: str, ref: str, attempt: RescueAttempt
) -> str | None:
    """The commit GitHub will take from this App, or None if there is nothing to change.

    ITS TREE is ``tree`` - the phase's whole worktree - with
    ``.github/workflows/`` exactly as ``base`` has it, and ITS ONLY PARENT is
    ``base``: the newest commit on HEAD's first-parent line that origin was
    last known to have. Both halves are needed. GitHub refuses a deletion as
    readily as an edit, so the directory cannot simply be left out; and it
    inspects every new commit, so the phase's own commits, which carry the
    edit, cannot be parents. What that costs is kept in the same commit, in a
    directory checked to be free: the dropped changes as a patch, and the
    original commits as a bundle.

    THE HISTORY ALONE CAN BE THE REFUSAL. When the phase's commits edited a
    workflow and later restored it, the tree holds nothing to drop, yet the
    first push was refused for those commits all the same. The rescue is then
    built anyway - flattened onto ``base``, with no patch and the bundle - and
    only when there is neither a path to drop nor a local commit to flatten is
    there nothing it could change.

    The worktree is never touched - every index change goes to the scratch
    index the first push already filled. The patch is written before any of
    that, into `attempt`, so a failure later on still leaves it to be stored.
    """
    history = await _unpushed_history(workspace, repo)
    scope = ("--", f"{UNPUSHABLE_WORKFLOW_DIR}/")
    changed = await git(
        workspace,
        repo,
        "diff-tree",
        "-r",
        "--name-only",
        "--no-renames",
        history.since,
        tree,
        *scope,
    )
    paths = tuple(line for line in changed.splitlines() if line)
    if not paths and not history.local:
        # Nothing to drop and no history to flatten: whatever GitHub saw, this
        # rescue could not change it, so the first refusal stands alone.
        return None
    # NO PATH CHANGED IS NOT NO REFUSAL. An unpushed commit that edited a
    # workflow and a later one that put it back leave the tree equal to the
    # base, and GitHub still refuses the edit in the history. Flattening is
    # then the whole fix, and there is simply no patch to keep.
    patch_blob, patch = await _write_patch(workspace, repo, history.since, tree, scope, paths)
    attempt.dropped = DroppedWorkflows(
        paths=paths,
        refusal=attempt.refusal,
        base=history.base,
        patch=patch,
        artifact_title=(
            f"{repo.rsplit('/', 1)[-1]}: {UNPUSHABLE_WORKFLOW_DIR} changes this App "
            f"could not push (#1437)"
        ),
    )

    rescue_dir = await _free_directory(workspace, repo, tree)
    if rescue_dir is None:
        attempt.failure = (
            f"no free directory for the rescue's own files: {_RESCUE_DIR} and its "
            f"{_RESCUE_DIR_CANDIDATES - 1} numbered variants are all in the phase's tree"
        )
        return None
    attempt.dropped = replace(attempt.dropped, rescue_dir=rescue_dir)

    await _restore_workflow_dir(workspace, repo, history.base)
    if patch_blob is not None:
        await _add_blob(workspace, repo, patch_blob, f"{rescue_dir}/{RESCUE_PATCH_NAME}")
    if history.local:
        await _add_bundle(workspace, repo, history.tips, f"{rescue_dir}/{RESCUE_BUNDLE_NAME}")
        attempt.dropped = replace(attempt.dropped, has_bundle=True)
    return await _commit_rescue(workspace, repo, history.base, ref=ref, dropped=attempt.dropped)


async def _unpushed_history(workspace: GitWorkspace, repo: str) -> _History:
    """HEAD's unpushed commits, the base they sit on, and what to diff against."""
    head = (await git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip()
    tips = ["HEAD"] if head else []
    unpushed = await git(
        workspace, repo, "rev-list", *tips, "--branches", "--not", "--remotes=origin"
    )
    local = frozenset(unpushed.split())
    base: str | None = None
    if head:
        line = await git(
            workspace, repo, "rev-list", "--first-parent", f"--max-count={len(local) + 1}", "HEAD"
        )
        base = next((sha for sha in line.split() if sha not in local), None)
    since = base or (await git(workspace, repo, "hash-object", "-t", "tree", "/dev/null")).strip()
    return _History(tips=tips, local=local, base=base, since=since)


async def _write_patch(
    workspace: GitWorkspace,
    repo: str,
    since: str,
    tree: str,
    scope: tuple[str, str],
    paths: tuple[str, ...],
) -> tuple[str | None, str]:
    """The dropped workflow changes as a stored blob and its text; (None, "") when none."""
    if not paths:
        return None, ""
    await git(
        workspace,
        repo,
        "diff-tree",
        "-p",
        "--binary",
        "--no-renames",
        f"--output={SCRATCH_PATCH}",
        since,
        tree,
        *scope,
    )
    patch_blob = (await git(workspace, repo, "hash-object", "-w", SCRATCH_PATCH)).strip()
    return patch_blob, await git(workspace, repo, "cat-file", "blob", patch_blob)


async def _restore_workflow_dir(workspace: GitWorkspace, repo: str, base: str | None) -> None:
    """Put ``.github/workflows/`` back as ``base`` has it, in the scratch index only."""
    if base is not None:
        await git(
            workspace,
            repo,
            "reset",
            "-q",
            base,
            "--",
            UNPUSHABLE_WORKFLOW_DIR,
            index=SCRATCH_INDEX,
        )
        return
    await git(
        workspace,
        repo,
        "rm",
        "--cached",
        "-r",
        "-q",
        "--ignore-unmatch",
        "--",
        UNPUSHABLE_WORKFLOW_DIR,
        index=SCRATCH_INDEX,
    )


async def _add_bundle(workspace: GitWorkspace, repo: str, tips: list[str], path: str) -> None:
    """Keep the phase's original commits as a bundle at ``path`` in the rescue commit."""
    await git(
        workspace,
        repo,
        "bundle",
        "create",
        "-q",
        SCRATCH_BUNDLE,
        *tips,
        "--branches",
        "--not",
        "--remotes=origin",
    )
    bundle_blob = (await git(workspace, repo, "hash-object", "-w", SCRATCH_BUNDLE)).strip()
    await _add_blob(workspace, repo, bundle_blob, path)


async def _commit_rescue(
    workspace: GitWorkspace,
    repo: str,
    base: str | None,
    *,
    ref: str,
    dropped: DroppedWorkflows | None,
) -> str:
    safe_tree = (await git(workspace, repo, "write-tree", index=SCRATCH_INDEX)).strip()
    commit = await git(
        workspace,
        repo,
        "commit-tree",
        safe_tree,
        *(("-p", base) if base is not None else ()),
        "-m",
        commit_message(ref, dropped=dropped),
        identity=True,
    )
    return commit.strip()


async def _free_directory(workspace: GitWorkspace, repo: str, tree: str) -> str | None:
    """The first rescue directory name ``tree`` does not already hold, or None."""
    for n in range(1, _RESCUE_DIR_CANDIDATES + 1):
        name = _RESCUE_DIR if n == 1 else f"{_RESCUE_DIR}-{n}"
        if not (await git(workspace, repo, "ls-tree", tree, "--", name)).strip():
            return name
    return None


async def _add_blob(workspace: GitWorkspace, repo: str, blob: str, path: str) -> None:
    await git(
        workspace,
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{blob},{path}",
        index=SCRATCH_INDEX,
    )


def commit_message(ref: str, *, dropped: DroppedWorkflows | None = None) -> str:
    """The quarantine commit's message; with ``dropped``, the workflow-safe one's (#1437)."""
    message = (
        f"syn: quarantined work that would have been lost ({ref})\n\n"
        "The phase that produced this ended without pushing it, and its "
        "workspace was about to be destroyed. "
    )
    if dropped is None:
        return message + (
            "This commit's tree is the working tree as it stood; its parents are "
            "the local tips carrying commits the remote did not have.\n"
        )
    onto = dropped.base if dropped.base is not None else "no parent"
    if not dropped.paths:
        return message + (
            f"This commit's tree is the working tree as it stood. The first push "
            f"of this work was refused because an unpushed commit changed "
            f"{UNPUSHABLE_WORKFLOW_DIR}/, which this App may not push (#1024); "
            f"the tree has it exactly as {onto} does, so nothing was left out.\n\n"
            f"History was flattened onto {onto}; the original commits are in "
            f"{dropped.rescue_dir}/{RESCUE_BUNDLE_NAME}.\n"
        )
    lines = [
        message + f"This commit's tree is the working tree as it stood, EXCEPT "
        f"{UNPUSHABLE_WORKFLOW_DIR}/, which is exactly as {onto} has it: "
        "this App may not push workflow changes (#1024), and the first push "
        "of this work was refused for them.",
        "",
        "Left out, and kept as a patch in "
        f"{dropped.rescue_dir}/{RESCUE_PATCH_NAME} (git apply it):",
        *(f"  {path}" for path in dropped.paths),
        "",
        f"History was flattened onto {onto}"
        + (
            f"; the original commits are in {dropped.rescue_dir}/{RESCUE_BUNDLE_NAME}."
            if dropped.has_bundle
            else "."
        ),
    ]
    return "\n".join(lines) + "\n"
