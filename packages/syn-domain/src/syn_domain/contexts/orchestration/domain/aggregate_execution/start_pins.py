"""What an execution fixes about itself when it starts, and where a resume came from.

A resume runs the rest of its parent's work (ADR-014 s7). "The rest of it" is
only the same work if it is run the way the parent would have run it, so the
parent has to have written that down when IT started - not left it to be looked
up in the workflow template later, which may have been edited in between (#1454)
and would then hand the resume a phase the parent never had. The same goes for
the code the parent ran against (#1457).

So `WorkflowExecutionStarted` carries three things beyond its phase list, all
defined here:

* the full runnable config of every phase (`pinned_phases`) - provider, model
  as resolved at start, prompt, sandbox, tools, plugins, skills;
* the commit each repository was at (`source_commits`);
* for a resume only, what it inherited and where it resumes (`resumed_from`).

The readers below are the replay seam for them. They accept both what a typed
event holds and the plain data an ADR-023 `GenericDomainEvent` hands back.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    AbandonedBranch,
    ContinuedBranch,
    LeftBranches,
    PhaseCheckout,
    PushedCommit,
    branches_left_by,
    read_abandoned_branches,
    read_continued_branches,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    LegacyEventShapeError,
    payload_of,
    upcast_forked_payload,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    INHERITED_PHASE_OWNERS,
    ExecutablePhase,
    InheritedPhase,
    PhaseDefinition,
    ResumeOrigin,
    SourceCommit,
    restore_owners,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent

logger = logging.getLogger(__name__)


# Re-exported: `SourceCommit` and `ResumeOrigin` now live in `value_objects`,
# because the start EVENT carries them and a domain event may not import from an
# aggregate's internals (vsa). Kept importable from here so the many modules that
# read them alongside the other pins do not all have to move.
__all__ = [
    "AdmittedResume",
    "ResumeOrigin",
    "SourceCommit",
    "StartPins",
]


class StartPins(BaseModel):
    """Everything an execution pinned about itself at start, as replayed.

    The aggregate holds one of these rather than four loose fields, so what a
    resume of it inherits is read from a single place (#1454, #1457).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    inputs: dict[str, str] = Field(default_factory=dict)
    pinned_phases: list[ExecutablePhase] = Field(default_factory=list)
    source_commits: list[SourceCommit] = Field(default_factory=list)
    #: Set on a resume only: the parent this run was resumed from.
    resumed_from: ResumeOrigin | None = None
    #: Set on a resume only: the branches its resumed phase continues (#1513).
    continued_branches: list[ContinuedBranch] = Field(default_factory=list)
    #: Set on a resume only: branches it could have continued and did not, and why.
    abandoned_branches: list[AbandonedBranch] = Field(default_factory=list)
    #: Set on a resume only: phases its parent's certified review skipped (#1681).
    inherited_skipped_phase_ids: list[str] = Field(default_factory=list)
    #: The installed workflow version it launched from (Evals v2); a resume
    #: carries its parent's, never the template's current one.
    workflow_version: str | None = None

    def inherited_owners(self) -> dict[str, str]:
        """Who holds the artifacts of each phase a resume inherited, by phase id."""
        return {} if self.resumed_from is None else self.resumed_from.owners()

    def checkout_for(self, phase_id: str) -> PhaseCheckout:
        """What ``phase_id``'s repositories are checked out at (#1458, #1513).

        THE RULE, in one place. A phase that READS code gets the pinned start
        commits (`checkout_commits`). The phase a resume resumes CONTINUES
        each branch in `continued_branches` - the branches its own earlier
        attempt pushed - so those repositories are checked out on that
        branch, at its head, instead. No other phase continues anything.
        """
        commits = {c.repository: c.sha for c in self.checkout_commits() if c.sha is not None}
        if self.resumed_from is None or phase_id != self.resumed_from.resume_phase_id:
            return PhaseCheckout(commits=commits)
        branches: dict[str, str] = {}
        for continued in self.continued_branches:
            commits[continued.repository] = continued.head_sha
            branches[continued.repository] = continued.branch
        return PhaseCheckout(commits=commits, branches=branches)

    def checkout_commits(self) -> list[SourceCommit]:
        """The commits this run's phases check their repositories out at (#1458).

        Every run's, fresh or resumed: what `source_commits` records is what
        the run is checked out at, so the record is a fact about the code the
        run ran on rather than about the moment it started. A resume copies
        its parent's record, so it runs the rest of its parent's work against
        the code the parent actually ran, however far the default branch has
        moved.

        A fresh run is pinned too, because otherwise its record would not be
        what it ran: the commit is read at start and each phase is cloned
        later, at provisioning, so a push landing in between - or between two
        of its phases - would have the run work on a commit nothing recorded,
        and a resume of it check out a different one (verification of #1525).

        A repository whose commit nobody could resolve (`sha` None) pins
        nothing. There is no commit to hold it to, so it clones the default
        branch's head as it always has, and refusing it would make every run
        started without GitHub access impossible.
        """
        return [c for c in self.source_commits if c.sha is not None]


class AdmittedResume(BaseModel):
    """The resume a parent admitted, as its `ExecutionResumed` fixed it.

    Read back to build the child's start, never recomputed: the parent's state
    may have moved on since, and the decision is the one that was recorded.
    `resume_execution_id` can replay as None under ADR-023; a start built from
    that is refused, never invented (`resume_start.resume_start_command`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    resume_execution_id: str | None = None
    inherited_phases: list[InheritedPhase] = Field(default_factory=list)
    resume_phase_id: str | None = None
    inherited_skipped_phase_ids: list[str] = Field(default_factory=list)


def phase_definitions_of(phases: Sequence[ExecutablePhase]) -> list[PhaseDefinition]:
    """The sequencing view of a runnable phase list.

    One spelling for the fresh start and the resume, so the phase timeout the
    aggregate sequences by is derived the same way on both.
    """
    return [
        PhaseDefinition(
            phase_id=p.phase_id,
            name=p.name,
            order=p.order,
            timeout_seconds=p.effective_timeout_seconds,
        )
        for p in phases
    ]


_PINNED_PHASES: TypeAdapter[list[ExecutablePhase]] = TypeAdapter(list[ExecutablePhase])
_SOURCE_COMMITS: TypeAdapter[list[SourceCommit]] = TypeAdapter(list[SourceCommit])
_INHERITED_PHASES: TypeAdapter[list[InheritedPhase]] = TypeAdapter(list[InheritedPhase])


def read_inputs(raw: object) -> dict[str, str]:
    """What the execution was asked to do, as a resume will be asked it again.

    `str` values because that is what reaches the start event: the only way in
    is `ExecuteWorkflowCommand.inputs`, a `dict[str, str]`, and what the
    processor adds (`repos`) is a string too. The coercion is for a payload
    written some other way, and is lossless for everything written this way.
    """
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def read_pinned_phases(raw: object) -> list[ExecutablePhase]:
    """The pinned phases, or empty when absent or unreadable.

    Empty is safe to fall back to because it fails CLOSED: a parent with no
    pinned phases cannot be resumed (`resume_rules.refuse_resume_start`), so a
    snapshot this reader cannot trust is never run from.
    """
    if not raw:
        return []
    try:
        return _PINNED_PHASES.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable pinned_phases on a replayed start event; treating as absent")
        return []


def read_source_commits(raw: object) -> list[SourceCommit]:
    """Recorded commits - a start's, or a provisioning's checkout - or empty when unreadable."""
    if not raw:
        return []
    try:
        return _SOURCE_COMMITS.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable commits on a replayed event; treating as absent")
        return []


def read_inherited_phases(raw: object, owners: object) -> list[InheritedPhase]:
    """The inherited prefix on a replayed `ExecutionResumed`.

    ``owners`` is what the event carried under `INHERITED_PHASE_OWNERS`. A typed
    event has already put them back; a generic one (ADR-023) has not, and
    dropping them here would lose #1462's fix on exactly that stream.
    """
    return _INHERITED_PHASES.validate_python(restore_owners(raw, owners) or [])


def read_start_pins(event: DomainEvent) -> StartPins:
    """The pins on a replayed `WorkflowExecutionStarted`, typed or generic."""
    return StartPins(
        inputs=read_inputs(evt(event, "inputs")),
        pinned_phases=read_pinned_phases(evt(event, "pinned_phases")),
        source_commits=read_source_commits(evt(event, "source_commits")),
        resumed_from=read_resume_origin(
            evt(event, "resumed_from"), evt(event, INHERITED_PHASE_OWNERS)
        ),
        continued_branches=read_continued_branches(evt(event, "continued_branches")),
        abandoned_branches=read_abandoned_branches(evt(event, "abandoned_branches")),
        inherited_skipped_phase_ids=read_phase_ids(evt(event, "inherited_skipped_phase_ids")),
        workflow_version=evt(event, "workflow_version"),
    )


def read_left_branches(
    pins: StartPins, event: DomainEvent, pushed: Sequence[PushedCommit] = ()
) -> LeftBranches:
    """The branches a replayed `WorkflowFailed`'s failing phase left on origin (#1513).

    A run that was itself continuing branches in the phase that failed owns
    them still, moved or not, so a resume of it continues them in turn. So
    does every branch the failing phase's own workspace pushed to, from
    ``pushed`` (PC-128): the only record a run orphaned by a restart has.
    """
    phase_id = evt(event, "failed_phase_id")
    resuming_same_phase = (
        pins.resumed_from is not None and pins.resumed_from.resume_phase_id == phase_id
    )
    return LeftBranches(
        phase_id=phase_id,
        branches=branches_left_by(
            evt(event, "observed_branches"),
            repositories=[c.repository for c in pins.source_commits],
            continued=pins.continued_branches if resuming_same_phase else [],
            pushed=[p for p in pushed if p.phase_id == phase_id],
        ),
    )


def read_admitted_resume(event: DomainEvent) -> AdmittedResume:
    """The resume a replayed `ExecutionResumed` admitted, typed or generic."""
    return AdmittedResume(
        resume_execution_id=evt(event, "resume_execution_id"),
        inherited_phases=read_inherited_phases(
            evt(event, "inherited_phases"), evt(event, INHERITED_PHASE_OWNERS)
        ),
        resume_phase_id=evt(event, "resume_phase_id"),
        inherited_skipped_phase_ids=read_phase_ids(evt(event, "inherited_skipped_phase_ids")),
    )


def read_phase_ids(value: object) -> list[str]:
    """A stored list of phase ids; empty when absent, as on events before #1681."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _stored_str(value: object) -> str | None:
    """A stored value as a string, or None when it is not one.

    Reading a non-string as absent is deliberate: the resume then refuses with
    "cannot be named" rather than starting a child under whatever the record
    happened to hold.
    """
    return value if isinstance(value, str) else None


def read_admitted_forked_resume(event: DomainEvent) -> AdmittedResume:
    """The resume a pre-rename `ExecutionForked` admitted.

    The upcast happens inside rather than at the call site, so the only thing
    that ever crosses this boundary is the typed value object. The concept
    never changed with the rename, so the fields map one to one.
    """
    upcast = upcast_forked_payload(payload_of(event))
    if not isinstance(upcast, Mapping):
        msg = "An ExecutionForked payload is not readable as a resume"
        raise LegacyEventShapeError(msg)
    return AdmittedResume(
        resume_execution_id=_stored_str(upcast.get("resume_execution_id")),
        inherited_phases=read_inherited_phases(
            upcast.get("inherited_phases"), upcast.get(INHERITED_PHASE_OWNERS)
        ),
        resume_phase_id=_stored_str(upcast.get("resume_phase_id")),
    )


def read_resume_origin(raw: object, owners: object) -> ResumeOrigin | None:
    """Where this execution was resumed from, or None for one that was not.

    Deliberately NOT forgiving, unlike the two readers above. Absent means "not
    a resume"; present-but-unreadable raises, because treating it as absent would
    replay a resume as a fresh run - one whose inherited phases are no longer
    closed, which is the fail-open this whole feature exists to prevent.

    ``owners`` is what the start event carried beside ``raw`` under
    `INHERITED_PHASE_OWNERS`, as for `read_inherited_phases`.
    """
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        raw = {**raw, "inherited_phases": restore_owners(raw.get("inherited_phases"), owners)}
    return ResumeOrigin.model_validate(raw)
