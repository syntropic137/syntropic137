"""What a phase's workspace is holding, asked while it is still alive.

TWO QUESTIONS, ONE WINDOW, one place that knows how to ask git anything in a
live workspace. `refuse_to_complete_unsaved_phase` asks "would anything here be
lost" before a phase is allowed to complete (#1184). `where_the_work_went` asks
the opposite question on the opposite path - "what did THIS PHASE push" - while
a phase is failing (#1200), because a phase that pushed and then failed the
#1167 output contract leaves finished work on a branch that nothing points at.
Both run in the same narrow window before teardown, and both are wrong in the
same way if they read an unanswered command as an answer, which is why they
share `_checked` rather than being two modules that each own half a git.

"WHAT THIS PHASE PUSHED" IS A QUESTION ABOUT TWO MOMENTS, so the failing half
needs a second call: `record_phase_starting_point` runs when the workspace is
provisioned and snapshots what it could already reach. Without it the only
question git can answer is "is HEAD on a remote", which is TRUE for a phase
that did nothing at all - it inherits a branch someone else already pushed -
and answering it reported the inherited commit as the phase's own work. That
is the whole distinction #1200 exists to draw, so the comparison is kept
rather than the shortcut.


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


@dataclass(frozen=True)
class PhaseStartingPoint:
    """What a phase's workspace could already reach before the phase ran.

    THE HALF OF "WHERE DID THIS PHASE'S WORK GO" THAT GIT CANNOT ANSWER LATER.
    At failure time every commit looks alike: a workspace whose branch is on a
    remote looks identical whether this phase pushed it a minute ago or
    inherited it from the clone. Only a reading taken BEFORE the phase ran
    separates them, so one is taken and carried.

    `reachable` holds tips rather than commits - a handful of SHAs standing for
    the whole history behind them - keyed by the repository's path in the
    workspace. A repository absent from it is one that did not exist when the
    phase started, whose every commit is therefore the phase's own; that falls
    out of `already_had` returning nothing rather than being a case anyone
    handles.

    `unreadable` says the snapshot itself could not be taken, and is why this
    is recorded rather than merely attempted: a phase whose starting point is
    unknown has no comparison available at failure time, and reporting "nothing
    was pushed" from a comparison nobody made is the substitution #1184 took
    four review passes to remove from its own reporting. It reports the absence
    of a verdict instead.

    The workspace is carried with it because the two are only ever useful
    together: a starting point from one phase and a workspace from another
    would produce a confident, wrong answer, and holding them in one value
    makes that pairing unrepresentable.
    """

    workspace: GitWorkspace
    reachable: Mapping[str, tuple[str, ...]]
    unreadable: str | None = None

    def already_had(self, repo: str) -> tuple[str, ...]:
        """Tips ``repo`` could reach at phase start; empty if it had none."""
        return self.reachable.get(repo, ())


async def record_phase_starting_point(workspace: GitWorkspace) -> PhaseStartingPoint:
    """Read what this workspace can reach, before its phase is allowed to run.

    MUST be called once the workspace is provisioned and BEFORE the agent
    starts, because that is the only moment at which "what was here already" is
    still a fact anyone can read. Cheap enough to pay on every phase - two git
    commands per repository, once - and there is no way to pay it only on the
    phases that will later turn out to fail.

    NEVER RAISES, for the same reason `where_the_work_went` never does, one
    path earlier: this runs on the SUCCESS path of every phase, and a snapshot
    that threw would fail a phase doing nothing wrong in order to protect a
    report that only matters if it fails for some other reason. A workspace
    that will not answer becomes a starting point that says so.
    """
    try:
        return PhaseStartingPoint(
            workspace=workspace,
            reachable={
                repo: await _already_reachable(workspace, repo)
                for repo in await _repositories(workspace)
            },
        )
    except WorkspaceInspectionFailedError as unreadable:
        logger.warning("Could not record where this phase started: %s", unreadable.summary)
        return PhaseStartingPoint(workspace=workspace, reachable={}, unreadable=unreadable.summary)


async def _already_reachable(workspace: GitWorkspace, repo: str) -> tuple[str, ...]:
    """Every commit this repository can reach right now, named by its tips.

    Tips rather than commits: `rev-list --not <tips>` excludes everything
    behind them, so a handful of SHAs stands in for a history of any length and
    the snapshot costs two commands however old the repository is.

    LOCAL AND REMOTE REFS BOTH, plus HEAD in case it is detached. A phase that
    checks out another branch, fetches, or resets is then still starting from
    what it inherited: anything the workspace could already reach is not
    something the phase produced, whichever ref later points at it.
    """
    tips = await _git(
        workspace, repo, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/remotes"
    )
    head = await _git(workspace, repo, "rev-parse", "--revs-only", "HEAD")
    return _dedup([head.strip(), *tips.split()])


async def where_the_work_went(
    starting_points: Mapping[str, PhaseStartingPoint],
    phase_id: str | None,
) -> StrandedWork | None:
    """What a FAILING phase put on a remote ITSELF, or None when nobody looked.

    MUST be called while the failing phase's workspace is still alive - the
    same window `refuse_to_complete_unsaved_phase` needs, for the same reason:
    once teardown has run, the branch a phase pushed is a fact nothing in this
    process can still discover. A phase that pushed its work and then failed
    the #1167 output-artifact contract has complete, reviewed-by-nobody commits
    on a branch, and until #1200 the failure record said only that the contract
    was unmet (#1200).

    ITSELF is the load-bearing word, and it is what `starting_points` is for.
    Every record here is work that was NOT in the workspace when the phase
    started, so a phase that produced nothing produces no records - rather than
    the branch and commit it was handed, which is a true sentence about git and
    a false answer to the question asked. "It pushed commits but wrote no
    deliverable" and "it produced nothing at all" are a recoverable incident
    and an unrecoverable one; reporting the inherited tip made them the same
    record, which is the whole distinction this exists to draw.

    NEVER RAISES, and that is the whole of its contract to the failure path. It
    is called while an execution is already dying, and an inspection that threw
    would replace the reason the phase failed with the reason the inspection
    failed - a strictly worse error, about a different subject. A workspace
    that stops answering becomes `StrandedWork.unreadable`, which reports the
    absence of a verdict rather than a verdict of "nothing".

    Returns:
        Where the work is, or None when no starting point was recorded for this
        phase - a failure between phases, or before provisioning. None is
        "nobody looked", never "nothing was pushed"; the two are different
        incidents and stay different all the way to the API.
    """
    start = starting_points.get(phase_id) if phase_id is not None else None
    if start is None:
        return None
    if start.unreadable is not None:
        # Nothing to compare against, so nothing can be attributed to the phase
        # - and "nothing could be attributed" must not be printed as "nothing
        # was pushed". The workspace may well hold a good pushed branch; what
        # is missing is any way to tell whether THIS PHASE put it there.
        return StrandedWork(pushed=(), unreadable=start.unreadable)

    pushed: list[PushedWork] = []
    try:
        for repo in await _repositories(start.workspace):
            found = await _work_this_phase_pushed(start, repo)
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


async def _work_this_phase_pushed(start: PhaseStartingPoint, repo: str) -> PushedWork | None:
    """The newest commit THIS PHASE both produced and got onto ``repo``'s remote.

    THREE CONDITIONS, ALL NECESSARY. The commit must be

      reachable from the branch now - it is still part of the work, not
                                      something reset away;
      new since the phase started   - `start` is what the workspace could
                                      already reach, so anything behind it was
                                      inherited and is not this phase's to
                                      claim. Without this a phase that did
                                      NOTHING reported the commit it was handed
                                      as its own output, which is the defect
                                      this function was rewritten to remove;
      on the branch's remote ref    - a commit that never left the container is
                                      #1184's business, not a location. Naming
                                      it would send an operator to fetch
                                      something that is not there.

    THE REMOTE COUNTERPART OF THIS BRANCH, not any remote ref that happens to
    contain the commit. A phase that merges a freshly fetched `origin/main`
    without pushing has made main's commits reachable, and they genuinely are
    on a remote, so "on any remote" would report someone else's commit on
    someone else's branch as this phase's pushed work - the same lie in a
    longer costume. The branch a PR would be opened from is the only one worth
    naming anyway.

    NOT NECESSARILY HEAD. A phase that pushed and then committed again leaves
    HEAD off the remote with the pushed commit behind it; that commit is real,
    fetchable, and exactly what an operator wants, so the newest commit meeting
    all three conditions is reported rather than nothing. The commits after it
    are unpushed work, which is #1184's quarantine to save and not this
    function's to describe.

    KNOWN LIMIT, stated because it is the one shape refs cannot settle: a phase
    that merely FETCHES a branch someone else advanced and fast-forwards onto
    it is indistinguishable from one that pushed those commits itself - both
    move HEAD and the remote-tracking ref to the same new commit, and nothing
    in the ref graph records which of them did it. It is narrow, because a
    merge that is not a fast-forward leaves an unpushed merge commit and so
    fails the third condition, and the only thing that would settle it is a
    reflog - a record of what this clone did locally, not a fact about the
    remote, which is the kind of evidence this module already refuses.
    """
    workspace = start.workspace
    already = start.already_had(repo)
    head = (await _git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip()
    if not head:
        return None
    # Newest first, so the first survivor of the filter below is the tip of
    # whatever this phase got onto the remote.
    produced = (await _git(workspace, repo, "rev-list", head, "--not", *already)).split()
    if not produced:
        return None

    branch = (await _git(workspace, repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    listing = await _git(
        workspace, repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/remotes"
    )
    remote_tips = _remote_tips_of(branch, listing)
    if not remote_tips:
        return None
    # The same `--not --remotes` question `_unsaved_work` asks, narrowed to this
    # branch's remote refs: what the phase produced that they do NOT have.
    unpushed = set(
        (await _git(workspace, repo, "rev-list", head, "--not", *already, *remote_tips)).split()
    )
    tip = next((sha for sha in produced if sha not in unpushed), None)
    if tip is None:
        return None
    return PushedWork(repo=repo.rsplit("/", 1)[-1], branch=branch, commit=tip)


def _remote_tips_of(branch: str, refs: str) -> list[str]:
    """SHAs of the remote-tracking refs for ``branch``, from `for-each-ref` lines.

    The counterpart of local `fix/x` is `<remote>/fix/x`: the first path
    component is the remote and the rest is the branch, so `origin/other/fix/x`
    is a different branch and not a match. Sorted and deduplicated so that a
    workspace with two remotes carrying one branch name answers the same way
    whatever order git listed them in.

    `origin/HEAD` is the remote's symbolic default and names no branch of this
    phase's. Dropping it is also what makes a detached HEAD - which `rev-parse
    --abbrev-ref` reports as the literal "HEAD" - match nothing, rather than
    matching the remote's default branch.
    """
    tips = {
        sha
        for sha, _, ref in (line.strip().partition(" ") for line in refs.splitlines())
        if sha and not ref.endswith("/HEAD") and ref.partition("/")[2] == branch
    }
    return sorted(tips)


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
