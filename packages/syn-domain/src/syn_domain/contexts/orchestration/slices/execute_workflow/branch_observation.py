"""Where a workspace's branches stand, against where the phase found them.

THE OPPOSITE QUESTION TO THE GUARD'S, ASKED IN THE SAME WINDOW (#1200).
`unpushed_work_guard` asks "would anything here be lost"; this asks "where does
what is already pushed now live". A phase that pushed and then failed the #1167
output contract leaves finished work on a branch that nothing points at, and
until this existed the failure record said only that the contract was unmet.
Both run before teardown and both go through `workspace_git`, which is where
the rule that an unanswered command is not an answer is kept for both of them.

IT IS A QUESTION ABOUT TWO MOMENTS, which is why there is a second call on the
success path. `record_phase_starting_point` runs when the workspace is
provisioned and records where each remote-tracking ref pointed then. Without it
the only question git can answer is "is HEAD on a remote", which is TRUE for a
phase that did nothing at all - it inherits a branch someone else already
pushed - and answering it offered the inherited commit as somewhere to go and
look. The comparison is what makes "this ref is not where the phase found it"
sayable at all.

ONE HALF OF THAT COMPARISON IS A CACHE AND THE OTHER IS NOT, deliberately.
Where a branch WAS is `refs/remotes` as the phase was handed it, which is the
definition of where the phase found it. Where a branch IS NOW is asked of the
remote over the network, because `refs/remotes` only ever says what this clone
was last told, and a phase that never fetched was last told something that may
predate everything the report is about.

WHAT THE COMPARISON IS NOT is a claim about who moved the ref. Two earlier
versions of this reported "work THIS PHASE pushed", derived from exactly this
snapshot-then-diff: anything new relative to the snapshot was called the
phase's own. A concurrent process pushing to the same branch, or a person,
produces the identical evidence, because GIT DOES NOT RECORD WHO PUSHED A
COMMIT. So the two readings are reported as two readings and the reader draws
their own conclusion. An operator needs to know where to look; that never
required knowing whose push it was.

NOTHING HERE RAISES, on either path, and that is the whole of this module's
contract to its callers. `record_phase_starting_point` runs on the success path
of every phase; `observe_branches` runs on a phase that is already dying. In
both cases an inspection that threw would replace a real outcome with the
inspection's own failure. A workspace that stops answering becomes a recorded
absence of a verdict, never a verdict of "nothing changed".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ObservedBranches,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    GitWorkspace,
    git,
    git_remote,
    repositories,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


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
                repo: await _cached_remote_refs(workspace, repo)
                for repo in await repositories(workspace)
            },
        )
    except WorkspaceInspectionFailedError as unreadable:
        logger.warning("Could not record where this phase started: %s", unreadable.summary)
        return PhaseStartingPoint(
            workspace=workspace, remote_refs={}, unreadable=unreadable.summary
        )


class PhaseStartingPoints:
    """The starting points of the phases currently holding a workspace.

    ONE OBJECT SO THE PROCESSOR NEVER HOLDS HALF THE INVARIANT. Reading where
    a phase's branches stand needs two readings taken at two moments in two
    different methods of a long-lived processor - taken at provision, read at
    failure, dropped at teardown - and every one of those is a chance to keep
    a snapshot one beat too long or throw it away one beat too early. Wiring
    that from the call sites meant the processor knew there was a map, what
    was in it, and which of the four moments it was in; none of that is
    anything the processor decides. It says which phase was handed which
    workspace and asks where that phase's branches stand.

    WHY IT IS READ AT PROVISION AND NOT AT FAILURE (#1200): at failure time a
    ref is just a ref. `origin/fix/x` at some commit says nothing about
    whether it is where the workspace found it, so a reading taken before the
    phase ran is the only thing that makes "this is not where it was" sayable
    at all. `record` is therefore called on the success path of every phase,
    including the overwhelming majority that never fail, and there is no way
    to pay it only on the ones that will.

    A STARTING POINT LIVES EXACTLY AS LONG AS THE WORKSPACE IT DESCRIBES.
    `PhaseStartingPoint` carries its own workspace precisely because the two
    are only ever useful as a pair, and one that outlived its container could
    only ever be paired with the wrong one. `forget` and `forget_all` are the
    two ways a workspace goes away - one phase finishing, and an execution
    dying with several still open - and they exist so that pairing stays
    unrepresentable rather than merely unlikely.

    NOTHING HERE RAISES on either path. `record` runs on phases that are
    fine, and `observe` runs on a phase that is already dying; in both cases
    an inspection that threw would replace a real outcome with the inspection's
    own failure. A workspace that stops answering becomes a recorded absence
    of a verdict, never a verdict of "nothing changed".
    """

    def __init__(self) -> None:
        self._by_phase: dict[str, PhaseStartingPoint] = {}

    async def record(self, phase_id: str, workspace: GitWorkspace) -> None:
        """Take this phase's starting point, before its agent is allowed to run."""
        self._by_phase[phase_id] = await record_phase_starting_point(workspace)

    async def observe(self, phase_id: str | None) -> ObservedBranches | None:
        """Where a failing phase's branches stand, or None when nobody looked.

        MUST be called while the phase's workspace is still alive: once
        teardown has run, where a branch stood is a fact nothing in this
        process can still discover.

        The lookup happens before the first await, so a concurrent teardown
        cannot empty the map out from under a reading that has already begun -
        the same discipline the caller applies to its own per-phase maps, kept
        here because this is where the map is.
        """
        return await observe_branches(self._by_phase, phase_id)

    def forget(self, phase_id: str) -> None:
        """Drop one phase's starting point, as its workspace is closed."""
        self._by_phase.pop(phase_id, None)

    def forget_all(self) -> None:
        """Drop every starting point, as a terminal path closes all workspaces."""
        self._by_phase.clear()


async def _cached_remote_refs(workspace: GitWorkspace, repo: str) -> Mapping[str, str]:
    """What this clone last HEARD its remotes say, short name to commit.

    `refs/remotes/*` is a cache and the name says so. It advances when THIS
    clone fetches or pushes, and never because a remote advanced, so reading
    it answers "what was this clone last told" and not "where is the branch".
    Only `record_phase_starting_point` may use it, and only because at that
    moment the two coincide: the workspace has just been cloned, and "where
    the phase FOUND the ref" is by definition the reading the phase was handed.
    Asking where a branch is NOW goes to `_remote_tips`, which asks the remote.

    `origin/HEAD` is dropped because it is the remote's symbolic default and
    names no branch of anyone's. Dropping it is also what makes a detached
    HEAD - which `rev-parse --abbrev-ref` reports as the literal "HEAD" -
    match nothing, rather than matching the remote's default branch.
    """
    listing = await git(
        workspace, repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/remotes"
    )
    return {
        ref: sha
        for sha, _, ref in (line.strip().partition(" ") for line in listing.splitlines())
        if sha and ref and not ref.endswith("/HEAD")
    }


async def _remote_tips(workspace: GitWorkspace, repo: str, branch: str) -> dict[str, str]:
    """Where each of ``repo``'s remotes ACTUALLY holds ``branch``, keyed by remote.

    ASKS THE REMOTE. That is the whole of this function and the reason it is
    not a read of `refs/remotes`, which is what it replaced. A phase that
    commits, pushes and fails updates its own cache, so the cache looked
    right in every fixture; a phase that fails while SOMEONE ELSE pushed the
    same branch never hears about it, and the cache then reports a commit that
    is not where the branch is - offered to an operator as where to look.
    `ls-remote` asks the remote itself and writes nothing on either side.

    A remote missing from the result does not have the branch. A remote that
    could not be REACHED is not in the result either - it raises, because the
    two must never be the same value, and the cached commit must never be
    offered in place of an answer nobody got. That is `checked`'s rule
    applied to the one command here that can fail without the workspace being
    at fault, and the caller reports the absence of a reading rather than
    inventing one.

    Raises:
        WorkspaceInspectionFailedError: a remote did not answer within
            `workspace_git`'s remote bound, or answered with a failure.
    """
    ref = f"refs/heads/{branch}"
    tips: dict[str, str] = {}
    for remote in (await git(workspace, repo, "remote")).split():
        listing = await git_remote(
            workspace,
            repo,
            "ls-remote",
            remote,
            ref,
            doing=f"asking {remote} where {branch} is, in {repo}",
        )
        # Matched on the full refname rather than trusting ls-remote's pattern
        # matching, so `refs/heads/x` can never be answered by some other
        # remote's `refs/heads/team/x`.
        for line in listing.splitlines():
            sha, _, name = line.strip().partition("\t")
            if sha and name == ref:
                tips[remote] = sha
    return tips


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
    same window `unpushed_work_guard.refuse_to_complete_unsaved_phase` needs, for the same reason:
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
        for repo in await repositories(start.workspace):
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

    WHERE IT IS NOW IS ASKED OF THE REMOTE, and where it WAS comes from the
    snapshot. Both readings used to come from `refs/remotes`, which is this
    clone's cache: it advances when this clone fetches or pushes and at no
    other time, so a branch that moved on the remote while the phase held the
    workspace read as one that had not moved at all. `_remote_tips` asks.

    EVERY RECORD IS FILTERED BY `is_worth_recording`, so a repository whose
    remote branch is where the phase found it and whose HEAD is fully pushed
    contributes nothing. That filter is the difference between "this phase
    left nothing anywhere" and "here is the commit it inherited".
    """
    workspace = start.workspace
    # --revs-only first, for the reason `unpushed_work_guard._unsaved_work` gives: a repository
    # with no commits answers it with exit 0 and empty output, where
    # `--abbrev-ref HEAD` would exit non-zero and be indistinguishable from an
    # unreachable workspace. Nothing observable on a branch that does not exist.
    if not (await git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip():
        return []

    branch = (await git(workspace, repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    # THE REMOTE ITSELF, not this clone's cache of it: see `_remote_tips`.
    # `before` is the cache on purpose - it is the reading the phase was
    # handed - so the two halves of the comparison come from different places
    # and each is the right source for the moment it describes.
    now = await _remote_tips(workspace, repo, branch)
    before = start.remote_refs_for(repo, branch)
    # The same `--not --remotes` question `unpushed_work_guard._unsaved_work` asks: what this
    # workspace holds that no remote does, and so what dying would erase.
    unpushed = len((await git(workspace, repo, "rev-list", "HEAD", "--not", "--remotes")).split())

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
