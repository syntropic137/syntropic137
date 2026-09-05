"""What a phase's workspace is holding, asked while it is still alive.

TWO QUESTIONS, ONE WINDOW, one place that knows how to ask git anything in a
live workspace. `refuse_to_complete_unsaved_phase` asks "would anything here be
lost" before a phase is allowed to complete (#1184). `observe_branches` asks
the opposite question on the opposite path - "where do this workspace's
branches stand" - while a phase is failing (#1200), because a phase that
pushed and then failed the #1167 output contract leaves finished work on a
branch that nothing points at. Both run in the same narrow window before
teardown, and both are wrong in the same way if they read an unanswered
command as an answer, which is why they share `_checked` rather than being two
modules that each own half a git.

WHERE A BRANCH STANDS IS A QUESTION ABOUT TWO MOMENTS, so the failing half
needs a second call: `record_phase_starting_point` runs when the workspace is
provisioned and records where each remote-tracking ref pointed then. Without
it the only question git can answer is "is HEAD on a remote", which is TRUE
for a phase that did nothing at all - it inherits a branch someone else
already pushed - and answering it offered the inherited commit as somewhere to
go and look. The comparison is what makes "this ref is not where the phase
found it" sayable at all.

WHAT THE COMPARISON IS NOT is a claim about who moved the ref. Two earlier
versions of this reported "work THIS PHASE pushed", derived from exactly this
snapshot-then-diff: anything new relative to the snapshot was called the
phase's own. A concurrent process pushing to the same branch, or a person,
produces the identical evidence, because GIT DOES NOT RECORD WHO PUSHED A
COMMIT. So the two readings are reported as two readings and the reader draws
their own conclusion. An operator needs to know where to look; that never
required knowing whose push it was.


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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    FailedWorkspaceCommand,
    ObservedBranches,
    QuarantinedWork,
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


@dataclass(frozen=True)
class PhaseStartingPoint:
    """Where a phase's remote-tracking refs pointed before the phase ran.

    THE HALF OF "WHERE DOES THIS BRANCH STAND" THAT GIT CANNOT ANSWER LATER.
    At failure time a ref is just a ref: `origin/fix/x` at some commit says
    nothing about whether it is where the workspace found it. Only a reading
    taken BEFORE the phase ran makes "this is not where it was" sayable, so
    one is taken and carried.

    `remote_refs` maps each repository's path in the workspace to that
    repository's remote-tracking refs, short name (`origin/main`) to commit.
    Remote refs only: what is on a remote is what an operator can still fetch
    after the container is gone, and a local ref that moved is #1184's subject
    rather than this one's. A repository absent from the map had none, which
    falls out of `remote_refs_for` returning nothing rather than being a case
    anyone handles.

    IT IS NOT EVIDENCE OF AUTHORSHIP and must never be read as any. A ref that
    differs from its snapshot moved; nothing here says whose push moved it,
    and no report built from this is entitled to say so.

    `unreadable` says the snapshot itself could not be taken, and is why this
    is recorded rather than merely attempted: a phase whose starting point is
    unknown has no comparison available at failure time, and reporting
    "nothing changed" from a comparison nobody made is the substitution #1184
    took four review passes to remove from its own reporting. It reports the
    absence of a verdict instead.

    The workspace is carried with it because the two are only ever useful
    together: a starting point from one phase and a workspace from another
    would produce a confident, wrong answer, and holding them in one value
    makes that pairing unrepresentable.
    """

    workspace: GitWorkspace
    remote_refs: Mapping[str, Mapping[str, str]]
    unreadable: str | None = None

    def remote_refs_for(self, repo: str, branch: str) -> Mapping[str, str]:
        """Remote name -> where its copy of ``branch`` pointed at phase start."""
        return _by_remote(branch, self.remote_refs.get(repo, {}))


async def record_phase_starting_point(workspace: GitWorkspace) -> PhaseStartingPoint:
    """Read where this workspace's remotes point, before its phase is allowed to run.

    MUST be called once the workspace is provisioned and BEFORE the agent
    starts, because that is the only moment at which "where was this ref" is
    still a fact anyone can read. Cheap enough to pay on every phase - one git
    command per repository, once - and there is no way to pay it only on the
    phases that will later turn out to fail.

    NEVER RAISES, for the same reason `observe_branches` never does, one path
    earlier: this runs on the SUCCESS path of every phase, and a snapshot that
    threw would fail a phase doing nothing wrong in order to protect a report
    that only matters if it fails for some other reason. A workspace that will
    not answer becomes a starting point that says so.
    """
    try:
        return PhaseStartingPoint(
            workspace=workspace,
            remote_refs={
                repo: await _remote_refs(workspace, repo) for repo in await _repositories(workspace)
            },
        )
    except WorkspaceInspectionFailedError as unreadable:
        logger.warning("Could not record where this phase started: %s", unreadable.summary)
        return PhaseStartingPoint(
            workspace=workspace, remote_refs={}, unreadable=unreadable.summary
        )


async def _remote_refs(workspace: GitWorkspace, repo: str) -> Mapping[str, str]:
    """This repository's remote-tracking refs, short name to commit.

    `origin/HEAD` is dropped because it is the remote's symbolic default and
    names no branch of anyone's. Dropping it is also what makes a detached
    HEAD - which `rev-parse --abbrev-ref` reports as the literal "HEAD" -
    match nothing, rather than matching the remote's default branch.
    """
    listing = await _git(
        workspace, repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/remotes"
    )
    return {
        ref: sha
        for sha, _, ref in (line.strip().partition(" ") for line in listing.splitlines())
        if sha and ref and not ref.endswith("/HEAD")
    }


def _by_remote(branch: str, refs: Mapping[str, str]) -> dict[str, str]:
    """Of ``refs``, the ones that are ``branch`` on some remote, keyed by remote.

    The counterpart of local `fix/x` is `<remote>/fix/x`: the first path
    component is the remote and the rest is the branch, so `origin/other/fix/x`
    is a different branch and not a match. Keyed by remote so that a workspace
    with two remotes carrying one branch name describes both rather than
    picking one by a rule nobody can see.
    """
    return {
        ref.partition("/")[0]: sha for ref, sha in refs.items() if ref.partition("/")[2] == branch
    }


async def observe_branches(
    starting_points: Mapping[str, PhaseStartingPoint],
    phase_id: str | None,
) -> ObservedBranches | None:
    """Where a FAILING phase's branches stand, or None when nobody looked.

    MUST be called while the failing phase's workspace is still alive - the
    same window `refuse_to_complete_unsaved_phase` needs, for the same reason:
    once teardown has run, where a branch stood is a fact nothing in this
    process can still discover. A phase that pushed its work and then failed
    the #1167 output-artifact contract has complete, reviewed-by-nobody commits
    on a branch, and until #1200 the failure record said only that the contract
    was unmet.

    OBSERVATIONS, NEVER ATTRIBUTIONS. Each record says where a remote branch
    is, where it was when the phase started, and how many local commits no
    remote holds. It does NOT say the phase pushed anything, because git
    cannot support that: the snapshot-and-diff that would be the only evidence
    is produced identically by a concurrent push. What it CAN support is
    everything the operator needs - which branch, which commit, and whether
    that is where the workspace found it.

    A REPOSITORY NOBODY TOUCHED PRODUCES NO RECORD, and that is the difference
    between the two empty outcomes staying visible. Silence means the remote
    branch is where the phase found it and nothing local is off a remote;
    recording it anyway would hand every failure a location, including the
    phase that did nothing, whose branch was already pushed before it started.

    NEVER RAISES, and that is the whole of its contract to the failure path. It
    is called while an execution is already dying, and an inspection that threw
    would replace the reason the phase failed with the reason the inspection
    failed - a strictly worse error, about a different subject. A workspace
    that stops answering becomes `ObservedBranches.unreadable`, which reports
    the absence of a verdict rather than a verdict of "nothing changed".

    Returns:
        Where the branches stand, or None when no starting point was recorded
        for this phase - a failure between phases, or before provisioning. None
        is "nobody looked", never "nothing changed"; the two are different
        incidents and stay different all the way to the API.
    """
    start = starting_points.get(phase_id) if phase_id is not None else None
    if start is None:
        return None
    if start.unreadable is not None:
        # No snapshot, so no ref can be compared with where it was - and "no
        # comparison was possible" must not be printed as "nothing changed".
        # The workspace may well hold a branch an operator wants; what is
        # missing is any reading of where it started.
        return ObservedBranches(branches=(), unreadable=start.unreadable)

    observed: list[BranchObservation] = []
    try:
        for repo in await _repositories(start.workspace):
            observed.extend(await _branch_state(start, repo))
    except WorkspaceInspectionFailedError as unreadable:
        # Partial progress is kept for the same reason the quarantine loop keeps
        # it: every record already built is a reading that was taken, and a
        # command failing later does not unmake it. What the records cannot do
        # is stand in for the repositories never reached, so the reason is
        # carried beside them rather than being logged and dropped.
        logger.warning("Could not finish reading this workspace's branches: %s", unreadable.summary)
        return ObservedBranches(branches=tuple(observed), unreadable=unreadable.summary)
    return ObservedBranches(branches=tuple(observed))


async def _branch_state(start: PhaseStartingPoint, repo: str) -> list[BranchObservation]:
    """How ``repo``'s checked-out branch stands now against how it started.

    ONE RECORD PER REMOTE CARRYING THE BRANCH, over the union of the remotes
    that carry it now and those that carried it at phase start. The union is
    what makes "the ref was deleted while the phase ran" an ordinary reading
    rather than a case: it appears as a ref that had a commit and now has
    none. A branch on no remote at either moment still gets one record, with
    no remote named, because its unpushed count is worth saying.

    THE CHECKED-OUT BRANCH ONLY. A phase that fetches while another PR merges
    moves `origin/main` too, and reporting that would put someone else's merge
    in this phase's failure record. The branch the workspace is on is the one
    a PR would come from and the only one worth naming.

    EVERY RECORD IS FILTERED BY `is_worth_recording`, so a repository whose
    remote branch is where the phase found it and whose HEAD is fully pushed
    contributes nothing. That filter is the difference between "this phase
    left nothing anywhere" and "here is the commit it inherited".
    """
    workspace = start.workspace
    # --revs-only first, for the reason `_unsaved_work` gives: a repository
    # with no commits answers it with exit 0 and empty output, where
    # `--abbrev-ref HEAD` would exit non-zero and be indistinguishable from an
    # unreachable workspace. Nothing observable on a branch that does not exist.
    if not (await _git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip():
        return []

    branch = (await _git(workspace, repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    now = _by_remote(branch, await _remote_refs(workspace, repo))
    before = start.remote_refs_for(repo, branch)
    # The same `--not --remotes` question `_unsaved_work` asks: what this
    # workspace holds that no remote does, and so what dying would erase.
    unpushed = len((await _git(workspace, repo, "rev-list", "HEAD", "--not", "--remotes")).split())

    name = repo.rsplit("/", 1)[-1]
    # `or [None]` rather than an if: a branch on no remote is still one
    # observation, so the loop covers it instead of a case after it.
    observed = [
        BranchObservation(
            repo=name,
            branch=_displayed(branch),
            remote=remote,
            remote_commit=now.get(remote) if remote else None,
            remote_commit_at_phase_start=before.get(remote) if remote else None,
            unpushed_commits=unpushed,
        )
        for remote in sorted(now.keys() | before.keys()) or [None]
    ]
    return [record for record in observed if record.is_worth_recording]


def _displayed(branch: str) -> str:
    """The branch as a reader should see it named.

    `rev-parse --abbrev-ref HEAD` says the literal "HEAD" when HEAD is
    detached, and "branch HEAD" reads as a branch someone named HEAD. Only the
    display is changed: the matching above uses the raw name, which matches no
    remote ref because `*/HEAD` is dropped when they are read.
    """
    return "(detached HEAD)" if branch == "HEAD" else branch


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
