"""What a phase's workspace is holding, asked while it is still alive.

TWO QUESTIONS, ONE WINDOW, one place that knows how to ask git anything in a
live workspace. `refuse_to_complete_unsaved_phase` asks "would anything here be
lost" before a phase is allowed to complete (#1184). `where_the_work_went` asks
the opposite question on the opposite path - "what did it already push" - while
a phase is failing (#1200), because a phase that pushed and then failed the
#1167 output contract leaves finished work on a branch that nothing points at.
Both run in the same narrow window before teardown, and both are wrong in the
same way if they read an unanswered command as an answer, which is why they
share `_checked` rather than being two modules that each own half a git.


THE GATE (#1184). Every phase runs in an ephemeral workspace that is destroyed
when the phase ends. Until this gate existed, nothing checked that the phase had
pushed: the
instruction lived in a prompt, and a phase that committed without pushing still
reported ``completed`` while its commits went into the bin with the container.

Called once per phase, immediately before the phase is declared complete and
while the workspace - and the git credential the setup phase deliberately
leaves in place - is still alive. It answers one question, "would anything in
this workspace fail to survive it", and if so puts that work somewhere durable
before raising. Callers need nothing but that: no git, no ref naming, no
knowledge of how many repositories a workspace holds.

EVERY COMMAND IS CHECKED, and that is load-bearing rather than tidy. An
unreachable container does not raise - the Docker backend RETURNS a non-zero
result with empty stdout, which is byte-for-byte what a clean workspace
returns. Reading stdout without reading the result therefore turned "I could
not look" into "I looked and it was fine", which is #1184 itself happening
inside the gate against it. ``_checked`` is the single point where a result
becomes readable output, so the discipline holds for commands nobody has
written yet.

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

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PushedWork,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    FailedWorkspaceCommand,
    QuarantinedWork,
    StrandedWork,
    UnpushedWorkQuarantinedError,
    WorkspaceInspectionFailedError,
)
from syn_shared.workspace_paths import WORKSPACE_REPOS_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
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


async def refuse_to_complete_unsaved_phase(
    workspaces: Mapping[str, GitWorkspace],
    todo: TodoItem,
) -> None:
    """Refuse to complete a phase that is holding work its teardown would erase.

    MUST be called before the aggregate is told the phase completed and before
    the phase's workspace context manager is exited. That window is the whole
    point: it is the last moment at which the work still exists to be saved,
    and the last at which refusing leaves the phase indistinguishable, to every
    path downstream, from any other phase failure (#1184). Called after either,
    the guard can still detect the loss but can no longer prevent it.

    The caller hands over the live workspace map and the to-do item and needs
    to know nothing else - which workspace belongs to the phase, and what an
    absent one means, are decided here. ABSENCE IS NOT A FAILURE, and that is a
    verdict rather than an oversight: a phase with no workspace is holding
    nothing that dying could erase, so there is nothing to save and nothing to
    refuse. Contrast a workspace that is present but will not answer, which
    `quarantine_unpushed_work` treats as the failure it is.

    Raises:
        UnpushedWorkQuarantinedError: as `quarantine_unpushed_work`.
        WorkspaceInspectionFailedError: as `quarantine_unpushed_work`.
    """
    phase_id = todo.phase_id
    workspace = workspaces.get(phase_id) if phase_id is not None else None
    if phase_id is None or workspace is None:
        return
    await quarantine_unpushed_work(workspace, execution_id=todo.execution_id, phase_id=phase_id)


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
    here means "nothing is being lost", and - because every command it relies
    on is checked - never "nothing was checked".

    Raises:
        UnpushedWorkQuarantinedError: work was found. It has already been
            pushed to ``refs/syn/lost/<execution-id>/<phase-id>`` in each
            affected repository, and the error names those refs.
        WorkspaceInspectionFailedError: a command this gate depends on did not
            run, so there is no verdict to give for the repositories it had
            not reached yet. Every repository it HAD finished with is named in
            the error, each said to be recoverable or not according to whether
            its push landed: work saved before the failure is not unsaved by
            it, and work whose push failed is not saved by being listed.
    """
    ref = f"{_QUARANTINE_NAMESPACE}/{execution_id}/{phase_id}"
    quarantined: list[QuarantinedWork] = []
    try:
        for repo in await _repositories(workspace):
            work = await _unsaved_work(workspace, repo)
            if work is not None:
                quarantined.append(await _quarantine(workspace, repo, work, ref=ref))
    except WorkspaceInspectionFailedError as unreadable:
        # PARTIAL PROGRESS IS STILL PROGRESS, and this loop is the only place
        # that knows there was any. Repositories are done ONE AT A TIME, so by
        # the time the third one stops answering, the first two's quarantine
        # refs have already been pushed and are durable in their origins.
        # Re-raised carrying them because the bare "NOTHING WAS QUARANTINED"
        # the error would otherwise print is, in that case, false in the one
        # direction that costs the work: an operator told nothing was saved
        # does not go looking for a ref that exists. That is #1184 itself -
        # a confident statement nobody checked - pointing the other way.
        #
        # HANDED OVER UNFILTERED, including the records whose push failed.
        # Those name work that is gone, and dropping them would hide a loss;
        # keeping them is only safe because the error counts pushed_ref rather
        # than records, so a list of failed pushes cannot become a claim that
        # something survived. Empty when the first repository is the one that
        # failed, or when everything before it was clean.
        raise WorkspaceInspectionFailedError(
            doing=unreadable.doing,
            failure=unreadable.failure,
            quarantined=tuple(quarantined),
        ) from unreadable
    if quarantined:
        raise UnpushedWorkQuarantinedError(phase_id=phase_id, quarantined=tuple(quarantined))


async def where_the_work_went(
    workspaces: Mapping[str, GitWorkspace],
    phase_id: str | None,
) -> StrandedWork | None:
    """What a FAILING phase already put on a remote, or None when nobody looked.

    MUST be called while the failing phase's workspace is still alive - the
    same window `refuse_to_complete_unsaved_phase` needs, for the same reason:
    once teardown has run, the branch a phase pushed is a fact nothing in this
    process can still discover. A phase that pushed its work and then failed
    the #1167 output-artifact contract has complete, reviewed-by-nobody commits
    on a branch, and until #1200 the failure record said only that the
    contract was unmet (#1200).

    NEVER RAISES, and that is the whole of its contract to the failure path.
    It is called while an execution is already dying, and an inspection that
    threw would replace the reason the phase failed with the reason the
    inspection failed - a strictly worse error, about a different subject. A
    workspace that stops answering becomes `StrandedWork.unreadable`, which
    reports the absence of a verdict rather than a verdict of "nothing".

    Returns:
        Where the work is, or None when there was no workspace for this phase
        to look in - a failure between phases, or before provisioning. None is
        "nobody looked", never "nothing was pushed"; the two are different
        incidents and stay different all the way to the API.
    """
    workspace = workspaces.get(phase_id) if phase_id is not None else None
    if workspace is None:
        return None

    pushed: list[PushedWork] = []
    try:
        for repo in await _repositories(workspace):
            found = await _pushed_tip(workspace, repo)
            if found is not None:
                pushed.append(found)
    except WorkspaceInspectionFailedError as unreadable:
        # Partial progress is kept for the same reason the quarantine loop keeps
        # it: every record already built names a ref that was found to exist,
        # and a command failing later does not unmake it. What the records
        # cannot do is stand in for the repositories never reached, so the
        # reason is carried beside them rather than being logged and dropped.
        logger.warning("Could not finish looking for pushed work: %s", unreadable.summary)
        return StrandedWork(pushed=tuple(pushed), unreadable=unreadable.summary)
    return StrandedWork(pushed=tuple(pushed))


async def _pushed_tip(workspace: GitWorkspace, repo: str) -> PushedWork | None:
    """This repository's HEAD if a remote has it, else None.

    THE QUESTION IS ASKED OF THE REFS, NOT OF THE BRANCH NAME. "The phase was
    on branch X" is true of work that never left the container, so the claim
    comes from `git branch --remotes --contains`: a remote-tracking ref that
    contains this exact commit. No such ref, no record - the caller reports
    nothing rather than a location an operator would fetch and not find.

    Remote-tracking refs are the same basis `_unsaved_work` uses for the
    inverse question, and they are exact for the case that matters: a push from
    this clone updates them as it lands, so a ref here means a push here
    succeeded. They are a cache of the remote, not the remote, so a branch
    someone else deleted meanwhile would still be named; that error direction
    costs a fetch, and the opposite one costs the work.

    KNOWN LIMIT: it reports HEAD or nothing. A phase that pushed, committed
    again, and then failed has commits this will not mention - they are
    genuinely unrecoverable, and #1184's quarantine is what saves that shape of
    work on the completion path.
    """
    head = (await _git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip()
    if not head:
        return None
    containing = await _git(
        workspace, repo, "branch", "--remotes", "--contains", head, "--format=%(refname:short)"
    )
    on_remote = _remote_branch_names(containing)
    if not on_remote:
        return None
    # The branch the phase checked out is the one a PR would be opened from, so
    # it is the name to print when a remote has it. Several remote branches can
    # contain one commit (a branch that is also main's tip, a fork's copy), and
    # the fallback is sorted rather than first-seen so the report does not
    # depend on git's listing order.
    local = (await _git(workspace, repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    branch = local if local in on_remote else on_remote[0]
    return PushedWork(repo=repo.rsplit("/", 1)[-1], branch=branch, commit=head)


def _remote_branch_names(refs: str) -> list[str]:
    """Fetchable branch names from `refname:short` lines, remote prefix removed.

    `origin/fix/x` is printed as `fix/x` because that is what an operator types
    to fetch it. `origin/HEAD` is dropped: it is the remote's symbolic default
    and names no branch of this phase's.
    """
    names = set()
    for line in refs.splitlines():
        ref = line.strip()
        _, _, branch = ref.partition("/")
        if branch and not branch.endswith("HEAD"):
            names.add(branch)
    return sorted(names)


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

    Empty means the execution was configured with no repositories - a real and
    common case, so it stays a success. It can only mean that because the
    search itself is checked: ``/workspace/repos`` is created by the image and
    again by the entrypoint, so on any workspace that answers at all this find
    exits 0 whether or not it matched anything, and a non-zero one is the
    workspace declining to answer rather than an answer of "nothing here".
    """
    found = await _checked(
        workspace,
        ["find", str(WORKSPACE_REPOS_DIR), "-mindepth", "2", "-maxdepth", "2", "-name", ".git"],
        doing=f"listing the repositories under {WORKSPACE_REPOS_DIR}",
    )
    suffix = "/.git"
    return sorted(line.strip()[: -len(suffix)] for line in found.splitlines() if line.strip())


async def _unsaved_work(workspace: GitWorkspace, repo: str) -> _UnsavedWork | None:
    """What this repository holds that the remote does not, or None if nothing."""
    status = await _git(workspace, repo, "status", "--porcelain")
    tips = await _git(
        workspace, repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"
    )
    # --revs-only, NOT --quiet --verify. Both print the sha and print nothing
    # when the repository has no commits yet, but --verify makes "no commits"
    # an exit 1 - indistinguishable from the workspace being unreachable, which
    # is the exact ambiguity this module refuses to live with. --revs-only
    # answers the empty repository with exit 0 and empty output, so the case
    # stops existing rather than being handled.
    head = await _git(workspace, repo, "rev-parse", "--revs-only", "HEAD")

    named: list[tuple[str, str]] = [
        (sha, name) for sha, _, name in (line.partition(" ") for line in tips.splitlines()) if sha
    ]
    head_sha = head.strip()
    # Every tip that could be carrying work, HEAD included so that a detached
    # HEAD is not a case of its own, deduplicated so that a checked-out branch
    # is not listed twice.
    candidates = _dedup([head_sha, *(sha for sha, _ in named)])
    unpushed: set[str] = set()
    if candidates:
        reachable = await _git(workspace, repo, "rev-list", *candidates, "--not", "--remotes")
        unpushed = set(reachable.split())

    files = tuple(line.rstrip() for line in status.splitlines() if line.strip())
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

    Only the push may fail and still return. Everything before it - clearing
    the scratch index, staging, writing the tree, writing the commit - is
    checked and raises, because a QuarantinedWork built on top of a command
    that did not run would report work as quarantined that was never written.
    That is the same false reassurance as a false ``completed``, in a smaller
    costume, so the only failure this reports as data is the one that happens
    after the objects exist.
    """
    await _checked(
        workspace,
        ["rm", "-f", _SCRATCH_INDEX],
        doing=f"clearing the scratch index before quarantining {repo}",
    )
    await _git(workspace, repo, "add", "--all", index=_SCRATCH_INDEX)
    tree = (await _git(workspace, repo, "write-tree", index=_SCRATCH_INDEX)).strip()
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
    pushed = await _push(workspace, repo, commit=commit.strip(), ref=ref)

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


async def _checked(workspace: GitWorkspace, command: list[str], *, doing: str) -> str:
    """Run ``command`` and return its stdout, or raise if it did not succeed.

    THE ONE PLACE a command result becomes something this module reads, and
    therefore the one place that decides a result can be trusted. The check
    lives here rather than in each caller on purpose: this gate is nothing but
    a sequence of commands whose stdout it parses, and a caller that forgot to
    check would silently read "" as "clean" - which is exactly the defect this
    guard exists to stop, turned inward. Add a command, get the check.

    Success is all three of exit 0, ``success``, and not timing out. A backend
    that sets only one of the first two should not slip through on the other,
    and a command that was killed part-way printed a prefix of an answer, not
    an answer.

    Returns:
        stdout. Never the ExecutionResult - handing that back would put the
        unchecked value in reach again.

    Raises:
        WorkspaceInspectionFailedError: the command failed, so it produced no
            verdict and this module refuses to invent one.
    """
    result = await workspace.execute(command)
    if result.success and result.exit_code == 0 and not result.timed_out:
        return result.stdout
    raise WorkspaceInspectionFailedError(
        doing=doing,
        failure=FailedWorkspaceCommand(
            command=tuple(command),
            exit_code=result.exit_code,
            stderr=result.stderr,
            timed_out=result.timed_out,
        ),
    )


def _git_argv(repo: str, *args: str, index: str | None = None, identity: bool = False) -> list[str]:
    """Argv for one git command in ``repo``.

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
    return [*env, "git", "-C", repo, *args]


async def _git(
    workspace: GitWorkspace,
    repo: str,
    *args: str,
    index: str | None = None,
    identity: bool = False,
) -> str:
    """Stdout of one git command in ``repo``, or raise if it failed."""
    return await _checked(
        workspace,
        _git_argv(repo, *args, index=index, identity=identity),
        doing=f"running 'git {args[0]}' in {repo}",
    )


async def _push(workspace: GitWorkspace, repo: str, *, commit: str, ref: str) -> ExecutionResult:
    """The one command whose failure is an answer rather than the lack of one.

    A push can fail for reasons that say nothing about whether the workspace
    is reachable - no credential, no network, the remote rejecting the ref -
    and by the time it runs the quarantine commit already exists locally. So
    its result is returned rather than raised on, and the caller reports the
    work as NOT recoverable. Every other command here goes through _checked.
    """
    return await workspace.execute(_git_argv(repo, "push", "origin", f"{commit}:{ref}"))
