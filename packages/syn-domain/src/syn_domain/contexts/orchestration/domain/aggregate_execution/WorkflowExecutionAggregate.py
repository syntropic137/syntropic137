"""WorkflowExecution aggregate - tracks execution lifecycle.

Each workflow execution is its own aggregate (keyed by execution_id).
Location: orchestration/domain/aggregate_execution/ (per ADR-020)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from event_sourcing import (
    AggregateRoot,
    aggregate,
    command_handler,
    event_sourcing_handler,
)

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    LeftBranches,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (  # noqa: TC001 - re-exported + used at runtime by @command_handler
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CancelExecutionCommand,
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    InterruptExecutionCommand,
    ProvisionWorkspaceCompletedCommand,
    ResumeExecutionCommand,
    RetryPhaseCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    StartResumeCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    EvalMembership,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.execution_tags import (
    ExecutionTags,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    resumed_event_applies,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    completed_event,
    failed_event,
    started_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import (
    evt,
    parse_phase_definitions,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_rules import (
    ResumeRefused,
    decide_resume,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_start import (
    refuse_resume_start,
    resume_start_command,
    resume_started_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
    ReviewRecord,
    next_phase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.run_edits import RunEdits
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    AdmittedResume,
    ResumeOrigin,
    StartPins,
    read_admitted_forked_resume,
    read_admitted_resume,
    read_left_branches,
    read_source_commits,
    read_start_pins,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
    FinishedAgentRun,
    PhaseDefinition,
    ReportedFailureReason,
    ReviewVerdict,
    SideEffectStatus,
    SourceCommit,
    StrandedDeliverable,
)
from syn_shared.control import ControlSignalType

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
        AgentExecutionCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
        ArtifactsCollectedForPhaseEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
        ExecutionCancelledEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
        ExecutionResumedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
        NextPhaseReadyEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
        PhaseCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseRetryScheduledEvent import (
        PhaseRetryScheduledEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
        PhaseStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
        WorkflowCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
        WorkflowInterruptedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
        WorkspaceProvisionedForPhaseEvent,
    )


#: How many times one phase of one execution may be attempted, counting the
#: original. Two, so a phase gets exactly one retry (#1335).
#:
#: A CEILING ON THE BILL, not a tuning knob. The fault this exists for - an
#: agent stream that ends without its terminal usage event - is indistinguishable
#: from the outside from one that will recur every time, so every attempt beyond
#: the first is money spent on a guess. One retry is the smallest number that
#: turns "lose the whole run" into "lose this phase"; a larger one buys a
#: diminishing share of the remaining faults at full price each, and an
#: unbounded one bills until the phase timeout does the refusing instead.
MAX_PHASE_ATTEMPTS: Final[int] = 2


logger = logging.getLogger(__name__)


@aggregate("WorkflowExecution")
class WorkflowExecutionAggregate(RunEdits, AggregateRoot["WorkflowExecutionStartedEvent"]):
    """Aggregate for tracking workflow execution lifecycle; tag and eval edits are in `RunEdits`."""

    _aggregate_type: str

    def __init__(self) -> None:
        """Initialize aggregate."""
        super().__init__()
        self._workflow_id: str | None = None
        self._workflow_name: str | None = None
        self._status: ExecutionStatus = ExecutionStatus.RUNNING
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._expected_completion_at: datetime | None = None
        self._total_phases: int = 0
        self._completed_phases: int = 0
        self._current_phase_order: int = 0
        #: The phase that has started and not yet completed, if any. Needed
        #: because a failure has to name the phase it failed IN: a
        #: WorkflowFailedEvent with no failed_phase_id leaves both phase read
        #: models claiming the phase is still running forever, since
        #: PhaseCompleted is their only other writer (#1036, #1120).
        self._running_phase_id: str | None = None
        self._total_tokens: int = 0
        self._artifact_ids: list[str] = []
        self._error: str | None = None
        #: What kind of failure ended this run (#1357), for a run that has
        #: ended in one. `UNCLASSIFIED` until a `WorkflowFailed` event says
        #: otherwise, which is also what every such event written before the
        #: field existed replays as.
        self._failure_classification: FailureClassification = FailureClassification.UNCLASSIFIED
        self._reported_failure_reason: ReportedFailureReason | None = None
        self._cancel_reason: str | None = None
        self._phase_definitions: list[PhaseDefinition] = []
        self._phase_order_map: dict[str, int] = {}
        self._current_phase_workspace_id: str | None = None
        #: What each RUNNING phase's agent left behind, keyed by phase.
        #:
        #: Replayed state, not a cache. The salvage (#1195, #1300) turns this
        #: into the phase's deliverable when nothing was written to
        #: `artifacts/output/`, and the decision it feeds - complete or fail -
        #: is a domain outcome. Held in the processor, as it was until #1300's
        #: review, it was destroyed by any restart between the agent finishing
        #: and its artifacts being collected: the rescue then worked only for
        #: runs where nothing much had gone wrong. Entries are dropped as each
        #: phase's artifacts are collected, so this never grows past the phases
        #: currently in flight - and so their presence IS the statement that
        #: the phase's output has not been collected yet.
        self._finished_agent_runs: dict[str, FinishedAgentRun] = {}
        #: The name each started phase goes by, so a salvage can title what it
        #: stores the way the live collector titles it.
        self._phase_names: dict[str, str] = {}
        #: How many times each phase has been ATTEMPTED, counting the one
        #: running now. Absent means never started; a phase that has started
        #: once and never been retried is 1.
        #:
        #: Replayed state because it is the retry budget itself, and a budget
        #: rebuilt from the process would be restored to full by any restart -
        #: which is the difference between one extra attempt and an unbounded
        #: number of them, each one billed. See `MAX_PHASE_ATTEMPTS`.
        self._phase_attempts: dict[str, int] = {}
        #: Phases whose deliverable was salvaged rather than written.
        #:
        #: Decided at collection and needed at completion, which are two
        #: different to-do items and therefore two possible processes - the
        #: same restart hazard as the message above, and here for the same
        #: reason rather than because the value is expensive to recompute.
        self._recovered_phases: set[str] = set()
        #: What each phase's latest agent run said about its external writes.
        #: Same restart hazard as `_recovered_phases`: reported when the agent
        #: finishes, needed when the phase completes.
        self._reported_side_effects: dict[str, SideEffectStatus | None] = {}
        #: Review verdicts, which choose the next phase (PC-63).
        self._reviews = ReviewRecord()
        #: Phases that completed, and what each one's collection stored. The
        #: inputs to a resume's inherited prefix (ADR-014 s7), which is decided
        #: here from the stream and never from the artifact projection: a
        #: projection that is merely lagging would read as missing artifacts,
        #: and a parent may be resumed only once.
        self._completed_phase_ids: set[str] = set()
        self._phase_artifact_ids: dict[str, list[str]] = {}
        #: Whether this execution has admitted a resume. THIS is the
        #: "resumed at most once" rule, deliberately separate from the child's
        #: id below, which under ADR-023 can replay as None and would make the
        #: rule fail OPEN - see `resume_rules.refuse_resume`.
        self._resumed: bool = False

        #: The child's id: for the refusal message, and the id its start is
        #: built under - where a None refuses the start rather than naming one.
        self._resume_execution_id: str | None = None
        self._admitted_resume = AdmittedResume()
        #: What this run was started with, pinned so a resume of it runs the same
        #: thing (#1454, #1457). Never read back from the workflow template.
        self._pins = StartPins()
        #: The branches the phase this run failed in left on origin (#1513).
        self._left_branches = LeftBranches()
        #: The tags it launched with and the tags it carries now (#967).
        self._tags = ExecutionTags()
        self._eval = EvalMembership()
        #: The first workspace's verified checkout (#967); None until it is applied.
        self._starting_checkout: list[SourceCommit] | None = None

    def get_aggregate_type(self) -> str:
        """Return aggregate type name."""
        return self._aggregate_type

    @property
    def workflow_id(self) -> str | None:
        """Get the workflow ID being executed."""
        return self._workflow_id

    @property
    def running_phase_id(self) -> str | None:
        """The phase that started and has not completed, or None.

        Rebuilt from the event stream like every other piece of aggregate
        state, so it survives a restart - which is the case that needs it.
        """
        return self._running_phase_id

    def may_retry_phase(self, phase_id: str) -> bool:
        """Whether this phase may be attempted again, budget-wise (#1335).

        Answers only the half of the question this aggregate owns: how many
        attempts this phase has already had against `MAX_PHASE_ATTEMPTS`. It
        says nothing about whether the attempt that just died deserves another
        one - that is a reading of the agent's stream, and the slice that reads
        the stream decides it.

        Asked before `retry_phase` rather than discovered by catching its
        refusal, because a caller that has run out of budget has a different
        job to do (report the failure it was about to report) and not an error
        to handle.
        """
        return self._phase_attempts.get(phase_id, 0) < MAX_PHASE_ATTEMPTS

    def accepts_control(self, signal: ControlSignalType) -> bool:
        """Whether an operator may ask this execution to do `signal` now.

        The one place the rule lives (ADR-014 section 7). The cancel handler
        guards on it, and the control plane asks it before it
        queues a signal, so the answer an operator gets is the answer the
        command will get. That only holds when this is asked of the aggregate
        rehydrated from its stream: a read model that has not yet caught up
        with a cancel still says `running`, and a guard is worth only as much
        as the staleness of what it reads.
        """
        if self.id is None:
            return False
        match signal:
            case ControlSignalType.CANCEL | ControlSignalType.INJECT:
                return self._status is ExecutionStatus.RUNNING

    def attempts_for(self, phase_id: str) -> int:
        """How many times this phase has been attempted, 0 if never started."""
        return self._phase_attempts.get(phase_id, 0)

    def last_agent_message_for(self, phase_id: str) -> str | None:
        """What this phase's agent said as it finished, or None.

        The input to the #1195/#1300 salvage, answered from the event stream
        so the answer is the same in the process that heard it and in one that
        started afterwards.
        """
        run = self._finished_agent_runs.get(phase_id)
        return run.last_agent_message if run is not None else None

    @property
    def stranded_deliverable(self) -> StrandedDeliverable | None:
        """The deliverable this execution can still produce, or None.

        Answers one question - "is there finished work here that nothing has
        collected?" - so that a caller deciding what to do with an execution a
        restart left running does not have to know which pair of events opens
        and closes that window, nor that the window exists.

        It is non-None for exactly the gap the salvage exists for: a phase
        whose agent finished and said something, whose artifacts were never
        collected, in an execution that is still RUNNING. Outside that gap
        there is either nothing to recover or a deliverable already stored,
        and in both cases the honest answer is None.
        """
        if self._status != ExecutionStatus.RUNNING:
            return None
        execution_id = self.aggregate_id
        if execution_id is None:
            return None
        phase_id = self._running_phase_id
        if phase_id is None:
            return None
        run = self._finished_agent_runs.get(phase_id)
        if run is None:
            return None
        return StrandedDeliverable(
            execution_id=execution_id,
            workflow_id=self._workflow_id or "",
            phase_id=run.phase_id,
            phase_name=run.phase_name,
            session_id=run.session_id,
            last_agent_message=run.last_agent_message,
        )

    @property
    def status(self) -> ExecutionStatus:
        """Get execution status."""
        return self._status

    @property
    def review_verdict(self) -> ReviewVerdict | None:
        """The last review verdict reported; `BLOCKED` on a completed run is unresolved findings."""
        return self._reviews.latest

    @property
    def failure_classification(self) -> FailureClassification:
        """What kind of failure ended this run, for a run that failed (#1357).

        Beside `status` rather than folded into it: `failed` is what happened
        and stays true for every value here, and this says what KIND. A run
        that has not failed reads `UNCLASSIFIED`, which is also what a failure
        recorded before the field existed reads - the aggregate cannot
        distinguish those two and does not pretend to, because `status` already
        does it exactly.
        """
        return self._failure_classification

    @property
    def reported_failure_reason(self) -> ReportedFailureReason | None:
        """What the failing phase SAID caused it (#1372), None when it did not.

        Apart from `failure_classification` deliberately and permanently: that
        one is what the platform measured and is what failure numbers are
        computed from, this one is a claim the run made about itself (#1392).
        """
        return self._reported_failure_reason

    @property
    def cancel_reason(self) -> str | None:
        """Get the cancellation reason, if the execution was cancelled."""
        return self._cancel_reason

    @property
    def tags(self) -> ExecutionTags:
        """The launch snapshot and the current tags (#967)."""
        return self._tags

    @property
    def eval_membership(self) -> EvalMembership:
        """The eval this run belongs to, how it joined, and what it launched into."""
        return self._eval

    @property
    def starting_checkout(self) -> list[SourceCommit]:
        """Each pinned repository's verified commit when the run's first workspace began."""
        return self._starting_checkout or []

    @property
    def start_pins(self) -> StartPins:
        """What this run pinned at start, including `resumed_from` for a resume."""
        return self._pins

    @property
    def resume_execution_id(self) -> str | None:
        """The resume this run admitted, or None. The other half of `resumed_from`."""
        return self._resume_execution_id

    def resume_start_command(self) -> StartResumeCommand:
        """The start of the resume this run admitted, from this stream alone."""
        return resume_start_command(
            parent_execution_id=self.id,
            workflow_id=self._workflow_id or "",
            workflow_name=self._workflow_name or "",
            pins=self._pins,
            resumed=self._resumed,
            admitted=self._admitted_resume,
            left=self._left_branches,
        )

    @command_handler("StartExecutionCommand")
    def start_execution(self, command: StartExecutionCommand) -> None:
        """Handle StartExecutionCommand."""
        if self.id is not None:
            msg = "Execution already started"
            raise ValueError(msg)

        self._initialize(command.aggregate_id)
        self._apply(started_event(command))

    @command_handler("StartResumeCommand")
    def start_resume(self, command: StartResumeCommand) -> None:
        """Handle StartResumeCommand - start the run a parent's resume admitted.

        Addressed to the CHILD's new stream. Its inherited phases are closed
        from its first event on (`on_execution_started`), so no later command
        can start one again: the child cannot re-run what it inherited.
        """
        if self.id is not None:
            msg = "Execution already started"
            raise ValueError(msg)
        refusal = refuse_resume_start(command)
        if refusal is not None:
            raise ValueError(refusal)

        self._initialize(command.aggregate_id)
        self._apply(resume_started_event(command))

    @command_handler("CompleteExecutionCommand")
    def complete_execution(self, command: CompleteExecutionCommand) -> None:
        """Handle CompleteExecutionCommand."""
        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot complete execution in status {self._status}"
            raise ValueError(msg)

        self._apply(completed_event(command, self._workflow_id or "", self._reviews.latest))

    @command_handler("FailExecutionCommand")
    def fail_execution(self, command: FailExecutionCommand) -> None:
        """Handle FailExecutionCommand."""
        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot fail execution in status {self._status}"
            raise ValueError(msg)

        self._apply(failed_event(command, self._workflow_id or ""))

    def _refuse_if_completed(self, phase_id: str, verb: str) -> None:
        """A completed phase's record is closed (#1453).

        Three commands could each reopen it - start, complete, collect - and
        each corrupts it differently: a second start lets a retry drop the
        artifacts of the attempt that did complete, a second completion inflates
        the completed count and can append another attempt's artifact, and a
        late collection injects artifacts into a phase that finished. A resume
        inherits the completed prefix, so all three end up handing a child work
        whose inputs are not what the record says (ADR-014 s7).

        One guard rather than three copies: the doors are different, the rule is
        the same, and a rule spelled once cannot be closed on two of them.
        """
        if phase_id in self._completed_phase_ids:
            msg = f"Cannot {verb} phase {phase_id}: it has already completed"
            raise ValueError(msg)

    @command_handler("StartPhaseCommand")
    def start_phase(self, command: StartPhaseCommand) -> None:
        """Handle StartPhaseCommand."""
        from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
            PhaseStartedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot start phase in status {self._status}"
            raise ValueError(msg)
        self._refuse_if_completed(command.phase_id, "start")

        event = PhaseStartedEvent(
            workflow_id=command.workflow_id,
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            phase_name=command.phase_name,
            phase_order=command.phase_order,
            started_at=datetime.now(UTC),
            session_id=command.session_id,
        )
        self._apply(event)

    @command_handler("RetryPhaseCommand")
    def retry_phase(self, command: RetryPhaseCommand) -> None:
        """Handle RetryPhaseCommand — give this phase's attempt up, keep the phase.

        Emits no failure and completes nothing: the execution stays RUNNING and
        the phase stays the current phase, so every phase already completed
        keeps its result and its cost. The next `PhaseStarted` for this phase
        is the retry (#1335).

        Refuses outside the budget rather than silently granting an extra
        attempt, so a caller that skipped `may_retry_phase` cannot spend money
        this aggregate has already said no to.
        """
        from syn_domain.contexts.orchestration.domain.events.PhaseRetryScheduledEvent import (
            PhaseRetryScheduledEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot retry phase in status {self._status}"
            raise ValueError(msg)
        if self._running_phase_id != command.phase_id:
            msg = (
                f"Cannot retry phase {command.phase_id}: the running phase is "
                f"{self._running_phase_id}"
            )
            raise ValueError(msg)
        if not self.may_retry_phase(command.phase_id):
            msg = f"Phase {command.phase_id} has used all {MAX_PHASE_ATTEMPTS} of its attempts"
            raise ValueError(msg)

        event = PhaseRetryScheduledEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            attempt=self._phase_attempts.get(command.phase_id, 0) + 1,
            reason=command.reason,
            scheduled_at=datetime.now(UTC),
        )
        self._apply(event)

    @command_handler("CompletePhaseCommand")
    def complete_phase(self, command: CompletePhaseCommand) -> None:
        """Handle CompletePhaseCommand."""
        from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
            PhaseCompletedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot complete phase in status {self._status}"
            raise ValueError(msg)
        self._refuse_if_completed(command.phase_id, "complete")

        event = PhaseCompletedEvent(
            workflow_id=command.workflow_id,
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            completed_at=datetime.now(UTC),
            success=True,
            artifact_id=command.artifact_id,
            session_id=command.session_id,
            # Read off replayed state rather than taken from the command: the
            # salvage is decided at COLLECT_ARTIFACTS and reported here, a
            # different to-do item and possibly a different process, so the
            # only honest source is the stream. It also keeps
            # CompletePhaseCommand - and every caller of it - unchanged.
            deliverable_recovered=command.phase_id in self._recovered_phases,
            reported_side_effects=self._reported_side_effects.get(command.phase_id),
            input_tokens=command.input_tokens,
            output_tokens=command.output_tokens,
            cache_creation_tokens=command.cache_creation_tokens,
            cache_read_tokens=command.cache_read_tokens,
            total_tokens=command.total_tokens,
            duration_seconds=command.duration_seconds,
        )
        self._apply(event)

    @command_handler("ProvisionWorkspaceCompletedCommand")
    def provision_workspace_completed(self, command: ProvisionWorkspaceCompletedCommand) -> None:
        """Handle workspace provisioned for a phase."""
        from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
            WorkspaceProvisionedForPhaseEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot provision workspace in status {self._status}"
            raise ValueError(msg)

        event = WorkspaceProvisionedForPhaseEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            workspace_id=command.workspace_id,
            session_id=command.session_id,
            provisioned_at=datetime.now(UTC),
            checked_out_commits=list(command.checked_out_commits) or None,
        )
        self._apply(event)

    @command_handler("AgentExecutionCompletedCommand")
    def agent_execution_completed(self, command: AgentExecutionCompletedCommand) -> None:
        """Handle agent finished executing in workspace."""
        from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
            AgentExecutionCompletedEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot complete agent execution in status {self._status}"
            raise ValueError(msg)

        event = AgentExecutionCompletedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            session_id=command.session_id,
            completed_at=datetime.now(UTC),
            exit_code=command.exit_code,
            input_tokens=command.input_tokens,
            output_tokens=command.output_tokens,
            last_agent_message=command.last_agent_message,
            reported_side_effects=command.reported_side_effects,
            reported_review_verdict=command.reported_review_verdict,
        )
        self._apply(event)

    @command_handler("ArtifactsCollectedCommand")
    def artifacts_collected(self, command: ArtifactsCollectedCommand) -> None:
        """Handle artifacts collected — aggregate decides if more phases exist."""
        from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
            ArtifactsCollectedForPhaseEvent,
        )

        if self._status != ExecutionStatus.RUNNING:
            msg = f"Cannot collect artifacts in status {self._status}"
            raise ValueError(msg)
        self._refuse_if_completed(command.phase_id, "collect artifacts for")

        event = ArtifactsCollectedForPhaseEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            artifact_ids=command.artifact_ids,
            collected_at=datetime.now(UTC),
            first_content_preview=command.first_content_preview,
            session_id=command.session_id,
            deliverable_recovered=command.deliverable_recovered,
        )
        self._apply(event)

        # The phase's own verdict decides what runs next (PC-63).
        decided = next_phase(
            self._phase_definitions,
            self._phase_order_map.get(command.phase_id),
            self._reviews.of(command.phase_id),
        )
        if decided is not None:
            self._apply(
                decided.event(
                    workflow_id=self._workflow_id or "",
                    execution_id=command.aggregate_id,
                    completed_phase_id=command.phase_id,
                )
            )

    @command_handler("CancelExecutionCommand")
    def cancel_execution(self, command: CancelExecutionCommand) -> None:
        """Handle CancelExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
            ExecutionCancelledEvent,
        )

        if not self.accepts_control(ControlSignalType.CANCEL):
            msg = f"Cannot cancel execution in status {self._status}"
            raise ValueError(msg)

        event = ExecutionCancelledEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            cancelled_at=datetime.now(UTC),
            reason=command.reason,
        )
        self._apply(event)

    @command_handler("InterruptExecutionCommand")
    def interrupt_execution(self, command: InterruptExecutionCommand) -> None:
        """Handle InterruptExecutionCommand."""
        from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
            WorkflowInterruptedEvent,
        )

        if self.id is None:
            msg = "Cannot interrupt execution that has not been started"
            raise ValueError(msg)
        if self._status is not ExecutionStatus.RUNNING:
            msg = f"Cannot interrupt execution in status {self._status}"
            raise ValueError(msg)

        event = WorkflowInterruptedEvent(
            workflow_id=self._workflow_id or "",
            execution_id=command.aggregate_id,
            phase_id=command.phase_id,
            interrupted_at=datetime.now(UTC),
            reason=command.reason,
            git_sha=command.git_sha,
            partial_artifact_ids=command.partial_artifact_ids,
            partial_input_tokens=command.partial_input_tokens,
            partial_output_tokens=command.partial_output_tokens,
        )
        self._apply(event)

    @command_handler("ResumeExecutionCommand")
    def resume_execution(self, command: ResumeExecutionCommand) -> None:
        """Handle ResumeExecutionCommand - admit, or refuse, one resume of this run.

        Decided on the PARENT, which records `ExecutionResumed` on its own
        stream and is otherwise untouched: it stays terminal, and nothing it
        already recorded is rewritten (ADR-014 s7). Creating and starting the
        resume is not done here - this is the admission, and every fact the resume
        needs from its parent is fixed on the event.

        The rules themselves are in `resume_rules`, where they are pure functions
        of this replayed state and testable without an aggregate.
        """
        decision = decide_resume(
            execution_id=self.id,
            workflow_id=self._workflow_id or "",
            status=self._status,
            resumed=self._resumed,
            resume_execution_id=self._resume_execution_id,
            phase_definitions=self._phase_definitions,
            completed_phase_ids=self._completed_phase_ids,
            phase_artifact_ids=self._phase_artifact_ids,
            phase_owners=self._inherited_owners(),
            started_phase_ids=self._phase_attempts,
            command=command,
            repair_point=self._reviews.repair_point(self._phase_definitions),
        )
        if isinstance(decision, ResumeRefused):
            raise ValueError(decision.reason)
        self._apply(decision.event)

    @event_sourcing_handler("WorkflowExecutionStarted")
    def on_execution_started(self, event: WorkflowExecutionStartedEvent) -> None:
        """Apply WorkflowExecutionStartedEvent."""
        self._workflow_id = evt(event, "workflow_id")
        self._workflow_name = evt(event, "workflow_name")
        self._started_at = evt(event, "started_at")
        self._total_phases = evt(event, "total_phases", 0)
        self._expected_completion_at = evt(event, "expected_completion_at")
        self._phase_definitions = parse_phase_definitions(evt(event, "phase_definitions"))
        self._phase_order_map = {p.phase_id: p.order for p in self._phase_definitions}
        self._status = ExecutionStatus.RUNNING
        self._pins = read_start_pins(event)
        self._tags = ExecutionTags.launched_with(evt(event, "tags") or [])
        self._eval = EvalMembership.launched_into(evt(event, "eval_id"))
        if self._pins.resumed_from is not None:
            self._inherit(self._pins.resumed_from)

    def _inherit(self, origin: ResumeOrigin) -> None:
        """Take over the parent's completed prefix as this run's own.

        As completed, not as merely skipped: `_refuse_if_completed` then closes
        each one to start, completion and collection alike, and a resume of THIS
        run inherits them onward with the same artifacts - and with the
        execution that holds them, which is not this one (#1462).
        """
        for phase in origin.inherited_phases:
            self._completed_phase_ids.add(phase.phase_id)
            self._phase_artifact_ids[phase.phase_id] = list(phase.artifact_ids)
        self._completed_phases = len(origin.inherited_phases)

    def _inherited_owners(self) -> dict[str, str]:
        """Who holds the artifacts of each phase this run inherited, by phase id."""
        origin = self._pins.resumed_from
        return {} if origin is None else origin.owners()

    @event_sourcing_handler("WorkflowCompleted")
    def on_execution_completed(self, event: WorkflowCompletedEvent) -> None:
        """Apply WorkflowCompletedEvent."""
        self._completed_at = evt(event, "completed_at")
        self._completed_phases = evt(event, "completed_phases", 0)
        self._total_tokens = evt(event, "total_tokens", 0)
        self._artifact_ids = list(evt(event, "artifact_ids", []))
        self._status = ExecutionStatus.COMPLETED

    @event_sourcing_handler("WorkflowFailed")
    def on_execution_failed(self, event: WorkflowFailedEvent) -> None:
        """Apply WorkflowFailedEvent."""
        self._completed_at = evt(event, "failed_at")
        self._error = evt(event, "error_message")
        self._status = ExecutionStatus.FAILED
        # Coerced rather than read, because this applier replays events older
        # than the field: `from_stored` turns a missing key - and a member some
        # newer writer knows and this reader does not - into `UNCLASSIFIED`
        # instead of a `ValueError` that would stop the whole stream rehydrating
        # (#1357).
        self._failure_classification = FailureClassification.from_stored(
            evt(event, "failure_classification")
        )
        # Same coercion, same reason, one field over: a reason written by a
        # newer version is a word this reader does not know, and reads as "no
        # reason given" rather than stopping the stream (#1372).
        self._reported_failure_reason = ReportedFailureReason.from_stored(
            evt(event, "reported_failure_reason")
        )
        self._left_branches = read_left_branches(self._pins, event)

    @event_sourcing_handler("PhaseStarted")
    def on_phase_started(self, event: PhaseStartedEvent) -> None:
        """Apply PhaseStartedEvent."""
        self._current_phase_order = evt(event, "phase_order", 0)
        phase_id = evt(event, "phase_id")
        self._running_phase_id = phase_id
        if phase_id:
            self._phase_names[phase_id] = evt(event, "phase_name") or phase_id
            # Counted HERE, on the event that says an attempt began, rather
            # than on PhaseRetryScheduled which only says one was asked for.
            # A retry that is scheduled and then never starts - the process
            # died in between - must not have been billed to the budget, or a
            # restart would find the phase out of attempts having run once.
            self._phase_attempts[phase_id] = self._phase_attempts.get(phase_id, 0) + 1

    @event_sourcing_handler("PhaseCompleted")
    def on_phase_completed(self, event: PhaseCompletedEvent) -> None:
        """Apply PhaseCompletedEvent."""
        self._completed_phases += 1
        self._running_phase_id = None
        phase_id: str = evt(event, "phase_id")
        self._completed_phase_ids.add(phase_id)
        # Collection normally names every artifact already; the completion's
        # own id is kept too, for streams where it is the only record.
        artifact_id: str | None = evt(event, "artifact_id")
        collected = self._phase_artifact_ids.setdefault(phase_id, [])
        if artifact_id and artifact_id not in collected:
            collected.append(artifact_id)

    @event_sourcing_handler("PhaseRetryScheduled")
    def on_phase_retry_scheduled(self, event: PhaseRetryScheduledEvent) -> None:
        """Apply PhaseRetryScheduledEvent — the attempt is over, the phase is not.

        `_running_phase_id` is cleared because no attempt is running until the
        retry's own `PhaseStarted` arrives, and a failure in that window names
        no phase rather than naming the abandoned attempt.

        `_completed_phases` is deliberately untouched: nothing completed.
        Anything the abandoned attempt collected goes with it, so a resume never
        inherits an artifact from an attempt that was given up.
        """
        self._running_phase_id = None
        self._phase_artifact_ids.pop(evt(event, "phase_id"), None)

    @event_sourcing_handler("WorkspaceProvisionedForPhase")
    def on_workspace_provisioned_for_phase(self, event: WorkspaceProvisionedForPhaseEvent) -> None:
        """Apply WorkspaceProvisionedForPhaseEvent."""
        self._current_phase_workspace_id = evt(event, "workspace_id")
        if self._starting_checkout is None:
            self._starting_checkout = read_source_commits(evt(event, "checked_out_commits"))

    @event_sourcing_handler("AgentExecutionCompleted")
    def on_agent_execution_completed(self, event: AgentExecutionCompletedEvent) -> None:
        """Apply AgentExecutionCompletedEvent — keep what the agent left behind."""
        reported_for: str = evt(event, "phase_id") or ""
        if reported_for:
            # Overwritten by every run, so a retry that says nothing does not
            # inherit the abandoned attempt's report.
            self._reported_side_effects[reported_for] = SideEffectStatus.from_stored(
                evt(event, "reported_side_effects")
            )
            self._reviews.report(
                reported_for, ReviewVerdict.from_stored(evt(event, "reported_review_verdict"))
            )
        said = evt(event, "last_agent_message")
        if not said:
            return
        phase_id: str = evt(event, "phase_id") or ""
        if not phase_id:
            return
        self._finished_agent_runs[phase_id] = FinishedAgentRun(
            phase_id=phase_id,
            phase_name=self._phase_names.get(phase_id, phase_id),
            session_id=evt(event, "session_id") or "",
            last_agent_message=said,
        )

    @event_sourcing_handler("ArtifactsCollectedForPhase")
    def on_artifacts_collected_for_phase(self, event: ArtifactsCollectedForPhaseEvent) -> None:
        """Apply ArtifactsCollectedForPhaseEvent."""
        self._artifact_ids.extend(evt(event, "artifact_ids", []))
        phase_id = evt(event, "phase_id")
        self._phase_artifact_ids.setdefault(phase_id, []).extend(evt(event, "artifact_ids", []))
        if evt(event, "deliverable_recovered", False):
            self._recovered_phases.add(phase_id)
        # The salvage input has done its job for this phase and stops being
        # replayed state: a later to-do item for the same phase must re-read
        # the deliverable, never re-salvage from a stale message. Dropping it
        # is also what makes `stranded_deliverable` answer None once the
        # output is safely stored.
        self._finished_agent_runs.pop(phase_id, None)
        self._reviews.collect(phase_id)

    @event_sourcing_handler("NextPhaseReady")
    def on_next_phase_ready(self, _event: NextPhaseReadyEvent) -> None:
        """Apply NextPhaseReadyEvent — to-do list projection reacts, not aggregate."""

    @event_sourcing_handler("ExecutionCancelled")
    def on_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Apply ExecutionCancelledEvent."""
        self._completed_at = evt(event, "cancelled_at")
        self._status = ExecutionStatus.CANCELLED
        self._cancel_reason = event.reason

    @event_sourcing_handler("WorkflowInterrupted")
    def on_execution_interrupted(self, event: WorkflowInterruptedEvent) -> None:
        """Apply WorkflowInterruptedEvent."""
        self._completed_at = evt(event, "interrupted_at")
        self._status = ExecutionStatus.INTERRUPTED

    @event_sourcing_handler("ExecutionResumed")
    def on_execution_resumed(self, event: ExecutionResumedEvent) -> None:
        """Apply ExecutionResumedEvent - the parent's one resume is spent.

        Status is deliberately untouched: the parent stays the terminal run it
        was, and only this fact about it is new. The payload's shape is the
        gate (`resumed_event_applies`), not only the event's validator.
        """
        if not resumed_event_applies(event, self.id):
            return
        self._resumed = True
        self._resume_execution_id = evt(event, "resume_execution_id")
        self._admitted_resume = read_admitted_resume(event)

    @event_sourcing_handler("ExecutionForked")
    def on_execution_forked(self, event: ExecutionResumedEvent) -> None:
        """Apply a pre-rename `ExecutionForked` as the resume it always was.

        Registered because the rename moved the `@event` registration to
        `ExecutionResumed`, so a stored `ExecutionForked` resolves to no
        concrete class, replays as a generic event and would route NOWHERE.
        Being dropped is worse than failing: the parent would look unresumed
        and a second resume would be admitted, which is the one thing the
        one-resume rule exists to prevent.

        The concept never changed, only its name, so the payload maps field for
        field (`upcast_forked_payload`).
        """
        admitted = read_admitted_forked_resume(event)
        self._resumed = True
        self._resume_execution_id = admitted.resume_execution_id
        self._admitted_resume = admitted
