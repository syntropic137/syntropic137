"""The gate that stops a phase completing while holding unreachable work (#1184).

Every phase runs in an ephemeral workspace that is destroyed when the phase
ends. Until this gate existed, nothing checked that the phase had pushed: the
instruction lived in a prompt, and a phase that committed without pushing still
reported ``completed`` while its commits went into the bin with the container.

Called once per phase, immediately before the phase is declared complete and
while the workspace - and the git credential the setup phase deliberately
leaves in place - is still alive. It answers one question, "would anything in
this workspace fail to survive it", and if so puts that work somewhere durable
before raising. Callers need nothing but that: no git, no ref naming, no
knowledge of how many repositories a workspace holds.

SCOPE, stated because it is a real limit. Repositories are the ones cloned
directly under ``/workspace/repos``. Work committed inside a SUBMODULE of one
of those is DETECTED - the superproject reports a modified gitlink, so the
phase still fails rather than silently succeeding - but the submodule's own
objects are not quarantined, because they belong to a different remote. A
submodule's commits are recoverable only if the phase pushed them itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, Protocol

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    QuarantinedWork,
    UnpushedWorkQuarantinedError,
)
from syn_shared.workspace_paths import WORKSPACE_REPOS_DIR

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

logger = logging.getLogger(__name__)

#: Namespace for quarantined work. Deliberately outside refs/heads and
#: refs/tags: nothing fetches it by default, no PR shows it, and no reviewer is
#: ever shown it. It exists to be recovered on purpose, by someone who was told
#: the name.
_QUARANTINE_NAMESPACE: Final[str] = "refs/syn/lost"

#: The quarantine commit is written through a scratch index so the doomed
#: worktree's own index is never touched. Starting from an empty file also
#: means the tree is the WORKTREE as it stands rather than whatever happened to
#: be staged - at the cost of re-hashing every tracked file, which is
#: acceptable on a path that only runs when a phase is already failing.
_SCRATCH_INDEX: Final[str] = "/tmp/syn-quarantine.index"

#: commit-tree needs an identity and the container may have none: the setup
#: script configures user.name only when GIT_AUTHOR_NAME was supplied. Stating
#: it here removes that dependency; it matches the setup script's own fallback.
_IDENTITY: Final[tuple[str, ...]] = (
    "GIT_AUTHOR_NAME=syn-bot",
    "GIT_AUTHOR_EMAIL=agent@agentic.local",
    "GIT_COMMITTER_NAME=syn-bot",
    "GIT_COMMITTER_EMAIL=agent@agentic.local",
)


class GitWorkspace(Protocol):
    """The single workspace capability this gate needs: run a command in it."""

    async def execute(self, command: list[str]) -> ExecutionResult: ...


async def quarantine_unpushed_work(
    workspace: GitWorkspace,
    *,
    execution_id: str,
    phase_id: str,
) -> None:
    """Fail the phase if it is holding work the workspace's death would erase.

    Returns silently when every repository is clean and fully pushed - which is
    the normal case, and includes the phase that legitimately produced nothing
    at all (a bootstrap that only reports, a verify that only reads). Silence
    here means "nothing is being lost", never "nothing was checked".

    Raises:
        UnpushedWorkQuarantinedError: work was found. It has already been
            pushed to ``refs/syn/lost/<execution-id>/<phase-id>`` in each
            affected repository, and the error names those refs.
    """
    ref = f"{_QUARANTINE_NAMESPACE}/{execution_id}/{phase_id}"
    quarantined: list[QuarantinedWork] = []
    for repo in await _repositories(workspace):
        work = await _unsaved_work(workspace, repo)
        if work is not None:
            quarantined.append(await _quarantine(workspace, repo, work, ref=ref))
    if quarantined:
        raise UnpushedWorkQuarantinedError(phase_id=phase_id, quarantined=tuple(quarantined))


class _UnsavedWork:
    """A repository's unsaved state: what is missing, and from which tips."""

    __slots__ = ("branch", "commit_count", "files", "parents")

    def __init__(
        self,
        *,
        branch: str,
        commit_count: int,
        files: tuple[str, ...],
        parents: tuple[str, ...],
    ) -> None:
        self.branch = branch
        self.commit_count = commit_count
        self.files = files
        #: Commits the quarantine commit must descend from for every unpushed
        #: commit to be reachable through the one ref. HEAD first, so the
        #: recovered history reads as the phase left it.
        self.parents = parents


async def _repositories(workspace: GitWorkspace) -> list[str]:
    """Absolute paths of the repositories cloned into this workspace.

    An empty result means the execution was configured with no repositories,
    not that the workspace could not be reached: artifact collection copied
    files out of this same container moments earlier, so by the time the gate
    runs, unreachable has already failed the phase by another route.
    """
    found = await workspace.execute(
        ["find", str(WORKSPACE_REPOS_DIR), "-mindepth", "2", "-maxdepth", "2", "-name", ".git"]
    )
    suffix = "/.git"
    return sorted(
        line.strip()[: -len(suffix)] for line in found.stdout.splitlines() if line.strip()
    )


async def _unsaved_work(workspace: GitWorkspace, repo: str) -> _UnsavedWork | None:
    """What this repository holds that the remote does not, or None if nothing."""
    status = await _git(workspace, repo, "status", "--porcelain")
    tips = await _git(
        workspace, repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"
    )
    head = await _git(workspace, repo, "rev-parse", "--quiet", "--verify", "HEAD")

    named: list[tuple[str, str]] = [
        (sha, name)
        for sha, _, name in (line.partition(" ") for line in tips.stdout.splitlines())
        if sha
    ]
    head_sha = head.stdout.strip()
    # Every tip that could be carrying work, HEAD included so that a detached
    # HEAD is not a case of its own, deduplicated so that a checked-out branch
    # is not listed twice.
    candidates = _dedup([head_sha, *(sha for sha, _ in named)])
    unpushed: set[str] = set()
    if candidates:
        reachable = await _git(workspace, repo, "rev-list", *candidates, "--not", "--remotes")
        unpushed = set(reachable.stdout.split())

    files = tuple(line.rstrip() for line in status.stdout.splitlines() if line.strip())
    if not unpushed and not files:
        return None

    # HEAD is a parent whenever it exists, even when it is fully pushed: it is
    # what makes an uncommitted-changes-only snapshot diffable against the
    # branch it came from.
    return _UnsavedWork(
        branch=_branch_name(head_sha, named),
        commit_count=len(unpushed),
        files=files,
        parents=_dedup([head_sha, *(sha for sha, _ in named if sha in unpushed)]),
    )


async def _quarantine(
    workspace: GitWorkspace,
    repo: str,
    work: _UnsavedWork,
    *,
    ref: str,
) -> QuarantinedWork:
    """Push ``work`` to ``ref`` in ``repo`` and report where it landed.

    A plain push, never a force: the ref is unique to this phase run, so the
    only thing that could already occupy it is a writer nobody predicted, and
    overwriting that would trade one silent loss for another.
    """
    await workspace.execute(["rm", "-f", _SCRATCH_INDEX])
    await _git(workspace, repo, "add", "--all", index=_SCRATCH_INDEX)
    tree = (await _git(workspace, repo, "write-tree", index=_SCRATCH_INDEX)).stdout.strip()
    parents = [arg for sha in work.parents for arg in ("-p", sha)]
    commit = await _git(
        workspace,
        repo,
        "commit-tree",
        tree,
        *parents,
        "-m",
        _commit_message(ref),
        identity=True,
    )
    pushed = await _git(workspace, repo, "push", "origin", f"{commit.stdout.strip()}:{ref}")

    name = repo.rsplit("/", 1)[-1]
    if pushed.exit_code != 0:
        logger.error("Quarantine push failed for %s -> %s: %s", repo, ref, pushed.stderr)
        return QuarantinedWork(
            repo=name,
            branch=work.branch,
            commit_count=work.commit_count,
            files=work.files,
            pushed_ref=None,
            push_error=(pushed.stderr or pushed.stdout).strip() or "push exited non-zero",
        )
    logger.warning("Quarantined unpushed work from %s at %s", repo, ref)
    return QuarantinedWork(
        repo=name,
        branch=work.branch,
        commit_count=work.commit_count,
        files=work.files,
        pushed_ref=ref,
    )


def _commit_message(ref: str) -> str:
    return (
        f"syn: quarantined work that would have been lost ({ref})\n\n"
        "The phase that produced this ended without pushing it, and its "
        "workspace was about to be destroyed. This commit's tree is the "
        "working tree as it stood; its parents are the local tips carrying "
        "commits the remote did not have.\n"
    )


def _branch_name(head_sha: str, named: list[tuple[str, str]]) -> str:
    """The checked-out branch, or a readable stand-in when HEAD is not on one."""
    if not head_sha:
        return "(no commits)"
    for sha, name in named:
        if sha == head_sha:
            return name
    return "(detached HEAD)"


def _dedup(shas: list[str]) -> tuple[str, ...]:
    """Non-empty SHAs, first occurrence wins, order preserved."""
    return tuple(dict.fromkeys(sha for sha in shas if sha))


async def _git(
    workspace: GitWorkspace,
    repo: str,
    *args: str,
    index: str | None = None,
    identity: bool = False,
) -> ExecutionResult:
    """Run one git command in ``repo``.

    Environment is carried in argv via ``env`` rather than through the
    execute() port's environment channel, so the command is self-contained and
    behaves identically on any backend that can merely run a process.
    """
    prefix: list[str] = []
    if index is not None:
        prefix.append(f"GIT_INDEX_FILE={index}")
    if identity:
        prefix.extend(_IDENTITY)
    env = ["env", *prefix] if prefix else []
    return await workspace.execute([*env, "git", "-C", repo, *args])
