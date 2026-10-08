"""Which branch a resumed phase continues, rather than starting over (#1513).

A v3 implement phase opens a draft PR on its first push, so a parent that fails
anywhere after that leaves a pushed branch and an open PR behind. A resume that
starts its implement phase fresh opens a SECOND branch and a second PR for the
same change. This module is the rule that stops that, in three steps, each a
pure function of recorded facts:

1. `branches_left_by` - when a run fails, which branches its failing phase
   left on origin. Read from the `observed_branches` the failure already
   records (#1200), so the fact is on the execution whether or not the phase
   completed.
2. `continuation_candidates` - when a resume is admitted, which of those the
   resumed phase should pick up: the ones its parent's failing phase left,
   when the resumed phase IS that phase.
3. `decide_continuation` - when the child starts, which candidates are still
   where the parent left them on the forge. A branch deleted, force-pushed or
   moved since, or whose PR is no longer the one the parent recorded open, is
   ABANDONED with a recorded reason and the phase starts fresh; nothing stale
   is reused, and nothing is dropped silently.

OWN PUSHES (PC-128). A run orphaned by a deploy records no failure-time
observation, and a fix phase's branch existed before the phase started, so
neither fact above can say the phase left it. What can is `PhaseCommitPushed`:
the commits the phase's own workspace pushed, recorded as it pushed them. A
branch the failing phase pushed to is a candidate, carrying every SHA it
pushed there, and is continued when origin's head is ANY of them - the run's
own unverified commits. A head that is none of them is someone else's push and
is abandoned exactly as before: the identity rule does not change, it just
learns which SHAs are this run's.

THE CHECKOUT RULE (ADR-058, #1458 + #1513). A phase that only READS code is
checked out at the run's pinned start commit. A phase that CONTINUES a branch
is checked out at that branch's head. `checkout_for` is the one place that
says which is which, and it says it per phase: only the resumed phase
continues, because only its own earlier attempt pushed the branch.

The models live here rather than in `value_objects` because that module is
already past the file-size limit; `value_objects` re-exports them so
`WorkflowExecutionStarted` can carry them under the vsa import rule.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation,
    )

logger = logging.getLogger(__name__)

#: The only remote a workspace clones from. A branch on any other remote is
#: not one a resumed workspace could check out.
_ORIGIN = "origin"


class ContinuedBranch(BaseModel):
    """A branch a phase pushed, and the PR open from it, if any (#1513).

    As a CANDIDATE (on the resume command) it is what the parent's failing
    phase left: `head_sha` is where origin had the branch when that phase
    failed, and `pull_request` the PR the forge had open from it then, as the
    failure recorded it. As a DECISION (on the child's start event) the forge
    has confirmed both are still so: the branch at `head_sha`, and that same
    PR open - never another one opened from the branch since.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `owner/name`, the slug `SourceCommit.repository` uses.
    repository: str
    branch: str
    head_sha: str
    pull_request: int | None = None
    #: Every SHA the failing phase itself pushed to this branch, oldest first
    #: (PC-128). Empty for a branch known only from the failure's observation.
    #: As a DECISION, non-empty means `head_sha` is one of them: the run's own
    #: commits, pushed and never verified.
    pushed_shas: list[str] = Field(default_factory=list)

    @property
    def is_own_unverified_push(self) -> bool:
        """Whether the head is a commit this run pushed and nothing verified."""
        return self.head_sha in self.pushed_shas


class PushedCommit(BaseModel):
    """One push a phase's own workspace made to origin, as it made it (PC-128).

    `repository` is the clone's directory name, as the workspace's push hook
    reports it; `branch_continuation` maps it to its slug.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    repository: str
    branch: str
    sha: str


class AbandonedBranch(BaseModel):
    """A branch a resume could have continued and deliberately did not (#1513).

    Recorded on the child's start so the fresh start is visible, with why.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    branch: str
    #: Where the parent left the branch.
    head_sha: str
    reason: str


class RemoteBranchReading(BaseModel):
    """What the forge said about one branch as a resume started.

    `readable` False means nobody could ask - no forge access, a rate limit -
    and is never read as "the branch is gone".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    branch: str
    readable: bool
    #: Where the branch is now; None when it does not exist.
    head_sha: str | None = None
    open_pull_request: int | None = None
    #: The most recent closed or merged PR from the branch, when none is open.
    closed_pull_request: int | None = None


class PhaseCheckout(BaseModel):
    """What one phase's repositories are checked out at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `owner/name` -> the commit (see `SourceCommit`); for a continued
    #: branch, the head the decision confirmed.
    commits: dict[str, str] = Field(default_factory=dict)
    #: `owner/name` -> the branch to check out at its head instead of detached.
    branches: dict[str, str] = Field(default_factory=dict)


class LeftBranches(BaseModel):
    """The branches a failed run's failing phase left on origin, by that phase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str | None = None
    branches: list[ContinuedBranch] = Field(default_factory=list)


def branches_left_by(
    observed: Sequence[object] | None,
    *,
    repositories: Sequence[str],
    continued: Sequence[ContinuedBranch],
    pushed: Sequence[PushedCommit] = (),
) -> list[ContinuedBranch]:
    """The branches a failing phase left on origin, as `ContinuedBranch`es.

    ``observed`` is the failure's `observed_branches` (BranchObservation or
    its replayed mapping). A branch counts when origin holds it and it is one
    the phase OWNED: either it did not exist on origin when the phase started
    (the phase created it), or the phase was itself continuing it. That
    second half is what keeps a branch the phase merely sat on - `main`
    moving under a fetch - from ever being continued.

    ``pushed`` is what the failing phase's own workspace pushed (PC-128). A
    branch it pushed to is owned, and is left at its last pushed SHA even
    when there is no observation at all - the orphaned-by-restart case.

    ``repositories`` maps an observation's directory name back to its slug; a
    name two repositories share maps to neither, rather than to a guess.
    """
    slugs = repository_slugs_by_name(repositories)
    own = _pushed_shas_by_branch(pushed, slugs)
    owned = {(c.repository, c.branch) for c in continued} | own.keys()
    left = {(c.repository, c.branch): c for c in continued}
    for (slug, branch), shas in own.items():
        earlier = left.get((slug, branch))
        left[slug, branch] = ContinuedBranch(
            repository=slug,
            branch=branch,
            head_sha=shas[-1],
            pull_request=earlier.pull_request if earlier is not None else None,
            pushed_shas=shas,
        )
    for raw in observed or ():
        branch = _left_branch(_observation(raw), slugs, owned, left)
        if branch is not None:
            left[branch.repository, branch.branch] = branch
    return list(left.values())


def _pushed_shas_by_branch(
    pushed: Sequence[PushedCommit], slugs: dict[str, str]
) -> dict[tuple[str, str], list[str]]:
    """(slug, branch) -> the SHAs pushed to it, oldest first, without repeats."""
    by_branch: dict[tuple[str, str], list[str]] = {}
    for push in pushed:
        slug = slugs.get(push.repository)
        if slug is None:
            continue
        shas = by_branch.setdefault((slug, push.branch), [])
        if push.sha not in shas:
            shas.append(push.sha)
    return by_branch


def repository_slugs_by_name(repositories: Sequence[str]) -> dict[str, str]:
    """Directory name -> `owner/name`, for the names exactly one repository has."""
    by_name: dict[str, list[str]] = {}
    for slug in repositories:
        by_name.setdefault(slug.rsplit("/", 1)[-1], []).append(slug)
    return {name: found[0] for name, found in by_name.items() if len(found) == 1}


def _left_branch(
    obs: BranchObservation | None,
    slugs: dict[str, str],
    owned: set[tuple[str, str]],
    left: dict[tuple[str, str], ContinuedBranch],
) -> ContinuedBranch | None:
    """The branch ``obs`` says the phase left and owned, or None."""
    slug = slugs.get(obs.repo) if obs is not None else None
    if obs is None or obs.remote_commit is None or slug is None:
        return None
    key = (slug, obs.branch)
    if obs.remote_commit_at_phase_start is not None and key not in owned:
        return None
    # A PR the forge could not be asked about at failure is still the one the
    # run was continuing, if it was continuing one.
    earlier = left.get(key)
    earlier_pr = earlier.pull_request if earlier is not None else None
    return ContinuedBranch(
        repository=slug,
        branch=obs.branch,
        head_sha=obs.remote_commit,
        pull_request=obs.pull_request if obs.pull_request is not None else earlier_pr,
        pushed_shas=earlier.pushed_shas if earlier is not None else [],
    )


def _observation(raw: object) -> BranchObservation | None:
    """The observation, when it is of a branch origin holds; None otherwise.

    None for anything that is not: another remote, a detached HEAD, a deleted
    ref, or a payload this reader cannot read.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation as Observation,
    )

    try:
        obs = raw if isinstance(raw, Observation) else Observation.model_validate(raw)
    except ValidationError:
        logger.warning("Unreadable observed branch on a replayed failure; ignoring it")
        return None
    if obs.remote != _ORIGIN or obs.remote_commit is None or obs.branch == "(detached HEAD)":
        return None
    return obs


def continuation_candidates(left: LeftBranches, resume_phase_id: str) -> list[ContinuedBranch]:
    """What a resume at ``resume_phase_id`` should try to continue.

    Only the branches the parent's FAILING phase left, and only when the
    resume resumes that same phase. A later phase that reads the branch reads
    it through its predecessor's artifact at the pinned commit; it continues
    nothing.
    """
    if left.phase_id is None or left.phase_id != resume_phase_id:
        return []
    return list(left.branches)


def decide_continuation(
    candidates: Sequence[ContinuedBranch], readings: Sequence[RemoteBranchReading]
) -> tuple[list[ContinuedBranch], list[AbandonedBranch]]:
    """Which candidates the child continues, and which it abandons and why.

    Continued only when the forge confirms the branch is exactly where the
    parent left it, or at another commit the parent's phase itself pushed
    there (PC-128), and the PR open from it is the one the parent recorded.
    Everything else is abandoned with the reason: the phase starts fresh,
    visibly.
    """
    by_key = {(r.repository, r.branch): r for r in readings}
    continued: list[ContinuedBranch] = []
    abandoned: list[AbandonedBranch] = []
    for candidate in candidates:
        reading = by_key.get((candidate.repository, candidate.branch))
        if reading is not None and reading.head_sha in candidate.pushed_shas:
            candidate = _at_own_push(candidate, reading)
        reason = _abandon_reason(candidate, reading)
        if reason is None:
            continued.append(candidate)
        else:
            abandoned.append(
                AbandonedBranch(
                    repository=candidate.repository,
                    branch=candidate.branch,
                    head_sha=candidate.head_sha,
                    reason=reason or "the branch was not read",
                )
            )
    return continued, abandoned


def _at_own_push(candidate: ContinuedBranch, reading: RemoteBranchReading) -> ContinuedBranch:
    """``candidate`` at the head origin has, which the parent's phase pushed itself.

    The PR the parent recorded still has to be the open one. When it recorded
    none - a fix phase pushes to a PR it did not open, and an orphaned run
    records no PR at all - the PR open from a branch whose head is the run's
    own commit is the one that commit updated, so it is the one continued.
    """
    pull_request = candidate.pull_request
    if pull_request is None:
        pull_request = reading.open_pull_request
    return candidate.model_copy(update={"head_sha": reading.head_sha, "pull_request": pull_request})


def _abandon_reason(candidate: ContinuedBranch, reading: RemoteBranchReading | None) -> str | None:
    """Why ``candidate`` may not be continued, or None when it may."""
    if reading is None or not reading.readable:
        return "the forge could not be asked where the branch is, so it was not reused unverified"
    if reading.head_sha is None:
        return "the branch no longer exists on origin (deleted)"
    if reading.head_sha != candidate.head_sha:
        return (
            f"origin has the branch at {reading.head_sha}, not {candidate.head_sha} where the "
            "parent left it (force-pushed or moved since)"
        )
    return _pull_request_reason(candidate.pull_request, reading)


def _pull_request_reason(recorded: int | None, reading: RemoteBranchReading) -> str | None:
    """Why the PR open from the branch now is not the one the parent left, or None."""
    now = reading.open_pull_request
    if now == recorded:
        if now is None and reading.closed_pull_request is not None:
            return f"its pull request #{reading.closed_pull_request} was closed or merged"
        return None
    if recorded is None:
        return f"pull request #{now} is open from it, but the parent recorded no open PR"
    if now is None:
        return f"the parent's pull request #{recorded} is no longer open (closed or merged)"
    return (
        f"the parent's pull request #{recorded} is no longer open; #{now} is open from "
        "the branch now, and a PR the parent did not open is not continued"
    )


_CONTINUED: TypeAdapter[list[ContinuedBranch]] = TypeAdapter(list[ContinuedBranch])
_ABANDONED: TypeAdapter[list[AbandonedBranch]] = TypeAdapter(list[AbandonedBranch])


def read_continued_branches(raw: object) -> list[ContinuedBranch]:
    """The continued branches on a replayed start, or empty when absent or unreadable.

    Empty fails toward a fresh start, the behaviour before #1513, and says so.
    """
    if not raw:
        return []
    try:
        return _CONTINUED.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable continued_branches on a replayed start; starting fresh")
        return []


def read_abandoned_branches(raw: object) -> list[AbandonedBranch]:
    """The abandoned branches on a replayed start, or empty when absent or unreadable."""
    if not raw:
        return []
    try:
        return _ABANDONED.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable abandoned_branches on a replayed start; ignoring them")
        return []
