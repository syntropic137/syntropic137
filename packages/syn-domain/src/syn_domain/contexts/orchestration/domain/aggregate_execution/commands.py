"""Command classes for WorkflowExecution aggregate.

Extracted from WorkflowExecutionAggregate to keep module under LOC threshold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration._shared.tags import TagSet

# Runtime import: FailExecutionCommand defaults an absent usage to zeros rather
# than carrying None into the aggregate, so the class is constructed here.
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import PhaseUsage

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
        ContinuedBranch,
        RemoteBranchReading,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        ResumeOrigin,
        SourceCommit,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation,
        DelegationFailure,
        ExecutablePhase,
        FailureClassification,
        PhaseDefinition,
        ReportedFailureReason,
        ReviewVerdict,
        SideEffectStatus,
    )


class StartExecutionCommand:
    """Command to start a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        workflow_name: str,
        total_phases: int,
        inputs: dict[str, Any],
        expected_completion_at: datetime | None = None,
        phase_definitions: list[PhaseDefinition] | None = None,
        pinned_phases: list[ExecutablePhase] | None = None,
        source_commits: list[SourceCommit] | None = None,
        tags: TagSet | None = None,
        launch_eval: LaunchEval | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.total_phases = total_phases
        self.inputs = inputs
        self.expected_completion_at = expected_completion_at
        self.phase_definitions = phase_definitions
        self.pinned_phases = pinned_phases
        self.source_commits = source_commits
        # The launch snapshot (#967): workflow tags united with request tags.
        self.tags = tags or TagSet()
        # The eval this launch joins, resolved at dispatch (#967).
        self.launch_eval = launch_eval or LaunchEval(None, EvalSelection.NONE)


class StartResumeCommand:
    """Command to start the execution a parent's resume admitted (ADR-014 s7).

    Addressed to the CHILD: `execution_id` is the resume's own id, the one the
    parent's `ExecutionResumed` named. Built from the parent's stream by
    `WorkflowExecutionAggregate.resume_start_command`, never from the workflow
    template, so every field here is what the parent ran with (#1454, #1457).
    """

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        workflow_name: str,
        inputs: dict[str, str],
        pinned_phases: list[ExecutablePhase],
        source_commits: list[SourceCommit],
        resumed_from: ResumeOrigin,
        continuation_candidates: list[ContinuedBranch] | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.inputs = inputs
        self.pinned_phases = pinned_phases
        self.source_commits = source_commits
        self.resumed_from = resumed_from
        #: The branches the parent's failing attempt at the resumed phase left
        #: on origin (#1513). Read back from the parent's stream.
        self.continuation_candidates = continuation_candidates or []
        #: What the forge says about each candidate now. Filled in by
        #: `StartResumeHandler` before the start; the aggregate decides from it
        #: (`branch_continuation.decide_continuation`).
        self.remote_branches: list[RemoteBranchReading] = []


class CompleteExecutionCommand:
    """Command to mark a workflow execution as completed.

    Tokens are domain truth (Lane 1). Cost is Lane 2 telemetry and is not
    carried on this command — see execution_cost projection.
    """

    def __init__(
        self,
        execution_id: str,
        completed_phases: int,
        total_phases: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cache_creation_tokens: int,
        total_cache_read_tokens: int,
        duration_seconds: float,
        artifact_ids: list[str],
    ) -> None:
        self.aggregate_id = execution_id
        self.completed_phases = completed_phases
        self.total_phases = total_phases
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.total_cache_creation_tokens = total_cache_creation_tokens
        self.total_cache_read_tokens = total_cache_read_tokens
        self.duration_seconds = duration_seconds
        self.artifact_ids = artifact_ids


class FailExecutionCommand:
    """Command to mark a workflow execution as failed."""

    def __init__(
        self,
        execution_id: str,
        error: str,
        error_type: str | None,
        failed_phase_id: str | None,
        completed_phases: int,
        total_phases: int,
        classification: FailureClassification,
        failed_phase_duration_seconds: float | None = None,
        observed_branches: tuple[BranchObservation, ...] | None = None,
        exit_code: int | None = None,
        failed_phase_artifact_ids: tuple[str, ...] = (),
        failed_phase_usage: PhaseUsage | None = None,
        reported_failure_reason: ReportedFailureReason | None = None,
        delegation_failure: DelegationFailure | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.error = error
        self.error_type = error_type
        self.failed_phase_id = failed_phase_id
        self.completed_phases = completed_phases
        self.total_phases = total_phases
        self.failed_phase_duration_seconds = failed_phase_duration_seconds
        #: Where the failed phase's branches stood when it died (#1200).
        #: THREE-VALUED: records are readings taken from git, `()` says the
        #: workspace was read and no branch differs from how the phase found
        #: it, and None says nobody could read it. A failure whose branch moved
        #: and one that left nothing anywhere are different incidents, and this
        #: is what keeps them apart downstream. DIFFERENCE FROM THE STARTING
        #: POINT, not authorship: the branch a phase starts on is normally
        #: already pushed, so recording every branch would give every failure a
        #: location, and no ref records whose push moved it.
        self.observed_branches = observed_branches
        #: What the failed phase's process exited with (#1319). None means
        #: nothing observed a status - an execution stranded by a restart has
        #: no process left to ask - and is NOT the same as 0. Callers that
        #: reconcile a run they did not watch leave this absent rather than
        #: inventing a number the reap already made unknowable.
        self.exit_code = exit_code
        #: What the failed phase had already written, kept out of its workspace
        #: before this failure tore it down (#1321). `()` when it wrote nothing
        #: collectable, which is every failure that got this far before.
        #:
        #: NOT three-valued, unlike the field above: "nothing was kept" and
        #: "nobody looked" need no telling apart here, because the collection
        #: is attempted on every path that reaches this command and cannot
        #: raise. Failing to store an artifact is logged where it happens and
        #: leaves this empty - the same answer as a phase that wrote nothing,
        #: and the same consequence either way.
        self.failed_phase_artifact_ids = failed_phase_artifact_ids
        #: What the failed phase had spent when it died (#1262), zeros when its
        #: agent never ran. Here rather than only in `error_message`, which is
        #: where these counts lived: an exit 124 reporting `(tokens=190+545)` in
        #: prose was a phase that had stalled, and an exit 124 with 171 messages
        #: and 133 tool calls behind it needed a bigger budget. Same exit code,
        #: opposite responses, and no field either could be sorted on.
        self.failed_phase_usage = failed_phase_usage or PhaseUsage()
        #: Whether the machinery failed or the work was correctly judged not
        #: deliverable (#1357). REQUIRED, unlike every optional field above,
        #: and the only field on this command that is: there are three places
        #: in production that fail an execution, they fail it for genuinely
        #: different reasons, and a default here would let a new fourth one
        #: inherit whichever answer happened to be written years earlier. Two
        #: of the three are unambiguously the platform - a restart orphaning a
        #: run, a stale-execution sweep - and saying so at those call sites is
        #: documentation a default would delete.
        self.classification = classification
        #: What the failing PHASE said caused it (#1372), `None` when it said
        #: nothing this reader knows - which is every one of the three call
        #: sites above except the one that read an agent's own report, and is
        #: why this defaults where the field above does not. Carried beside
        #: the classification and never folded into it (#1392): an operator
        #: reads the agent's word, and no number is computed from it.
        self.reported_failure_reason = reported_failure_reason
        #: Which required delegate did not happen, and why (#894). `None` for
        #: every failure that is not a failed delegation - every call site but
        #: the one whose phase declared one.
        self.delegation_failure = delegation_failure


class StartPhaseCommand:
    """Command to start a phase execution."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        phase_name: str,
        phase_order: int,
        session_id: str | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.phase_name = phase_name
        self.phase_order = phase_order
        self.session_id = session_id


class RetryPhaseCommand:
    """Command to abandon this phase's current attempt and start another (#1335).

    Carries `reason` because the aggregate refuses on the budget, not on the
    fault: whether a fault is worth another attempt is a judgement about the
    agent harness's stream and belongs to the slice that reads it, while how
    many attempts a phase may have is a rule about the execution and belongs
    here. The reason travels so the event can record it either way.
    """

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        reason: str,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.reason = reason


class CompletePhaseCommand:
    """Command to mark a phase as completed with metrics.

    Tokens are domain truth (Lane 1). Cost is Lane 2 telemetry and is not
    carried on this command — see session_cost / execution_cost projections.
    """

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        session_id: str | None,
        artifact_id: str | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        total_tokens: int,
        duration_seconds: float,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.session_id = session_id
        self.artifact_id = artifact_id
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_tokens = cache_creation_tokens
        self.cache_read_tokens = cache_read_tokens
        self.total_tokens = total_tokens
        self.duration_seconds = duration_seconds


class CancelExecutionCommand:
    """Command to cancel a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.reason = reason


class InterruptExecutionCommand:
    """Command to forcefully interrupt a workflow execution mid-stream."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        git_sha: str | None = None,
        partial_artifact_ids: list[str] | None = None,
        reason: str | None = None,
        partial_input_tokens: int = 0,
        partial_output_tokens: int = 0,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.git_sha = git_sha
        self.partial_artifact_ids = partial_artifact_ids or []
        self.reason = reason
        self.partial_input_tokens = partial_input_tokens
        self.partial_output_tokens = partial_output_tokens


class ProvisionWorkspaceCompletedCommand:
    """Command reported by WorkspaceProvisionHandler after workspace is ready.

    `checked_out_commits` is where each pinned repository was actually found,
    read back off the workspace once setup finished and verified against its
    pin (#967) - the run's recorded starting state, not its request.
    """

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        workspace_id: str,
        session_id: str = "",
        checked_out_commits: Sequence[SourceCommit] = (),
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.workspace_id = workspace_id
        self.session_id = session_id
        self.checked_out_commits = tuple(checked_out_commits)


class AgentExecutionCompletedCommand:
    """Command reported by AgentExecutionHandler after agent finishes.

    `last_agent_message` is the closing message the agent produced on its own
    stream, and it is on this command - rather than held by the processor -
    because it is the salvage input (#1195, #1300) and the salvage has to work
    after a restart. See `AgentExecutionCompletedEvent.last_agent_message`.
    """

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        session_id: str | None,
        exit_code: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        last_agent_message: str | None = None,
        reported_side_effects: SideEffectStatus | None = None,
        reported_review_verdict: ReviewVerdict | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.session_id = session_id
        self.exit_code = exit_code
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_tokens = cache_creation_tokens
        self.cache_read_tokens = cache_read_tokens
        self.last_agent_message = last_agent_message
        self.reported_side_effects = reported_side_effects
        self.reported_review_verdict = reported_review_verdict


class ArtifactsCollectedCommand:
    """Command reported by ArtifactCollectionHandler after outputs stored."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        artifact_ids: list[str],
        first_content_preview: str | None = None,
        session_id: str | None = None,
        deliverable_recovered: bool = False,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.artifact_ids = artifact_ids
        self.first_content_preview = first_content_preview
        self.session_id = session_id
        #: Whether what was stored came from the transcript rather than from
        #: disk. Collection is the only place that knows, and the phase does
        #: not complete until a later to-do item, so the fact has to be told
        #: to the aggregate here or be lost (#1195, #1300).
        self.deliverable_recovered = deliverable_recovered


class ResumeExecutionCommand:
    """Command to resume a terminal execution into a new one (ADR-014 s7).

    Addressed to the PARENT: `execution_id` is the execution being resumed and
    `resume_execution_id` the id the new run will have. The parent decides.

    Both flags are separate, explicit operator decisions and default to the
    refusal. `override_cancellation` is the only way to resume a CANCELLED
    parent: a cancel is an instruction to stop, and a resume must not defeat it
    without a fresh decision. `acknowledge_external_effects` accepts that the
    phase the resume re-runs may have pushed or published something in the
    parent that re-running repeats. Neither implies the other.
    """

    def __init__(
        self,
        execution_id: str,
        resume_execution_id: str,
        override_cancellation: bool = False,
        acknowledge_external_effects: bool = False,
    ) -> None:
        self.aggregate_id = execution_id
        self.resume_execution_id = resume_execution_id
        self.override_cancellation = override_cancellation
        self.acknowledge_external_effects = acknowledge_external_effects
